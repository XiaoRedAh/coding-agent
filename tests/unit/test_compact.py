"""单元测试：services/compact.py (TokenTracker, CircuitBreaker, Budget, Snip)"""
import pytest
from unittest.mock import MagicMock
from context.compact import (
    TokenTracker, CircuitBreaker, budget_tool_results, snip_stale_results,
)


class TestTokenTracker:
    def test_initial_state(self):
        t = TokenTracker()
        assert t.last_input_tokens == 0
        assert t.estimate_current_tokens() == 0

    def _make_response(self, input_tokens=5000, output_tokens=1000):
        """Create a mock LLMResponse (has direct input_tokens/output_tokens attrs)."""
        from dataclasses import dataclass
        @dataclass
        class FakeResp:
            input_tokens: int
            output_tokens: int
            content: list = None
            stop_reason: str = "end_turn"
        return FakeResp(input_tokens=input_tokens, output_tokens=output_tokens)

    def test_update_from_response(self):
        t = TokenTracker()
        resp = self._make_response(5000, 1000)
        t.update_from_response(resp)
        assert t.last_input_tokens == 5000
        assert t.total_input_tokens == 5000
        assert t.total_output_tokens == 1000

    def test_track_new_message(self):
        t = TokenTracker()
        t.update_from_response(self._make_response(3000, 500))
        t.track_new_message({"role": "user", "content": "x" * 300})
        est = t.estimate_current_tokens()
        assert est > 3000

    def test_get_utilization(self, monkeypatch):
        # EFFECTIVE_WINDOW 受 .env 的 MODEL_CONTEXT_WINDOW 影响，
        # 显式固定窗口值保证测试与运行环境无关
        monkeypatch.setattr("context.compact.EFFECTIVE_WINDOW", 180000)
        t = TokenTracker()
        t.update_from_response(self._make_response(90000, 0))
        util = t.get_utilization()
        assert 0.4 < util < 0.6

    def test_reset_after_compact(self):
        t = TokenTracker()
        t.update_from_response(self._make_response(50000, 1000))
        t.reset_after_compact()
        assert t.last_input_tokens == 0
        assert t.estimate_current_tokens() == 0


class TestCircuitBreaker:
    def test_initial_closed(self):
        cb = CircuitBreaker()
        assert cb.state == "CLOSED"
        assert not cb.should_skip()

    def test_failures_open(self):
        cb = CircuitBreaker()
        cb.record_failure()
        assert cb.state == "HALF_OPEN"
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "OPEN"
        assert cb.should_skip()

    def test_success_resets(self):
        cb = CircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.state == "CLOSED"
        assert not cb.should_skip()

    def test_open_stays_open(self):
        cb = CircuitBreaker()
        for _ in range(5):
            cb.record_failure()
        assert cb.should_skip()
        assert cb.consecutive_failures == 5


class TestBudgetToolResults:
    def _make_messages(self, content_len):
        return [{"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "x" * content_len}
        ]}]

    def test_below_threshold_no_change(self):
        msgs = self._make_messages(50000)
        budget_tool_results(msgs, 0.40)
        assert len(msgs[0]["content"][0]["content"]) == 50000

    def test_normal_budget(self):
        msgs = self._make_messages(50000)
        budget_tool_results(msgs, 0.60)
        assert len(msgs[0]["content"][0]["content"]) < 50000
        assert "budgeted" in msgs[0]["content"][0]["content"]

    def test_tight_budget(self):
        msgs = self._make_messages(50000)
        budget_tool_results(msgs, 0.75)
        content = msgs[0]["content"][0]["content"]
        assert len(content) < 20000


class TestSnipStaleResults:
    def _make_messages(self, n_results):
        msgs = []
        for i in range(n_results):
            # Use dicts for assistant content (matching how _find_tool_use checks isinstance(block, dict))
            msgs.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "read_file", "input": {"file_path": f"f{i}.py"}}
            ]})
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}", "content": f"content of file {i}" * 20}
            ]})
        return msgs

    def test_keeps_recent_3(self):
        msgs = self._make_messages(6)
        snip_stale_results(msgs, 0.65)
        snipped = sum(1 for m in msgs if m["role"] == "user"
                      and isinstance(m.get("content"), list)
                      and any(b.get("content", "").startswith("[Content snipped")
                              for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_result"))
        assert snipped >= 1  # at least some were snipped

    def test_below_threshold_no_snip(self):
        msgs = self._make_messages(6)
        original = [m.get("content", [{}])[0].get("content", "") for m in msgs if m["role"] == "user"]
        snip_stale_results(msgs, 0.50)
        after = [m.get("content", [{}])[0].get("content", "") for m in msgs if m["role"] == "user"]
        assert original == after
