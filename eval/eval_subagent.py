"""
Module evaluation: SubAgent system (agents/subagent.py + agents/definitions.py)
Cost: ~$0.05-0.50 (for LLM tests) | LLM required: Yes (partial)
Run: python eval/eval_subagent.py

Tests marked with [LLM] require a real API key and will be skipped otherwise.
"""
import sys
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from agents.definitions import (
    AGENT_DEFINITIONS, READ_ONLY_TOOLS, GENERAL_TOOLS,
    get_agent_config, get_filtered_tools,
)

# Check if real API key is available for LLM tests
def _check_api_key():
    provider = os.environ.get("LLM_PROVIDER", "anthropic")
    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        return bool(key) and len(key) > 10
    key = os.environ.get("ANTHROPIC_API_KEY", "test-key")
    return key != "test-key" and len(key) > 10

_HAS_API_KEY = _check_api_key()


@dataclass
class EvalResult:
    category: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    details: list = field(default_factory=list)

    @property
    def accuracy(self):
        effective = self.total - self.skipped
        return self.passed / effective if effective > 0 else 0.0

    def record(self, success, desc, expected="", actual=""):
        self.total += 1
        if success:
            self.passed += 1
        else:
            self.failed += 1
            self.details.append(f"  FAIL: {desc} (expected={expected}, actual={actual})")

    def skip(self, desc, reason="no API key"):
        self.total += 1
        self.skipped += 1
        self.details.append(f"  SKIP: {desc} ({reason})")


# ──────────────────────────────────────────────
#  1. Agent definitions completeness
# ──────────────────────────────────────────────

def evaluate_definitions() -> EvalResult:
    r = EvalResult("Agent Definitions")

    # 1.1 All 4 agent types defined
    expected_types = {"explore", "plan", "general", "verification"}
    actual_types = set(AGENT_DEFINITIONS.keys())
    r.record(expected_types == actual_types, "4 agent types defined",
             str(expected_types), str(actual_types))

    # 1.2 Each definition has required keys
    required_keys = {"system_prompt", "allowed_tools", "max_turns", "description", "when_to_use", "background"}
    for agent_type, config in AGENT_DEFINITIONS.items():
        missing = required_keys - set(config.keys())
        r.record(len(missing) == 0, f"{agent_type} has all required keys",
                 "all keys", f"missing: {missing}" if missing else "all keys")

    # 1.3 get_agent_config works
    config = get_agent_config("explore")
    r.record(config is not None, "get_agent_config returns config", "not None", str(type(config)))

    # 1.4 get_agent_config raises on unknown type
    try:
        get_agent_config("nonexistent_type")
        r.record(False, "unknown type raises ValueError", "ValueError", "no exception")
    except ValueError:
        r.record(True, "unknown type raises ValueError", "ValueError", "ValueError")

    return r


# ──────────────────────────────────────────────
#  2. Agent type tool filtering
# ──────────────────────────────────────────────

def evaluate_tool_filtering() -> EvalResult:
    r = EvalResult("Tool Filtering")

    # 2.1 Explore has read-only tools
    explore_tools = AGENT_DEFINITIONS["explore"]["allowed_tools"]
    r.record(explore_tools == READ_ONLY_TOOLS, "explore uses READ_ONLY_TOOLS",
             str(READ_ONLY_TOOLS), str(explore_tools))

    # 2.2 Explore should NOT have write_file
    r.record("write_file" not in explore_tools, "explore has no write_file",
             "absent", "present" if "write_file" in explore_tools else "absent")

    # 2.3 Explore should NOT have edit_file
    r.record("edit_file" not in explore_tools, "explore has no edit_file",
             "absent", "present" if "edit_file" in explore_tools else "absent")

    # 2.4 General has all file tools
    general_tools = AGENT_DEFINITIONS["general"]["allowed_tools"]
    r.record(general_tools == GENERAL_TOOLS, "general uses GENERAL_TOOLS",
             str(GENERAL_TOOLS), str(general_tools))

    # 2.5 General has write_file and edit_file
    r.record("write_file" in general_tools, "general has write_file", "present", "absent")
    r.record("edit_file" in general_tools, "general has edit_file", "present", "absent")

    # 2.6 No agent type allows recursive "agent" tool
    for atype, config in AGENT_DEFINITIONS.items():
        r.record("agent" not in config["allowed_tools"],
                 f"{atype} has no 'agent' tool (no recursion)", "absent", "present")

    # 2.7 Verification is read-only
    verif_tools = AGENT_DEFINITIONS["verification"]["allowed_tools"]
    r.record(verif_tools == READ_ONLY_TOOLS, "verification uses READ_ONLY_TOOLS",
             str(READ_ONLY_TOOLS), str(verif_tools))

    # 2.8 Plan is read-only
    plan_tools = AGENT_DEFINITIONS["plan"]["allowed_tools"]
    r.record(plan_tools == READ_ONLY_TOOLS, "plan uses READ_ONLY_TOOLS",
             str(READ_ONLY_TOOLS), str(plan_tools))

    return r


