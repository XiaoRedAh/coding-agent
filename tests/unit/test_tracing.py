"""可观测性（Tracer）+ 编排收敛（Coordinator 配置化）测试。

覆盖：
  A. Tracer 基础：JSONL 写入、事件字段、聚合报告、禁用态 no-op
  B. Tracer 接线：主循环钩子产生的事件（llm_response / tool_call / memory_write）
  C. LoopResult.turns_used 字段
  D. Coordinator 配置化：提示词经三级覆盖加载、白名单来自 config、激活优先级
"""

import json
from types import SimpleNamespace

import pytest

import runtime.state as st
from services.tracing import Tracer, get_tracer, reset_tracer


@pytest.fixture
def tracer(tmp_path):
    """隔离的 Tracer（显式路径，不碰 TRANSCRIPT_DIR）。"""
    return Tracer(path=tmp_path / "trace.jsonl")


# ──────────────────────────────────────────────
#  A. Tracer 基础
# ──────────────────────────────────────────────

class TestTracerBasics:
    def test_events_written_as_jsonl(self, tracer, tmp_path):
        tracer.event("llm_response", turn=1, tokens_in=100, tokens_out=50,
                     latency_ms=1200.0)
        tracer.event("tool_call", turn=1, tool="read_file", ok=True,
                     latency_ms=15.2, result_chars=800)

        lines = (tmp_path / "trace.jsonl").read_text(encoding="utf-8").strip().splitlines()
        events = [json.loads(l) for l in lines]
        # 首行 _meta + session_start + 2 个事件
        assert events[0]["event"] == "_meta"
        names = [e["event"] for e in events]
        assert "session_start" in names
        assert "llm_response" in names and "tool_call" in names

        llm = next(e for e in events if e["event"] == "llm_response")
        assert llm["tokens_in"] == 100 and llm["tokens_out"] == 50
        assert "ts" in llm

    def test_summary_aggregates(self, tracer):
        tracer.event("llm_response", turn=1, tokens_in=1000, tokens_out=200, latency_ms=100)
        tracer.event("llm_response", turn=2, tokens_in=2000, tokens_out=300, latency_ms=150)
        tracer.event("tool_call", turn=1, tool="read_file", ok=True, latency_ms=10)
        tracer.event("tool_call", turn=1, tool="read_file", ok=False, latency_ms=20)
        tracer.event("tool_call", turn=2, tool="grep_search", ok=True, latency_ms=5)
        tracer.event("memory_write", turn=2, tool="write_file", path="x.md")
        tracer.event("compact", turn=3, utilization=0.85)
        tracer.event("agent_done", agent_type="explore", turns=5,
                     latency_ms=8000, stop_reason="end_turn")

        s = tracer.summary()
        assert s["llm_calls"] == 2
        assert s["tokens_in"] == 3000 and s["tokens_out"] == 500
        assert s["tool_calls"] == 3
        assert s["tools"]["read_file"]["count"] == 2
        assert s["tools"]["read_file"]["errors"] == 1
        assert s["tools"]["read_file"]["total_ms"] == 30.0
        assert s["memory_writes"] == 1
        assert s["compacts"] == 1
        assert s["agents"][0]["agent_type"] == "explore"

    def test_format_summary_readable(self, tracer):
        tracer.event("llm_response", turn=1, tokens_in=1000, tokens_out=200, latency_ms=100)
        text = tracer.format_summary()
        assert "Session stats" in text
        assert "1,000 in / 200 out" in text
        assert "Memory writes: 0" in text

    def test_disabled_tracer_is_noop(self, tmp_path):
        t = Tracer(enabled=False)
        t.event("llm_response", tokens_in=1)
        assert t.summary()["llm_calls"] == 0
        assert t.path is None

    def test_nonserializable_fields_do_not_crash(self, tracer):
        tracer.event("weird", obj=object())  # default=str 兜底
        assert tracer.summary()["events_total"] >= 1

    def test_default_tracer_singleton(self, tmp_path, monkeypatch):
        monkeypatch.setattr(st, "TRANSCRIPT_DIR", tmp_path / "transcripts")
        t1 = reset_tracer(path=tmp_path / "transcripts" / "s1.jsonl")
        assert get_tracer() is t1
        t2 = reset_tracer(path=tmp_path / "transcripts" / "s2.jsonl")
        assert get_tracer() is t2 and t1 is not t2


# ──────────────────────────────────────────────
#  B. 主循环钩子接线（不启动真实 LLM）
# ──────────────────────────────────────────────

