"""失败/异常处理加固测试。

覆盖审计发现的四个缺口：
  A. REPL 全局兜底：漏网异常只终结单次请求，会话保留
  B. 空响应检测：静默失败注入 <error> 续跑一次，仍空则正常结束
  C. workflow loader 兜底：坏配置返回错误提示而非炸穿
  D. traceback 降噪：完整堆栈进 trace，终端只有一行
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

import runtime.state as st


# ──────────────────────────────────────────────
#  A. 空响应检测（engine/loop.py）
# ──────────────────────────────────────────────

class TestEmptyResponseDetection:
    def _run_loop(self, responses):
        """用 mock LLM 依次返回给定响应，跑统一循环。"""
        from engine.loop import AgentLoop, LoopSpec, LoopHooks
        from llm.adapter import LLMResponse

        calls = {"n": 0}

        def fake_chat(system, messages, tools=None, max_tokens=8000,
                      stream=False, on_text=None):
            i = min(calls["n"], len(responses) - 1)
            calls["n"] += 1
            return responses[i]

        fake_llm = SimpleNamespace(chat=fake_chat)
        spec = LoopSpec(
            system_prompt="test", tool_defs=[], tool_handlers={},
            max_turns=10, llm_timeout=None, stream=False)
        loop = AgentLoop(fake_llm, spec, LoopHooks())
        messages = [{"role": "user", "content": "hello"}]
        return loop.run(messages), messages, calls["n"]

    @staticmethod
    def _resp(text=""):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)] if text else [],
            stop_reason="end_turn", input_tokens=10, output_tokens=0,
            is_truncated=False, truncated_text="")

    def test_empty_response_retried_once(self):
        """首次空响应 → 注入 <error> 续跑 → 第二次有内容正常结束。"""
        result, messages, n_calls = self._run_loop([
            self._resp(""), self._resp("Here is the answer."),
        ])
        assert result.stop_reason == "end_turn"
        assert result.final_text == "Here is the answer."
        assert n_calls == 2
        # 续跑提示已注入
        assert any("empty" in str(m.get("content", "")) for m in messages
                   if m["role"] == "user" and m is not messages[0])

    def test_empty_response_gives_up_after_retry(self):
        """重试后仍空 → 正常结束（不死循环）。"""
        result, messages, n_calls = self._run_loop([
            self._resp(""), self._resp(""),
        ])
        assert result.stop_reason == "end_turn"
        assert result.final_text == ""
        assert n_calls == 2  # 只重试一次

    def test_normal_response_not_affected(self):
        """正常响应不触发空响应路径。"""
        result, messages, n_calls = self._run_loop([
            self._resp("normal answer here"),
        ])
        assert result.final_text == "normal answer here"
        assert n_calls == 1


# ──────────────────────────────────────────────
#  B. workflow loader 兜底（gateway）
# ──────────────────────────────────────────────

class TestWorkflowLoaderGuard:
    def test_bad_workflow_id_returns_message(self, tmp_path, monkeypatch):
        """坏 workflow id → (True, 错误提示)，不抛异常。"""
        monkeypatch.chdir(tmp_path)
        from workflows.gateway import maybe_run_workflow

        messages = [{"role": "user",
                     "content": "/workflow no-such-workflow do something"}]
        handled, reply = maybe_run_workflow(messages)
        assert handled is True
        assert "failed" in reply.lower()

    def test_bad_yaml_returns_message(self, tmp_path, monkeypatch):
        """坏 YAML 配置 → 错误提示，不炸穿。"""
        monkeypatch.chdir(tmp_path)
        proj = tmp_path / ".xiaoagent" / "workflows"
        proj.mkdir(parents=True)
        (proj / "broken.yaml").write_text(
            "roles: [unclosed", encoding="utf-8")

        from workflows.gateway import maybe_run_workflow
        messages = [{"role": "user",
                     "content": "/workflow broken test requirement"}]
        handled, reply = maybe_run_workflow(messages)
        assert handled is True
        assert "failed" in reply.lower()


# ──────────────────────────────────────────────
#  C. REPL 全局兜底
# ──────────────────────────────────────────────

class TestReplGuard:
    def test_agent_loop_exception_caught(self, monkeypatch, tmp_path, capsys):
        """漏网异常 → 打印错误 + 会话保留提示，REPL 不崩。"""
        import ui.repl as repl_mod

        # 模拟 agent_loop 抛出漏网异常
        def exploding_loop(history, tracker=None, breaker=None):
            raise RuntimeError("unexpected bug in new code")

        monkeypatch.setattr(repl_mod, "agent_loop", exploding_loop)

        # 模拟用户输入一次后退出
        inputs = iter(["do something", "q"])
        monkeypatch.setattr("builtins.input", lambda *a: next(inputs))

        repl_mod.run_repl()  # 不应抛异常
        out = capsys.readouterr().out
        assert "Agent error" in out
        assert "Session preserved" in out


# ──────────────────────────────────────────────
#  D. traceback 降噪（adapter）
# ──────────────────────────────────────────────

class TestTracebackNoiseReduction:
    def test_traceback_goes_to_trace_not_terminal(self, tmp_path, monkeypatch, capsys):
        """异常时：终端只有一行（无 Traceback 块），完整堆栈进 trace 事件。"""
        from llm.adapter import LLMAdapter
        from services.tracing import Tracer

        tracer = Tracer(path=tmp_path / "t.jsonl")
        monkeypatch.setattr("services.tracing._default_tracer", tracer)

        adapter = LLMAdapter("openai",
                             SimpleNamespace(chat=None), "test-model")

        def always_fail(*args, **kw):
            raise RuntimeError("connection boom")

        with patch.object(adapter, "_call_openai", side_effect=always_fail):
            with pytest.raises(Exception):
                adapter.chat("sys", [{"role": "user", "content": "hi"}])

        out = capsys.readouterr().out
        assert "EXCEPTION in attempt" in out       # 一行摘要仍在
        assert "Traceback:" not in out             # 终端无堆栈
        # 完整堆栈进了 trace
        tb_events = [e for e in tracer._events if e["event"] == "llm_traceback"]
        assert len(tb_events) >= 1
        assert "RuntimeError" in tb_events[0]["traceback"]
