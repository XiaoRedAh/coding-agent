"""
Module evaluation: Context compression pipeline (services/compact.py)
Cost: $0 | LLM required: No
Run: python eval/eval_compact.py
"""
import sys
import os
import time
import json
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from services.compact import (
    TokenTracker, CircuitBreaker,
    budget_tool_results, snip_stale_results, microcompact,
    run_compression_pipeline, SNIP_PLACEHOLDER, CLEARED_PLACEHOLDER,
    SNIPPABLE_TOOLS, _extract_summary,
)
from bootstrap.state import (
    BUDGET_THRESHOLD, BUDGET_TIGHT_THRESHOLD, SNIP_THRESHOLD,
    BUDGET_NORMAL, BUDGET_TIGHT, SNIP_KEEP_RECENT,
    MICROCOMPACT_IDLE_SECONDS, MAX_AUTOCOMPACT_FAILURES,
    EFFECTIVE_WINDOW,
)


@dataclass
class EvalResult:
    category: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    details: list = field(default_factory=list)

    @property
    def accuracy(self):
        return self.passed / self.total if self.total else 0.0

    def record(self, success, desc, expected="", actual=""):
        self.total += 1
        if success:
            self.passed += 1
        else:
            self.failed += 1
            self.details.append(f"  FAIL: {desc} (expected={expected}, actual={actual})")


# ──────────────────────────────────────────────
#  Helpers: construct messages
# ──────────────────────────────────────────────

def _make_tool_result(tool_use_id: str, content: str) -> dict:
    return {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}
        ],
    }


def _make_tool_use(tool_use_id: str, name: str, inp: dict) -> dict:
    return {
        "role": "assistant",
        "content": [
            {"type": "tool_use", "id": tool_use_id, "name": name, "input": inp}
        ],
    }


def _make_messages_with_tool_results(n: int, content_size: int = 200) -> list:
    """Create n pairs of tool_use + tool_result messages."""
    msgs = []
    for i in range(n):
        tid = f"tu_{i}"
        msgs.append(_make_tool_use(tid, "read_file", {"file_path": f"file_{i}.py"}))
        msgs.append(_make_tool_result(tid, "x" * content_size))
    return msgs


# ──────────────────────────────────────────────
#  1. TokenTracker evaluation
# ──────────────────────────────────────────────

def evaluate_token_tracker() -> EvalResult:
    r = EvalResult("TokenTracker")

    # 1.1 Initial state
    t = TokenTracker()
    r.record(t.estimate_current_tokens() == 0, "initial tokens = 0", "0", str(t.estimate_current_tokens()))
    r.record(t.get_utilization() == 0.0, "initial utilization = 0", "0.0", str(t.get_utilization()))

    # 1.2 Tracking new messages (no anchor yet)
    t.track_new_message({"role": "user", "content": "x" * 300})
    est = t.estimate_current_tokens()
    r.record(est > 0, "estimate > 0 after tracking", ">0", str(est))

    # 1.3 Update from mock response (anchor update)
    class MockResp:
        input_tokens = 5000
        output_tokens = 1000
    t.update_from_response(MockResp())
    r.record(t.last_input_tokens == 5000, "anchor updated", "5000", str(t.last_input_tokens))
    r.record(t.total_input_tokens == 5000, "total input updated", "5000", str(t.total_input_tokens))
    r.record(t.messages_since_anchor == 0, "counter reset", "0", str(t.messages_since_anchor))

    # 1.4 Estimate after anchor + new messages
    t.track_new_message({"role": "user", "content": "y" * 600})
    est = t.estimate_current_tokens()
    r.record(est > 5000, "estimate > anchor after new msg", ">5000", str(est))

    # 1.5 Utilization calculation
    util = t.get_utilization()
    expected_util = est / EFFECTIVE_WINDOW
    r.record(abs(util - expected_util) < 0.001, "utilization correct", f"{expected_util:.4f}", f"{util:.4f}")

    # 1.6 Reset after compact
    t.reset_after_compact()
    r.record(t.last_input_tokens == 0, "reset clears anchor", "0", str(t.last_input_tokens))
    r.record(t.estimate_current_tokens() == 0, "reset clears estimate", "0", str(t.estimate_current_tokens()))

    return r