# ──────────────────────────────────────────────
#  3. System prompt content
# ──────────────────────────────────────────────

def evaluate_system_prompts() -> EvalResult:
    r = EvalResult("System Prompts")

    # 3.1 Explore prompt contains READ-ONLY constraint
    explore_prompt = AGENT_DEFINITIONS["explore"]["system_prompt"]
    r.record("READ-ONLY" in explore_prompt or "READ_ONLY" in explore_prompt or "read-only" in explore_prompt.lower(),
             "explore prompt has READ-ONLY", "READ-ONLY", explore_prompt[:80])

    # 3.2 Verification prompt mentions adversarial testing
    verif_prompt = AGENT_DEFINITIONS["verification"]["system_prompt"]
    r.record("adversarial" in verif_prompt.lower() or "PROVE" in verif_prompt,
             "verification prompt is adversarial", "adversarial", verif_prompt[:80])

    # 3.3 General prompt is concise
    general_prompt = AGENT_DEFINITIONS["general"]["system_prompt"]
    r.record(len(general_prompt) < 500, "general prompt is concise", "<500 chars", str(len(general_prompt)))

    return r


# ──────────────────────────────────────────────
#  4. Background flag
# ──────────────────────────────────────────────

def evaluate_background_flag() -> EvalResult:
    r = EvalResult("Background Flag")

    # 4.1 Verification always runs in background
    r.record(AGENT_DEFINITIONS["verification"]["background"] is True,
             "verification background=True", "True", str(AGENT_DEFINITIONS["verification"]["background"]))

    # 4.2 Others default to foreground
    for atype in ["explore", "plan", "general"]:
        r.record(AGENT_DEFINITIONS[atype]["background"] is False,
                 f"{atype} background=False", "False", str(AGENT_DEFINITIONS[atype]["background"]))

    return r


# ──────────────────────────────────────────────
#  5. get_filtered_tools integration
# ──────────────────────────────────────────────

def evaluate_get_filtered_tools() -> EvalResult:
    r = EvalResult("get_filtered_tools Integration")

    try:
        defs, handlers = get_filtered_tools(READ_ONLY_TOOLS)

        # 5.1 Returns correct number of tool definitions
        r.record(len(defs) == len(READ_ONLY_TOOLS),
                 f"READ_ONLY returns {len(READ_ONLY_TOOLS)} defs",
                 str(len(READ_ONLY_TOOLS)), str(len(defs)))

        # 5.2 Handler names match definitions
        def_names = {d["name"] for d in defs}
        handler_names = set(handlers.keys())
        r.record(def_names == handler_names, "def names match handler names",
                 str(def_names), str(handler_names))

        # 5.3 No write tools in read-only set
        r.record("write_file" not in handler_names, "no write_file in read-only handlers",
                 "absent", "present" if "write_file" in handler_names else "absent")

    except Exception as e:
        r.record(False, f"get_filtered_tools crashed: {e}", "no crash", str(e))

    return r


# ──────────────────────────────────────────────
#  6. LLM integration test (requires real API key)
# ──────────────────────────────────────────────

