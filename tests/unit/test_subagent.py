"""Unit tests for agents/subagent.py — _run_agent_loop / run_subagent / AgentTool.

覆盖：正常路径（文本/工具多轮）、异常路径（LLM 错误/工具错误/JSON 解析错误）、
边界（max_turns 耗尽/重试耗尽/空输出/超时护栏）。
"""

import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.subagent import _run_agent_loop, run_subagent
from runtime import state
from engine.errors import APIErrorType, LLMError


class _FakeLLM:
    """按脚本顺序返回响应；Exception 会被抛出；callable 被调用以生成响应。"""

    def __init__(self, responses):
        self._responses = list(responses)
        self.call_count = 0

    def chat(self, system_prompt, messages, tool_defs):
        self.call_count += 1
        item = self._responses.pop(0) if self._responses else None
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(system_prompt, messages, tool_defs)
        return item


def _text_resp(text="task done"):
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def _tool_use_resp(tool_name="read_file", tool_input=None, tool_id="t1", text="phase1"):
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="text", text=text),
            SimpleNamespace(type="tool_use", id=tool_id, name=tool_name,
                            input=tool_input if tool_input is not None else {}),
        ],
    )


def _run(llm, max_turns=5, handlers=None, agent_type="general", callback=None):
    return _run_agent_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do task"}],
        tool_defs=[],
        tool_handlers=handlers or {},
        max_turns=max_turns,
        agent_type=agent_type,
        status_callback=callback,
    )


# ──────────────────────────────────────────────
#  正常路径
# ──────────────────────────────────────────────

class TestHappyPath:
    def test_text_response_returns_directly(self, monkeypatch):
        """纯文本响应（无工具调用）应直接返回文本。"""
        llm = _FakeLLM([_text_resp("hello world")])
        monkeypatch.setattr(state, "llm", llm)
        assert _run(llm) == "hello world"

    def test_multi_block_text_concatenated(self, monkeypatch):
        """多个 text block 应拼接返回。"""
        resp = SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="text", text="part1-"),
                SimpleNamespace(type="text", text="part2"),
            ],
        )
        llm = _FakeLLM([resp])
        monkeypatch.setattr(state, "llm", llm)
        assert _run(llm) == "part1-part2"

    def test_tool_call_then_finalize(self, monkeypatch):
        """工具调用 → 结果注入 → 最终文本，完整两轮流程。"""
        llm = _FakeLLM([_tool_use_resp(), _text_resp("final answer")])
        monkeypatch.setattr(state, "llm", llm)
        handlers = {"read_file": lambda **kw: "file content"}
        out = _run(llm, handlers=handlers)
        assert out == "final answer"
        assert llm.call_count == 2

    def test_tool_result_appended_to_messages(self, monkeypatch):
        """工具结果应作为 user 消息追加，供下一轮 LLM 使用。"""
        messages = [{"role": "user", "content": "do task"}]

        def _capture(_sys, msgs, _tools):
            if len(msgs) == 1:  # 第一轮：只有初始消息
                return _tool_use_resp()
            return _text_resp("ok")

        llm = _FakeLLM([_capture, _capture])  # 两轮各消费一次
        monkeypatch.setattr(state, "llm", llm)
        _run_agent_loop("sys", messages, [], {"read_file": lambda **kw: "data"}, 5)
        # messages 应包含：初始 user + assistant(tool_use) + user(tool_result) + assistant(text)
        assert len(messages) == 4
        tool_result_msg = messages[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["content"] == "data"

    def test_status_callback_invoked(self, monkeypatch):
        """状态回调应报告每轮 LLM 等待、工具执行和 done。"""
        llm = _FakeLLM([_tool_use_resp(), _text_resp()])
        monkeypatch.setattr(state, "llm", llm)
        calls = []
        _run(llm, handlers={"read_file": lambda **kw: "x"}, callback=calls.append)
        assert "turn 1/5: waiting llm" in calls
        assert any(c.startswith("turn 1/5: tool read_file") for c in calls)
        assert "done" in calls

    def test_multiple_tools_same_turn(self, monkeypatch):
        """同一轮内多个工具调用都应执行并注入结果。"""
        resp = SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(type="tool_use", id="t1", name="read_file", input={"file_path": "a"}),
                SimpleNamespace(type="tool_use", id="t2", name="read_file", input={"file_path": "b"}),
            ],
        )
        messages = [{"role": "user", "content": "read"}]
        llm = _FakeLLM([resp, _text_resp("summary")])
        monkeypatch.setattr(state, "llm", llm)
        seen = []

        def handler(**kw):
            seen.append(kw["file_path"])
            return "content"

        _run_agent_loop("sys", messages, [], {"read_file": handler}, 5)
        assert seen == ["a", "b"]
        results = messages[2]["content"]
        assert len(results) == 2
        assert results[0]["tool_use_id"] == "t1"
        assert results[1]["tool_use_id"] == "t2"