# ──────────────────────────────────────────────
#  2. budget_tool_results evaluation
# ──────────────────────────────────────────────

def evaluate_budget() -> EvalResult:
    r = EvalResult("budget_tool_results (L1)")

    # 2.1 Below threshold — no truncation
    msgs = [_make_tool_result("t1", "a" * 40000)]
    budget_tool_results(msgs, 0.40)
    content = msgs[0]["content"][0]["content"]
    r.record(len(content) == 40000, "below 50% no truncation", "40000", str(len(content)))

    # 2.2 Normal budget (50-70%) — truncate > 30K
    msgs = [_make_tool_result("t2", "b" * 40000)]
    budget_tool_results(msgs, 0.60)
    content = msgs[0]["content"][0]["content"]
    r.record(len(content) < 40000, "60% truncates >30K", "<40000", str(len(content)))
    r.record("budgeted" in content, "truncation marker present", "budgeted", content[:200])

    # 2.3 Content under budget not truncated at normal level
    msgs = [_make_tool_result("t3", "c" * 20000)]
    budget_tool_results(msgs, 0.60)
    content = msgs[0]["content"][0]["content"]
    r.record(len(content) == 20000, "60% keeps <30K intact", "20000", str(len(content)))

    # 2.4 Tight budget (>70%) — truncate > 15K
    msgs = [_make_tool_result("t4", "d" * 20000)]
    budget_tool_results(msgs, 0.75)
    content = msgs[0]["content"][0]["content"]
    r.record(len(content) < 20000, "75% truncates >15K", "<20000", str(len(content)))

    # 2.5 Compression ratio measurement
    original_size = 40000
    msgs = [_make_tool_result("t5", "e" * original_size)]
    budget_tool_results(msgs, 0.60)
    compressed_size = len(msgs[0]["content"][0]["content"])
    ratio = compressed_size / original_size
    r.record(ratio < 1.0, f"compression ratio < 1.0 at 60%", "<1.0", f"{ratio:.2f}")

    return r


# ──────────────────────────────────────────────
#  3. snip_stale_results evaluation
# ──────────────────────────────────────────────

