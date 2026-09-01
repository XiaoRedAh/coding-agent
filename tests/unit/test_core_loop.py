"""Unit tests for core/loop.py — 统一 Agent Loop 的骨架与钩子契约。

独立于 query.py / subagent.py 的组装层，直接验证：
- 循环骨架（工具执行 / 结果注入 / 退出条件）
- LoopSpec 保护参数（max_turns / 连续错误）
- 钩子契约（pre_turn 跳过 / execute_tool 异常吞噬 / 截断续写 / 超时护栏）
- is_error_output / extract_text 工具函数
"""

from types import SimpleNamespace

import pytest

from core.loop import (
    AgentLoop, LoopSpec, LoopHooks, LoopResult,
    is_error_output, extract_text,
)
from services.api_errors import APIErrorType, LLMError


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def chat(self, system_prompt, messages, tool_defs, **kwargs):
        self.call_count += 1
        item = self._responses.pop(0) if self._responses else None
        if isinstance(item, Exception):
            raise item
        return item


def _text_resp(text="done"):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def _tool_resp(name="read_file", input=None, id="t1"):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=id, name=name,
                                 input=input if input is not None else {})],
    )


def _spec(**kwargs):
    defaults = dict(
        system_prompt="sys", tool_defs=[], tool_handlers={},
        max_turns=5, llm_timeout=None,
    )
    defaults.update(kwargs)
    return LoopSpec(**defaults)


class _ExecutingHooks(LoopHooks):
    """执行 spec.tool_handlers 的最小钩子实现。"""

    def __init__(self, tool_handlers):
        self.tool_handlers = tool_handlers

    def execute_tool(self, ctx, block):
        handler = self.tool_handlers.get(block.name)
        if not handler:
            return f"Unknown tool: {block.name}"
        try:
            return str(handler(**block.input))
        except Exception as e:
            return f"Error: {e}"


class TestLoopSkeleton:
    def test_end_turn_returns_text(self):
        llm = _FakeLLM([_text_resp("final")])
        result = AgentLoop(llm, _spec()).run([])
        assert result.stop_reason == "end_turn"
        assert result.final_text == "final"

    def test_tool_then_end(self):
        llm = _FakeLLM([_tool_resp(), _text_resp("ok")])
        messages = [{"role": "user", "content": "go"}]
        handlers = {"read_file": lambda **kw: "data"}
        hooks = _ExecutingHooks(handlers)
        result = AgentLoop(llm, _spec(tool_handlers=handlers), hooks).run(messages)
        assert result.stop_reason == "end_turn"
        # messages: user + assistant + tool_result + assistant
        tool_msg = messages[2]
        assert tool_msg["content"][0]["type"] == "tool_result"
        assert tool_msg["content"][0]["content"] == "data"

    def test_max_turns_stop(self):
        llm = _FakeLLM([_tool_resp() for _ in range(10)])
        handlers = {"read_file": lambda **kw: "x"}
        result = AgentLoop(llm, _spec(max_turns=3, tool_handlers=handlers)).run([])
        assert result.stop_reason == "max_turns"
        assert llm.call_count == 3

    def test_llm_error_injected_and_recovers(self):
        llm = _FakeLLM([
            LLMError("rate", APIErrorType.RATE_LIMIT),
            _text_resp("recovered"),
        ])
        messages = []
        result = AgentLoop(llm, _spec()).run(messages)
        assert result.stop_reason == "end_turn"
        assert any("<error>" in m["content"] for m in messages)

    def test_consecutive_llm_errors_stop(self):
        llm = _FakeLLM([LLMError("e", APIErrorType.AUTH_ERROR)] * 3)
        result = AgentLoop(llm, _spec()).run([])
        assert result.stop_reason == "llm_errors"
        assert result.error_count == 3

    def test_tool_errors_stop(self):
        resp = SimpleNamespace(stop_reason="tool_use", content=[
            SimpleNamespace(type="tool_use", id=f"t{i}", name="read_file", input={})
            for i in range(5)
        ])
        llm = _FakeLLM([resp])
        handlers = {"read_file": lambda **kw: (_ for _ in ()).throw(RuntimeError("boom"))}
        result = AgentLoop(llm, _spec(tool_handlers=handlers)).run([])
        assert result.stop_reason == "tool_errors"
        assert result.error_count == 5

    def test_truncation_continuation_injected(self):
        resp = SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="partial")],
            is_truncated=True,
            truncated_text="partial",
        )
        llm = _FakeLLM([resp, _text_resp("continued")])
        messages = []
        result = AgentLoop(llm, _spec()).run(messages)
        assert result.stop_reason == "end_turn"
        assert any("<output_truncated>" in m["content"] for m in messages)
        assert llm.call_count == 2

    def test_truncation_after_tools(self):
        resp = SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", id="t1", name="read_file", input={})],
            is_truncated=True,
            truncated_text="partial",
        )
        llm = _FakeLLM([resp, _text_resp("done")])
        handlers = {"read_file": lambda **kw: "x"}
        messages = []
        AgentLoop(llm, _spec(tool_handlers=handlers), _ExecutingHooks(handlers)).run(messages)
        # tool_result 消息之后应紧跟续写提示
        contents = [m["content"] for m in messages]
        assert any(
            isinstance(c, list) and isinstance(c[0], dict) and c[0].get("type") == "tool_result"
            for c in contents)
        assert any("<output_truncated>" in c and isinstance(c, str) for c in contents)