# ──────────────────────────────────────────────
#  异常路径
# ──────────────────────────────────────────────

class TestErrorPaths:
    def test_tool_exception_returns_error_result(self, monkeypatch):
        """工具 handler 抛异常应转为 Error 结果，不崩溃。"""

        def bad_handler(**kw):
            raise FileNotFoundError("missing")

        messages = [{"role": "user", "content": "x"}]
        llm = _FakeLLM([_tool_use_resp(), _text_resp("recovered")])
        monkeypatch.setattr(state, "llm", llm)
        out = _run_agent_loop("sys", messages, [], {"read_file": bad_handler}, 5)
        assert out == "recovered"
        assert "Error: missing" in messages[2]["content"][0]["content"]

    def test_unknown_tool_returns_error(self, monkeypatch):
        """未注册的工具应返回 Unknown tool 错误结果。"""
        messages = [{"role": "user", "content": "x"}]
        llm = _FakeLLM([_tool_use_resp("nonexistent"), _text_resp("done")])
        monkeypatch.setattr(state, "llm", llm)
        _run_agent_loop("sys", messages, [], {}, 5)
        assert "Unknown tool: nonexistent" in messages[2]["content"][0]["content"]

    def test_json_parse_error_handled(self, monkeypatch):
        """LLM 层注入的 _json_parse_error 应被识别为工具失败。"""
        messages = [{"role": "user", "content": "x"}]
        resp = _tool_use_resp("read_file", {"_json_parse_error": "truncated", "_raw_args": "{"})
        llm = _FakeLLM([resp, _text_resp("done")])
        monkeypatch.setattr(state, "llm", llm)
        _run_agent_loop("sys", messages, [], {"read_file": lambda **kw: "ok"}, 5)
        assert "JSON parse failed" in messages[2]["content"][0]["content"]

    def test_consecutive_tool_errors_stop(self, monkeypatch):
        """同一轮内工具错误达到阈值应提前停止。"""
        blocks = [
            SimpleNamespace(type="tool_use", id=f"t{i}", name="read_file", input={})
            for i in range(5)
        ]
        resp = SimpleNamespace(stop_reason="tool_use", content=blocks)
        llm = _FakeLLM([resp])
        monkeypatch.setattr(state, "llm", llm)

        def bad(**kw):
            raise RuntimeError("boom")

        out = _run(llm, handlers={"read_file": bad}, max_turns=10)
        assert "SubAgent stopped" in out
        assert "tool errors" in out

    def test_non_retryable_error_injected_then_recover(self, monkeypatch):
        """不可重试错误应注入 <error> 消息，下一轮可恢复。"""
        llm = _FakeLLM([
            LLMError("auth failed", APIErrorType.AUTH_ERROR),
            _text_resp("recovered"),
        ])
        monkeypatch.setattr(state, "llm", llm)
        out = _run(llm, max_turns=3)
        assert out == "recovered"

    def test_retryable_error_retries_then_succeeds(self, monkeypatch):
        """可重试错误（限流）应在重试后成功。"""
        monkeypatch.setattr("agents.subagent.time.sleep", lambda s: None)  # 跳过退避等待
        llm = _FakeLLM([
            LLMError("rate limited", APIErrorType.RATE_LIMIT),
            _text_resp("after retry"),
        ])
        monkeypatch.setattr(state, "llm", llm)
        out = _run(llm, max_turns=3)
        assert out == "after retry"

    def test_max_consecutive_llm_errors_stop(self, monkeypatch):
        """连续 LLM 错误达到阈值应返回停止消息。"""
        monkeypatch.setattr("agents.subagent.time.sleep", lambda s: None)
        llm = _FakeLLM([
            LLMError("auth", APIErrorType.AUTH_ERROR),
            LLMError("auth", APIErrorType.AUTH_ERROR),
            LLMError("auth", APIErrorType.AUTH_ERROR),
        ])
        monkeypatch.setattr(state, "llm", llm)
        out = _run(llm, max_turns=10)
        assert "SubAgent stopped after 3 consecutive LLM errors" in out