def evaluate_snip() -> EvalResult:
    r = EvalResult("snip_stale_results (L2)")

    # 3.1 Below threshold — no snipping
    msgs = _make_messages_with_tool_results(6, 500)
    snip_stale_results(msgs, 0.40)
    snipped = sum(1 for m in msgs if m.get("role") == "user"
                  and isinstance(m.get("content"), list)
                  and any(b.get("content") == SNIP_PLACEHOLDER
                          for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"))
    r.record(snipped == 0, "below threshold no snip", "0", str(snipped))

    # 3.2 Above threshold — keeps recent SNIP_KEEP_RECENT
    msgs = _make_messages_with_tool_results(8, 500)
    snip_stale_results(msgs, 0.65)
    tool_results = []
    for m in msgs:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tool_results.append(b)
    not_snipped = [b for b in tool_results if b.get("content") != SNIP_PLACEHOLDER]
    r.record(len(not_snipped) >= SNIP_KEEP_RECENT,
             f"keeps recent {SNIP_KEEP_RECENT}", f">={SNIP_KEEP_RECENT}", str(len(not_snipped)))

    # 3.3 Snipped ones have placeholder
    snipped_blocks = [b for b in tool_results if b.get("content") == SNIP_PLACEHOLDER]
    r.record(len(snipped_blocks) > 0, "some blocks snipped", ">0", str(len(snipped_blocks)))

    # 3.4 Too few results — no snipping
    msgs = _make_messages_with_tool_results(2, 500)
    snip_stale_results(msgs, 0.65)
    snipped = sum(1 for m in msgs if m.get("role") == "user"
                  and isinstance(m.get("content"), list)
                  and any(b.get("content") == SNIP_PLACEHOLDER
                          for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"))
    r.record(snipped == 0, "<=3 results not snipped", "0", str(snipped))

    return r


# ──────────────────────────────────────────────
#  4. microcompact evaluation
# ──────────────────────────────────────────────

def evaluate_microcompact() -> EvalResult:
    r = EvalResult("microcompact (L3)")

    # 4.1 Not triggered when no API call yet
    tracker = TokenTracker()
    msgs = _make_messages_with_tool_results(5, 200)
    microcompact(msgs, tracker)
    cleared = sum(1 for m in msgs if m.get("role") == "user"
                  and isinstance(m.get("content"), list)
                  and any(b.get("content") == CLEARED_PLACEHOLDER
                          for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"))
    r.record(cleared == 0, "no API call = no microcompact", "0", str(cleared))

    # 4.2 Not triggered when recent API call
    tracker.last_api_call_time = time.time()
    msgs = _make_messages_with_tool_results(5, 200)
    microcompact(msgs, tracker)
    cleared = sum(1 for m in msgs if m.get("role") == "user"
                  and isinstance(m.get("content"), list)
                  and any(b.get("content") == CLEARED_PLACEHOLDER
                          for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"))
    r.record(cleared == 0, "recent API call = no microcompact", "0", str(cleared))

    # 4.3 Triggered when idle > MICROCOMPACT_IDLE_SECONDS
    tracker.last_api_call_time = time.time() - MICROCOMPACT_IDLE_SECONDS - 10
    msgs = _make_messages_with_tool_results(5, 200)
    microcompact(msgs, tracker)
    cleared = sum(1 for m in msgs if m.get("role") == "user"
                  and isinstance(m.get("content"), list)
                  and any(b.get("content") == CLEARED_PLACEHOLDER
                          for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"))
    r.record(cleared > 0, "idle triggers microcompact", ">0", str(cleared))

    # 4.4 Keeps last 1 result
    tool_results = []
    for m in msgs:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tool_results.append(b)
    not_cleared = [b for b in tool_results if b.get("content") != CLEARED_PLACEHOLDER]
    r.record(len(not_cleared) >= 1, "keeps last 1 result", ">=1", str(len(not_cleared)))

    return r


# ──────────────────────────────────────────────
#  5. CircuitBreaker evaluation
# ──────────────────────────────────────────────

def evaluate_circuit_breaker() -> EvalResult:
    r = EvalResult("CircuitBreaker")

    cb = CircuitBreaker()

    # 5.1 Initial state is CLOSED
    r.record(cb.state == "CLOSED", "initial CLOSED", "CLOSED", cb.state)
    r.record(not cb.should_skip(), "CLOSED does not skip", "False", str(cb.should_skip()))

    # 5.2 One failure -> HALF_OPEN
    cb.record_failure()
    r.record(cb.state == "HALF_OPEN", "1 failure = HALF_OPEN", "HALF_OPEN", cb.state)
    r.record(not cb.should_skip(), "HALF_OPEN does not skip", "False", str(cb.should_skip()))

    # 5.3 Reach threshold -> OPEN
    for _ in range(MAX_AUTOCOMPACT_FAILURES - 1):
        cb.record_failure()
    r.record(cb.state == "OPEN", f"{MAX_AUTOCOMPACT_FAILURES} failures = OPEN", "OPEN", cb.state)
    r.record(cb.should_skip(), "OPEN skips", "True", str(cb.should_skip()))

    # 5.4 Success resets to CLOSED
    cb.record_success()
    r.record(cb.state == "CLOSED", "success resets to CLOSED", "CLOSED", cb.state)
    r.record(cb.consecutive_failures == 0, "counter reset to 0", "0", str(cb.consecutive_failures))

    return r


# ──────────────────────────────────────────────
#  6. Compression ratio measurement
# ──────────────────────────────────────────────

def evaluate_compression_metrics() -> EvalResult:
    r = EvalResult("Compression Metrics")

    # Build a realistic message set
    msgs = _make_messages_with_tool_results(10, 35000)  # 10 large tool results

    # Measure before
    before_chars = sum(len(json.dumps(m, default=str)) for m in msgs)
    before_tokens_est = before_chars // 3

    # Run L1 at 60% utilization
    budget_tool_results(msgs, 0.60)
    after_chars = sum(len(json.dumps(m, default=str)) for m in msgs)
    after_tokens_est = after_chars // 3

    savings_pct = 1 - (after_chars / before_chars) if before_chars > 0 else 0
    r.record(after_chars < before_chars, "L1 reduces size", f"<{before_chars}", str(after_chars))
    r.record(savings_pct > 0.05, f"L1 savings > 5% (got {savings_pct:.1%})", ">5%", f"{savings_pct:.1%}")

    # Run L2 snip at 65%
    snip_stale_results(msgs, 0.65)
    after_snip_chars = sum(len(json.dumps(m, default=str)) for m in msgs)
    snip_savings = 1 - (after_snip_chars / after_chars) if after_chars > 0 else 0
    r.record(after_snip_chars <= after_chars, "L2 further reduces or same", f"<={after_chars}", str(after_snip_chars))

    return r


# ──────────────────────────────────────────────
#  7. _extract_summary evaluation
# ──────────────────────────────────────────────

def evaluate_extract_summary() -> EvalResult:
    r = EvalResult("Summary Extraction")

    # 7.1 Proper format
    raw = "<analysis>thinking...</analysis>\n<summary>The real summary.</summary>"
    out = _extract_summary(raw)
    r.record(out == "The real summary.", "extracts summary block", "The real summary.", out[:60])

    # 7.2 Fallback when no tags
    raw2 = "Just plain text without tags"
    out2 = _extract_summary(raw2)
    r.record(out2 == raw2, "fallback to raw", raw2[:30], out2[:30])

    # 7.3 Multi-line summary
    raw3 = "<analysis>a</analysis>\n<summary>\nLine 1\nLine 2\n</summary>"
    out3 = _extract_summary(raw3)
    r.record("Line 1" in out3 and "Line 2" in out3, "multi-line summary", "Line1+Line2", out3[:60])

    return r


# ──────────────────────────────────────────────
#  Report generation
# ──────────────────────────────────────────────

def run_full_evaluation():
    evaluators = [
        ("TokenTracker", evaluate_token_tracker),
        ("budget_tool_results", evaluate_budget),
        ("snip_stale_results", evaluate_snip),
        ("microcompact", evaluate_microcompact),
        ("CircuitBreaker", evaluate_circuit_breaker),
        ("Compression Metrics", evaluate_compression_metrics),
        ("Summary Extraction", evaluate_extract_summary),
    ]

    results = []
    for name, fn in evaluators:
        try:
            results.append(fn())
        except Exception as e:
            er = EvalResult(name)
            er.record(False, f"evaluator crashed: {e}")
            results.append(er)

    total_cases = sum(r.total for r in results)
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)

    print("=" * 70)
    print("  Context Compression Evaluation Report")
    print("=" * 70)
    print()

    for r in results:
        status = "PASS" if r.failed == 0 else "FAIL"
        print(f"[{status}] {r.category}: {r.passed}/{r.total} ({r.accuracy:.1%})")
        for detail in r.details:
            print(detail)

    print()
    print("-" * 70)
    overall = total_passed / total_cases if total_cases else 0
    print(f"  Total: {total_passed}/{total_cases} ({overall:.1%})")
    print(f"  Passed: {total_passed}  Failed: {total_failed}")
    print(f"  Test cases: {total_cases}")
    print(f"  API calls: 0  |  Cost: $0")
    print("-" * 70)

    return total_failed == 0


# ──────────────────────────────────────────────
#  pytest compatible
# ──────────────────────────────────────────────

def test_token_tracker():
    r = evaluate_token_tracker()
    assert r.accuracy >= 0.90, f"TokenTracker accuracy {r.accuracy:.1%} < 90%"

def test_budget_tool_results():
    r = evaluate_budget()
    assert r.accuracy >= 0.90, f"budget accuracy {r.accuracy:.1%} < 90%"

def test_snip_stale():
    r = evaluate_snip()
    assert r.accuracy >= 0.90, f"snip accuracy {r.accuracy:.1%} < 90%"

def test_microcompact():
    r = evaluate_microcompact()
    assert r.accuracy >= 0.90, f"microcompact accuracy {r.accuracy:.1%} < 90%"

def test_circuit_breaker():
    r = evaluate_circuit_breaker()
    assert r.accuracy == 1.0, f"CircuitBreaker accuracy {r.accuracy:.1%} < 100%"

def test_compression_metrics():
    r = evaluate_compression_metrics()
    assert r.accuracy >= 0.80, f"compression metrics accuracy {r.accuracy:.1%} < 80%"

def test_extract_summary():
    r = evaluate_extract_summary()
    assert r.accuracy >= 0.90, f"extract_summary accuracy {r.accuracy:.1%} < 90%"


if __name__ == "__main__":
    success = run_full_evaluation()
    sys.exit(0 if success else 1)
