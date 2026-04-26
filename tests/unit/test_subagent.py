"""Unit tests for subagent loop timeout and stale-response handling."""

import time
from types import SimpleNamespace

from agents.subagent import _run_agent_loop
from bootstrap import state
from services.api_errors import APIErrorType, LLMError


class _FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    def chat(self, system_prompt, messages, tool_defs):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(system_prompt, messages, tool_defs)
        return item


def _tool_use_resp():
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[
            SimpleNamespace(type="text", text="phase1"),
            SimpleNamespace(type="tool_use", id="t1", name="unknown_tool", input={}),
        ],
    )


def test_run_agent_loop_resets_resp_each_turn(monkeypatch):
    """第二轮失败时不应复用第一轮 resp。"""
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

    # 修复后第二轮失败不会误用第一轮响应。
    assert out == "(subagent failed)"


def test_run_agent_loop_llm_timeout_guard(monkeypatch):
    """LLM 调用超时时应快速退出，而不是长期阻塞。"""

    def _slow_chat(_system_prompt, _messages, _tool_defs):
        time.sleep(0.05)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="late")])

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