# ──────────────────────────────────────────────
#  边界场景
# ──────────────────────────────────────────────

class TestBoundaries:
    def test_max_turns_exhausted(self, monkeypatch):
        """持续工具调用直到 max_turns 用尽：返回截断告知 + 最后一轮文本。"""
        # 每轮都返回新的 tool_use 响应（不可复用同一对象）
        llm = _FakeLLM([_tool_use_resp() for _ in range(10)])
        monkeypatch.setattr(state, "llm", llm)
        handlers = {"read_file": lambda **kw: "x"}
        out = _run(llm, max_turns=3, handlers=handlers)
        # 截断告知：主 agent 需知道结果是残次的
        assert "stopped at max_turns" in out
        assert "INCOMPLETE" in out
        assert "phase1" in out  # 最后一轮 resp 的文本仍附带
        assert llm.call_count == 3

    def test_empty_content_returns_no_output(self, monkeypatch):
        """content 无任何文本：注入 <error> 续跑一次，仍空则返回占位符。"""
        empty = SimpleNamespace(stop_reason="end_turn", content=[])
        llm = _FakeLLM([empty, empty])  # 重试一次后仍空 → 放弃
        monkeypatch.setattr(state, "llm", llm)
        assert _run(llm) == "(no output)"
        assert llm.call_count == 2

    def test_retry_exhausted_returns_failure(self, monkeypatch):
        """重试耗尽且未达连续错误阈值时，注入错误消息继续（下一轮再失败）。"""
        monkeypatch.setattr("agents.subagent.time.sleep", lambda s: None)
        monkeypatch.setattr("agents.subagent.RetryConfig.DEFAULT_MAX_RETRIES", 1)
        errors = [LLMError("rate limit", APIErrorType.RATE_LIMIT)] * 6
        llm = _FakeLLM(errors)
        monkeypatch.setattr(state, "llm", llm)
        out = _run(llm, max_turns=3)
        # 3 轮各重试 1 次后失败 → 连续错误达 3 → 停止
        assert "SubAgent stopped" in out

    def test_first_turn_empty_messages_min_turns(self, monkeypatch):
        """max_turns=1 且第一轮即文本响应：正常返回。"""
        llm = _FakeLLM([_text_resp("quick")])
        monkeypatch.setattr(state, "llm", llm)
        assert _run(llm, max_turns=1) == "quick"


# ──────────────────────────────────────────────
#  保留的原有回归测试
# ──────────────────────────────────────────────

def test_run_agent_loop_resets_resp_each_turn(monkeypatch):
    """第二轮失败时不应复用第一轮 resp。

    max_turns=2：turn1 工具调用 → turn2 auth 错误（注入 <error>）→
    turn3 超过上限 → max_turns 停止（resp 为 None，final_text 空）。
    关键断言：不包含 turn1 的 'phase1' 文本（不复用旧响应）。
    """
    llm = _FakeLLM([
        _tool_use_resp(),
        LLMError("auth failed", APIErrorType.AUTH_ERROR),
    ])
    monkeypatch.setattr(state, "llm", llm)

    out = _run_agent_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do task"}],
        tool_defs=[],
        tool_handlers={},
        max_turns=2,
        agent_type="general",
    )

    # 修复后第二轮失败不会误用第一轮响应（'phase1' 不出现）。
    assert "phase1" not in out
    assert "max_turns" in out or "failed" in out or out == ""