class TestHookContract:
    def test_pre_turn_skip_llm(self):
        class SkipHooks(LoopHooks):
            def __init__(self):
                self.calls = 0

            def pre_turn(self, ctx, messages, tracker):
                self.calls += 1
                return self.calls == 1  # 第一轮跳过

        llm = _FakeLLM([_text_resp("ok")])
        hooks = SkipHooks()
        AgentLoop(llm, _spec(), hooks).run([])
        assert hooks.calls == 2
        assert llm.call_count == 1  # 第一轮被跳过，只调用了 1 次

    def test_execute_tool_exception_swallowed(self):
        class ExplodingHooks(LoopHooks):
            def execute_tool(self, ctx, block):
                raise RuntimeError("hook bug")

        llm = _FakeLLM([_tool_resp()])
        with pytest.raises(RuntimeError, match="hook bug"):
            AgentLoop(llm, _spec(), ExplodingHooks()).run([])

    def test_execute_tool_error_string_counted(self):
        class ErrorHooks(LoopHooks):
            def execute_tool(self, ctx, block):
                return "Error: something failed"

        llm = _FakeLLM([_tool_resp()])
        result = AgentLoop(llm, _spec(max_consecutive_tool_errors=1), ErrorHooks()).run([])
        assert result.stop_reason == "tool_errors"
        assert result.error_count == 1

    def test_on_response_called_with_resp(self):
        seen = []

        class Tracking(LoopHooks):
            def on_response(self, ctx, response):
                seen.append(response)

        resp = _text_resp("x")
        AgentLoop(_FakeLLM([resp]), _spec(), Tracking()).run([])
        assert seen == [resp]

    def test_on_stop_reason_reported(self):
        stops = []

        class Tracking(LoopHooks):
            def on_stop(self, stop_reason, error_count):
                stops.append((stop_reason, error_count))

        AgentLoop(_FakeLLM([_text_resp()]), _spec(), Tracking()).run([])
        assert stops == [("end_turn", 0)]

    def test_stream_flag_passes_on_text(self):
        texts = []

        class StreamHooks(LoopHooks):
            def on_text(self, delta):
                texts.append(delta)

        llm = _FakeLLM([_text_resp("abc")])
        AgentLoop(llm, _spec(stream=True), StreamHooks()).run([])
        # FakeLLM 不真正流式，但 on_text 契约存在且不报错


class TestTimeoutGuard:
    def test_timeout_triggers_llm_errors_stop(self):
        """LLM 调用超时 → LLMError(TIMEOUT) → 计入连续错误 → 达阈值停止。"""
        import time

        def slow_chat(*args, **kwargs):
            time.sleep(0.05)
            return _text_resp("late")

        llm = SimpleNamespace(chat=slow_chat)
        spec = _spec(llm_timeout=0.01, max_consecutive_llm_errors=1)
        result = AgentLoop(llm, spec).run([])
        assert result.stop_reason == "llm_errors"
        assert result.error_count == 1

    def test_timeout_error_injected_as_message(self):
        """超时错误应注入 <error> 消息（含 timeout 字样）。"""
        import time

        calls = []

        def slow_then_fast(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                time.sleep(0.05)
            return _text_resp("ok")

        llm = SimpleNamespace(chat=slow_then_fast)
        messages = []
        spec = _spec(llm_timeout=0.01)
        result = AgentLoop(llm, spec).run(messages)
        assert result.stop_reason == "end_turn"
        assert any("<error>" in m["content"] and "timed out" in m["content"]
                   for m in messages)


class TestHelpers:
    def test_is_error_output_variants(self):
        assert is_error_output("Error: x")
        assert is_error_output("<tool_use_error>bad")
        assert is_error_output("<error>e")
        assert is_error_output("Unknown tool: foo")
        assert is_error_output('{"_json_parse_error": "x"}')
        assert not is_error_output("normal output")
        assert not is_error_output("Errorless")  # 前缀严格匹配

    def test_extract_text(self):
        resp = SimpleNamespace(content=[
            SimpleNamespace(type="text", text="a"),
            SimpleNamespace(type="tool_use", text=None),
            SimpleNamespace(type="text", text="b"),
        ])
        assert extract_text(resp) == "ab"

    def test_extract_text_defensive(self):
        """MagicMock 等对象的自动属性不应进入结果。"""
        from unittest.mock import MagicMock
        resp = MagicMock(content=[MagicMock(type="tool_use")])
        assert extract_text(resp) == ""

    def test_extract_text_none_content(self):
        resp = SimpleNamespace(content=None)
        assert extract_text(resp) == ""


class TestLoopResultPassthrough:
    def test_tracker_breaker_passthrough(self):
        tracker = object()
        breaker = object()
        result = AgentLoop(_FakeLLM([_text_resp()]), _spec()).run(
            [], tracker=tracker, breaker=breaker)
        assert result.tracker is tracker
        assert result.breaker is breaker