def evaluate_llm_integration() -> EvalResult:
    r = EvalResult("LLM Integration [LLM]")

    if not _HAS_API_KEY:
        r.skip("run_subagent with simple task", "no API key — set LLM_PROVIDER + API key in .env")
        r.skip("subagent reads a file", "no API key")
        return r

    # Initialize LLM client
    try:
        from services.llm import LLMAdapter
        import bootstrap.state as state

        if state.llm is None:
            state.llm = LLMAdapter.from_env()

        from agents.subagent import run_subagent

        # 6.1 Simple task: ask agent to return a specific string
        result = run_subagent("Reply with exactly: EVAL_SUCCESS_42", agent_type="general")
        r.record("EVAL_SUCCESS_42" in result, "subagent returns expected string",
                 "EVAL_SUCCESS_42", result[:120])

        # 6.2 Explore agent with file reading
        with tempfile.TemporaryDirectory() as td:
            test_file = Path(td) / "eval_test.txt"
            test_file.write_text("The secret number is 7777.", encoding="utf-8")

            # Temporarily set WORKDIR（S2 后 safe_path 动态读取 state.WORKDIR，一处即可）
            old_workdir = state.WORKDIR
            state.WORKDIR = Path(td)
            try:
                result = run_subagent(
                    f"Read the file 'eval_test.txt' and tell me what the secret number is.",
                    agent_type="explore",
                )
                r.record("7777" in result, "explore agent reads file content",
                         "7777", result[:120])
            finally:
                state.WORKDIR = old_workdir

    except Exception as e:
        r.record(False, f"LLM integration error: {e}", "success", str(e)[:120])

    return r


# ──────────────────────────────────────────────
#  Report generation
# ──────────────────────────────────────────────

def run_full_evaluation():
    evaluators = [
        ("Definitions", evaluate_definitions),
        ("Tool Filtering", evaluate_tool_filtering),
        ("System Prompts", evaluate_system_prompts),
        ("Background Flag", evaluate_background_flag),
        ("get_filtered_tools", evaluate_get_filtered_tools),
        ("LLM Integration", evaluate_llm_integration),
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
    total_skipped = sum(r.skipped for r in results)

    print("=" * 70)
    print("  SubAgent Evaluation Report")
    print("=" * 70)
    print()

    for r in results:
        status = "PASS" if r.failed == 0 else "FAIL"
        if r.skipped > 0 and r.failed == 0:
            status = "SKIP"
        suffix = f" ({r.skipped} skipped)" if r.skipped > 0 else ""
        print(f"[{status}] {r.category}: {r.passed}/{r.total} ({r.accuracy:.1%}){suffix}")
        for detail in r.details:
            print(detail)

    print()
    print("-" * 70)
    effective = total_cases - total_skipped
    overall = total_passed / effective if effective > 0 else 0
    print(f"  Total: {total_passed}/{total_cases} ({overall:.1%})")
    print(f"  Passed: {total_passed}  Failed: {total_failed}  Skipped: {total_skipped}")
    print(f"  Test cases: {total_cases}")
    cost_note = "$0 (no LLM tests)" if total_skipped > 0 else "~$0.05-0.50"
    print(f"  API calls: {total_cases - total_skipped - total_failed}  |  Cost: {cost_note}")
    print("-" * 70)

    return total_failed == 0


# ──────────────────────────────────────────────
#  pytest compatible
# ──────────────────────────────────────────────

def test_definitions():
    r = evaluate_definitions()
    assert r.accuracy >= 0.90, f"Definitions accuracy {r.accuracy:.1%} < 90%"

def test_tool_filtering():
    r = evaluate_tool_filtering()
    assert r.accuracy >= 0.90, f"Tool filtering accuracy {r.accuracy:.1%} < 90%"

def test_system_prompts():
    r = evaluate_system_prompts()
    assert r.accuracy >= 0.90, f"System prompts accuracy {r.accuracy:.1%} < 90%"

def test_background_flag():
    r = evaluate_background_flag()
    assert r.accuracy == 1.0, f"Background flag accuracy {r.accuracy:.1%} < 100%"

def test_get_filtered_tools():
    r = evaluate_get_filtered_tools()
    assert r.accuracy >= 0.90, f"get_filtered_tools accuracy {r.accuracy:.1%} < 90%"

def test_llm_integration():
    """This test requires a real ANTHROPIC_API_KEY."""
    if not _HAS_API_KEY:
        import pytest
        pytest.skip("No API key available for LLM integration test")
    r = evaluate_llm_integration()
    assert r.accuracy >= 0.50, f"LLM integration accuracy {r.accuracy:.1%} < 50%"


if __name__ == "__main__":
    success = run_full_evaluation()
    sys.exit(0 if success else 1)