def test_run_agent_loop_llm_timeout_guard(monkeypatch):
    """LLM 调用超时时应快速退出，而不是长期阻塞。"""

    def _slow_chat(_system_prompt, _messages, _tool_defs):
        time.sleep(0.05)
        return _text_resp("late")

    monkeypatch.setattr(state, "llm", _FakeLLM([_slow_chat]))
    monkeypatch.setattr("agents.subagent.LoopConfig.LLM_RESPONSE_TIMEOUT", 0.01)
    monkeypatch.setattr("agents.subagent.LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS", 1)
    monkeypatch.setattr("agents.subagent.RetryConfig.DEFAULT_MAX_RETRIES", 0)

    out = _run_agent_loop(
        system_prompt="sys",
        messages=[{"role": "user", "content": "do task"}],
        tool_defs=[],
        tool_handlers={},
        max_turns=1,
        agent_type="general",
    )

    assert "SubAgent stopped" in out
    assert "LLM errors" in out


# ──────────────────────────────────────────────
#  run_subagent 同步入口
# ──────────────────────────────────────────────

class TestRunSubagent:
    def test_dispatches_with_agent_config(self, monkeypatch):
        """run_subagent 应使用对应类型的配置（system_prompt/max_turns/工具过滤）。"""
        captured = {}

        def fake_loop(system_prompt, messages, tool_defs, tool_handlers,
                      max_turns, agent_type="general", status_callback=None,
                      description="", background=False):
            captured.update(
                system_prompt=system_prompt, max_turns=max_turns,
                agent_type=agent_type, tool_defs=tool_defs,
            )
            return "subagent result"

        monkeypatch.setattr("agents.subagent.get_filtered_tools", lambda allowed: (["d1"], {"h": 1}))
        monkeypatch.setattr("agents.subagent._run_agent_loop", fake_loop)

        out = run_subagent("find TODOs", agent_type="explore", description="scan")
        assert out == "subagent result"
        assert captured["agent_type"] == "explore"
        assert "Explore agent" in captured["system_prompt"]  # explore 类型的提示词
        assert captured["max_turns"] == 25                    # explore 配置的轮次
        assert captured["tool_defs"] == ["d1"]

    def test_unknown_type_raises(self):
        """未知 agent 类型应抛 ValueError 并列出可用类型。"""
        with pytest.raises(ValueError, match="explore"):
            run_subagent("x", agent_type="no_such_type")


# ──────────────────────────────────────────────
#  AgentTool 分发逻辑
# ──────────────────────────────────────────────

class TestAgentToolDispatch:
    def test_sync_by_default(self):
        """默认参数走同步 run_subagent。"""
        from tools import AgentTool
        with patch("agents.subagent.run_subagent", return_value="sync result") as mock_sync:
            out = AgentTool.handle(prompt="task", description="d", type="general")
        assert out == "sync result"
        mock_sync.assert_called_once_with("task", "general")

    def test_run_in_background_forces_async(self):
        """run_in_background=True 走异步 run_subagent_async。"""
        from tools import AgentTool
        with patch("agents.subagent.run_subagent_async",
                   return_value="started") as mock_async, \
             patch("agents.subagent.run_subagent") as mock_sync:
            out = AgentTool.handle(prompt="task", description="d",
                                   type="general", run_in_background=True)
        assert out == "started"
        mock_async.assert_called_once_with("task", "general", "d")
        mock_sync.assert_not_called()

    def test_verification_type_always_async(self):
        """verification 类型配置为始终后台运行。"""
        from tools import AgentTool
        with patch("agents.subagent.run_subagent_async",
                   return_value="bg started") as mock_async, \
             patch("agents.subagent.run_subagent") as mock_sync:
            AgentTool.handle(prompt="task", description="d", type="verification")
        mock_async.assert_called_once()
        mock_sync.assert_not_called()

    def test_definition_schema(self):
        """工具定义的 schema 完整性。"""
        from tools import AgentTool
        d = AgentTool.DEFINITION
        assert d["name"] == "agent"
        assert set(d["input_schema"]["required"]) == {"description", "prompt"}
        # enum 应覆盖全部内置类型
        assert set(d["input_schema"]["properties"]["type"]["enum"]) == {
            "explore", "plan", "general", "verification"}