class TestMainLoopWiring:
    @pytest.fixture
    def patched_tracer(self, tracer, monkeypatch):
        """把模块级默认 tracer 替换为隔离实例。"""
        monkeypatch.setattr("services.tracing._default_tracer", tracer)
        return tracer

    def _make_hooks(self):
        from context.compact import TokenTracker, CircuitBreaker
        from agents.session import _MainLoopHooks
        return _MainLoopHooks(TokenTracker(), CircuitBreaker(),
                              {"read_file": lambda **k: "ok"})

    def test_on_response_emits_llm_event(self, patched_tracer):
        hooks = self._make_hooks()
        ctx = SimpleNamespace(turn_count=1, max_turns=50)
        resp = SimpleNamespace(
            input_tokens=5000, output_tokens=300,
            stop_reason="end_turn", is_truncated=False)
        hooks.on_response(ctx, resp)

        llm_events = [e for e in patched_tracer._events if e["event"] == "llm_response"]
        assert len(llm_events) == 1
        assert llm_events[0]["tokens_in"] == 5000
        assert llm_events[0]["tokens_out"] == 300

    def test_execute_tool_emits_tool_event_and_memory_write(self, patched_tracer,
                                                            monkeypatch, tmp_workdir):
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        from services.memory import MemoryManager
        monkeypatch.setattr(st, "memory", MemoryManager(memory_dir=mem_dir))

        hooks = self._make_hooks()
        ctx = SimpleNamespace(turn_count=1, max_turns=50)
        block = SimpleNamespace(
            name="write_file",
            input={"file_path": str(mem_dir / "user_role.md"), "content": "x"},
        )
        monkeypatch.setattr(
            "agents.session.check_permission",
            lambda *a, **k: {"action": "allow"})
        from engine.results import ToolResult
        monkeypatch.setattr(
            hooks, "_run_handler", lambda b: ToolResult("Successfully wrote"))
        hooks.execute_tool(ctx, block)

        tool_events = [e for e in patched_tracer._events if e["event"] == "tool_call"]
        mem_events = [e for e in patched_tracer._events if e["event"] == "memory_write"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "write_file" and tool_events[0]["ok"] is True
        assert len(mem_events) == 1, "记忆写入未被检测到（memory_write 事件缺失）"

    def test_non_memory_write_no_memory_event(self, patched_tracer,
                                              monkeypatch, tmp_workdir):
        from services.memory import MemoryManager
        monkeypatch.setattr(
            st, "memory",
            MemoryManager(memory_dir=tmp_workdir / ".xiaoagent" / "memory"))

        hooks = self._make_hooks()
        ctx = SimpleNamespace(turn_count=1, max_turns=50)
        block = SimpleNamespace(
            name="write_file",
            input={"file_path": str(tmp_workdir / "normal.py"), "content": "x"},
        )
        monkeypatch.setattr(
            "agents.session.check_permission",
            lambda *a, **k: {"action": "allow"})
        from engine.results import ToolResult
        monkeypatch.setattr(
            hooks, "_run_handler", lambda b: ToolResult("Successfully wrote"))
        hooks.execute_tool(ctx, block)

        mem_events = [e for e in patched_tracer._events if e["event"] == "memory_write"]
        assert len(mem_events) == 0

    def test_subagent_tool_hook_emits_event(self, tracer, monkeypatch):
        monkeypatch.setattr("services.tracing._default_tracer", tracer)
        from agents.subagent import _SubAgentHooks
        hooks = _SubAgentHooks({"read_file": lambda **k: "content"})
        ctx = SimpleNamespace(turn_count=1, max_turns=10)
        block = SimpleNamespace(name="read_file", input={"file_path": "x.py"})
        out = hooks.execute_tool(ctx, block)
        assert "content" in str(out)

        tool_events = [e for e in tracer._events if e["event"] == "tool_call"]
        assert len(tool_events) == 1
        assert tool_events[0]["tool"] == "read_file"


# ──────────────────────────────────────────────
#  C. LoopResult.turns_used
# ──────────────────────────────────────────────

class TestTurnsUsed:
    def test_loop_result_has_turns_used(self):
        from engine.loop import LoopResult
        r = LoopResult(stop_reason="end_turn", turns_used=3)
        assert r.turns_used == 3
        assert LoopResult(stop_reason="end_turn").turns_used == 0


# ──────────────────────────────────────────────
#  D. 通知等待（统一语义）
# ──────────────────────────────────────────────

class TestAgentWaitNotifications:
    """通知等待语义的薄验证。"""

    def test_wait_and_drain_used_by_process_agent_notifications(self, monkeypatch):
        from engine import notifications
        import runtime.state as st

        class _FakeTasks:
            def __init__(self):
                self._in_flight = 2
                self._notifs = [{"task_id": "a", "agent_type": "general", "status": "completed", "result": "r"}]
                self._waited = False

            def drain(self):
                if self._waited:
                    return self._notifs, 0
                return [], self._in_flight

            def wait_and_drain(self, timeout):
                self._waited = True
                return self._notifs, 0

        fake_state = SimpleNamespace(agent_tasks=_FakeTasks())
        content, skip = notifications.process_agent_notifications(
            fake_state, wait_for_inflight=True, wait_timeout=0.1)
        assert skip is False
        assert content is not None and "<task-notification>" in content
