"""等待闭环（批次 A）+ 可观测性增强（批次 B）测试。

A. 等待闭环：
  - LoopSpec.wait_for_pending + hooks.has_pending_work：end_turn 前有后台任务在飞
    → 注入 <background-tasks-pending> 继续循环，任务完成后正常结束
  - 无在飞任务 → 不影响正常结束
B. 可观测性：
  - agent 归属上下文（enter/exit）：子 agent 事件带 agent-N 标识
  - agent_spawn 事件含 agent_id/background/description
  - max_turns 截断告知
  - stream_options include_usage
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import runtime.state as st
from engine.loop import AgentLoop, LoopSpec, LoopHooks


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def chat(self, system, messages, tools=None, max_tokens=8000,
             stream=False, on_text=None):
        self.call_count += 1
        item = self._responses.pop(0) if self._responses else None
        if isinstance(item, Exception):
            raise item
        return item


def _text_resp(text="all done"):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
        is_truncated=False, truncated_text="", input_tokens=10, output_tokens=5,
    )


class _WaitingHooks(LoopHooks):
    """带 pending 状态的钩子：前 N 次 has_pending_work 返回 True。"""

    def __init__(self, pending_rounds: int):
        self.pending_rounds = pending_rounds

    def has_pending_work(self, messages) -> bool:
        return self.pending_rounds > 0

    def pre_turn(self, ctx, messages, tracker) -> bool:
        # 模拟通知到达：第二次进入时清空 pending 并注入通知
        if self.pending_rounds > 0 and ctx.turn_count >= 2:
            self.pending_rounds -= 1
            messages.append({"role": "user",
                             "content": "<task-notification>result</task-notification>"})
        return False


class TestWaitClosure:
    def test_end_turn_waits_for_pending(self):
        """end_turn 时有在飞任务 → 注入等待消息继续，通知到达后正常结束。"""
        llm = _FakeLLM([
            _text_resp("I'm waiting for the workers."),
            _text_resp("Final summary with results."),
        ])
        hooks = _WaitingHooks(pending_rounds=1)
        spec = LoopSpec(system_prompt="s", tool_defs=[], tool_handlers={},
                        max_turns=10, wait_for_pending=True)
        messages = [{"role": "user", "content": "go"}]
        result = AgentLoop(llm, spec, hooks).run(messages)

        assert result.stop_reason == "end_turn"
        assert result.final_text == "Final summary with results."
        # 等待提示与模拟通知都已注入
        assert any("background-tasks-pending" in str(m.get("content", ""))
                   for m in messages if m["role"] == "user")
        assert any("task-notification" in str(m.get("content", ""))
                   for m in messages if m["role"] == "user")

    def test_no_pending_ends_normally(self):
        """无在飞任务：正常结束（无额外轮次）。"""
        llm = _FakeLLM([_text_resp()])
        hooks = _WaitingHooks(pending_rounds=0)
        spec = LoopSpec(system_prompt="s", tool_defs=[], tool_handlers={},
                        max_turns=10, wait_for_pending=True)
        messages = [{"role": "user", "content": "go"}]
        result = AgentLoop(llm, spec, hooks).run(messages)

        assert result.final_text == "all done"
        assert llm.call_count == 1

    def test_wait_disabled_by_default(self):
        """wait_for_pending 默认关闭（子 agent 不等待）。"""
        llm = _FakeLLM([_text_resp()])
        hooks = _WaitingHooks(pending_rounds=99)  # 一直有 pending
        spec = LoopSpec(system_prompt="s", tool_defs=[], tool_handlers={},
                        max_turns=10)
        messages = [{"role": "user", "content": "go"}]
        result = AgentLoop(llm, spec, hooks).run(messages)

        # 子 agent 语义：不管 pending，直接结束
        assert result.stop_reason == "end_turn"
        assert llm.call_count == 1

    def test_main_hooks_pending_detection(self, monkeypatch, tmp_path):
        """_MainLoopHooks.has_pending_work 读 state.agent_tasks。"""
        from agents.session import _MainLoopHooks
        from context.compact import TokenTracker, CircuitBreaker
        from agents.task_queue import AgentTaskQueue

        queue = AgentTaskQueue()
        monkeypatch.setattr(st, "agent_tasks", queue)
        hooks = _MainLoopHooks(TokenTracker(), CircuitBreaker(), {})

        assert hooks.has_pending_work([]) is False
        queue.increment()
        assert hooks.has_pending_work([]) is True
        queue.submit("t1", "general", "completed", "done")
        assert hooks.has_pending_work([]) is False


class TestAgentTracingContext:
    def test_events_carry_agent_field(self, tmp_path):
        """主 agent 事件 agent=main；子 agent 上下文中 agent=agent-N。"""
        from services.tracing import Tracer

        tracer = Tracer(path=tmp_path / "t.jsonl")
        tracer.event("tool_call", tool="read_file")
        assert tracer._events[-1]["agent"] == "main"

        agent_id = tracer.enter_agent()
        assert agent_id == "agent-1"
        tracer.event("tool_call", tool="grep_search")
        assert tracer._events[-1]["agent"] == "agent-1"

        tracer.exit_agent()
        tracer.event("tool_call", tool="run_shell")
        assert tracer._events[-1]["agent"] == "main"

        # 落盘的事件同样带字段
        lines = (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()
        tool_events = [json.loads(l) for l in lines if '"tool_call"' in l]
        assert tool_events[0]["agent"] == "main"
        assert tool_events[1]["agent"] == "agent-1"

    def test_spawn_event_enriched(self, tmp_path, monkeypatch):
        """agent_spawn 含 agent_id / background / description。"""
        from services.tracing import Tracer
        import agents.subagent as subagent_mod

        tracer = Tracer(path=tmp_path / "t.jsonl")
        monkeypatch.setattr("services.tracing._default_tracer", tracer)
        monkeypatch.setattr(st, "llm", _FakeLLM([_text_resp("done")]))
        monkeypatch.setattr(
            "agents.subagent.get_filtered_tools", lambda a: ([], {}))

        subagent_mod.run_subagent(
            "task", agent_type="explore", description="scan codebase")
        spawns = [e for e in tracer._events if e["event"] == "agent_spawn"]
        assert len(spawns) == 1
        assert spawns[0]["agent_id"] == "agent-1"
        assert spawns[0]["background"] is False
        assert "scan codebase" in spawns[0]["description"]
        # 子 agent 完成后回到 main 上下文
        assert tracer._agent_ctx == "main"

    def test_max_turns_incomplete_warning(self, monkeypatch):
        """max_turns 截断：返回文本带 INCOMPLETE 告知。"""
        from agents.subagent import _run_agent_loop

        tool_resp = SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", id="t1",
                                     name="read_file", input={})],
            is_truncated=False, truncated_text="",
        )
        llm = _FakeLLM([tool_resp] * 10)
        monkeypatch.setattr(st, "llm", llm)

        out = _run_agent_loop(
            "sys", [{"role": "user", "content": "go"}], [],
            {"read_file": lambda **kw: "x"}, max_turns=3, agent_type="general")
        assert "INCOMPLETE" in out
        assert "max_turns=3" in out


class TestStreamUsage:
    def test_stream_options_requested(self):
        """OpenAI 流式调用请求 include_usage（tokens 统计来源）。"""
        import inspect
        from llm.adapter import LLMAdapter

        src = inspect.getsource(LLMAdapter._stream_openai)
        assert "include_usage" in src
        assert "stream_options" in src
