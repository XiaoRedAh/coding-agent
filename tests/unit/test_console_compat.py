"""控制台兼容与 REPL 交互修复测试。

覆盖：
  A. 空回车不退出（空提交 → 重新提示），EOF/q 正常退出
  B. 控制台符号回退（ASCII_SYMBOLS 的确定性）
  C. base.md 反"我做不到"引导注入
"""

from pathlib import Path

import pytest

import ui.console as console_mod


# ──────────────────────────────────────────────
#  A. 空输入语义
# ──────────────────────────────────────────────

class TestEmptyInput:
    def test_empty_enter_continues(self, monkeypatch, capsys):
        """空回车 → 重新提示（不退出），随后 /exit 退出。"""
        import ui.repl as repl_mod

        inputs = iter(["", "/exit"])  # 先空回车，再退出

        def fake_input(prompt=""):
            print(prompt, end="")  # 模拟真实 input 打印提示符
            return next(inputs)

        monkeypatch.setattr("builtins.input", fake_input)

        repl_mod.run_repl()
        out = capsys.readouterr().out
        # 空回车后 REPL 仍活着并再次打印提示符（出现两次提示符）
        assert out.count("coding-agent >>") >= 2

    def test_single_q_not_exit(self, monkeypatch, capsys):
        """单字母 q 不再是退出指令（防误触：想打 quick 却丢了会话）。"""
        import ui.repl as repl_mod

        inputs = iter(["quick question", "/exit"])

        def fake_input(prompt=""):
            print(prompt, end="")
            return next(inputs)

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(repl_mod, "agent_loop",
                            lambda history, tracker=None, breaker=None:
                            (tracker, breaker))
        repl_mod.run_repl()
        out = capsys.readouterr().out
        # 'quick question' 被当作普通输入处理（未退出），/exit 才退出
        assert out.count("coding-agent >>") >= 2

    def test_eof_exits(self, monkeypatch, capsys):
        """EOF（Ctrl+Z/管道结束）→ 退出。"""
        import ui.repl as repl_mod

        def raise_eof(*a):
            raise EOFError()

        monkeypatch.setattr("builtins.input", raise_eof)
        repl_mod.run_repl()  # 应正常返回不抛异常

    def test_piped_empty_line_does_not_hang(self, monkeypatch, capsys):
        """非交互管道下空行 + EOF：空行被跳过，EOF 退出（不死循环）。"""
        import ui.repl as repl_mod

        inputs = iter(["", "hello"])

        def fake_input(prompt=""):
            try:
                return next(inputs)
            except StopIteration:
                raise EOFError()

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(repl_mod, "agent_loop",
                            lambda history, tracker=None, breaker=None:
                            (tracker, breaker))
        repl_mod.run_repl()  # 不死循环、不抛异常


# ──────────────────────────────────────────────
#  B. 控制台符号
# ──────────────────────────────────────────────

class TestConsoleSymbols:
    def test_symbols_are_ascii_on_windows(self):
        """ASCII_SYMBOLS 模式下所有符号均为纯 ASCII（GBK 字体可渲染）。"""
        monkey_value = True
        original = console_mod.ASCII_SYMBOLS
        console_mod.ASCII_SYMBOLS = monkey_value
        try:
            assert all(ord(c) < 128 for c in console_mod.spinner_frames()[0])
            assert all(ord(c) < 128 for c in console_mod.warn_sym())
            assert all(ord(c) < 128 for c in console_mod.fail_sym())
            assert all(ord(c) < 128 for c in console_mod.ok_sym())
        finally:
            console_mod.ASCII_SYMBOLS = original

    def test_setup_console_noop_on_posix(self, monkeypatch):
        """非 Windows 平台 setup_console 直接返回（不抛异常）。"""
        monkeypatch.setattr(console_mod.os, "name", "posix")
        console_mod.setup_console()  # 应无操作无异常

    def test_setup_console_windows_resilient(self, monkeypatch):
        """Windows 上 ctypes 失败时回退 os.system，不抛异常。"""
        monkeypatch.setattr(console_mod.os, "name", "nt")

        def boom():
            raise OSError("no console")

        monkeypatch.setattr(console_mod, "os", type("FakeOS", (), {
            "name": "nt", "system": staticmethod(boom),
        })())
        console_mod.setup_console()  # 全部失败也不抛


# ──────────────────────────────────────────────
#  C. 反"我做不到"引导
# ──────────────────────────────────────────────

class TestNeverSayCant:
    def test_base_md_contains_never_say_cant(self):
        from prompts.loader import PromptLoader
        base = PromptLoader(user_dir=Path("nonexistent_user_dir_xyz")).load("base.md")
        assert "NEVER say you cannot do something" in base
        assert "run_shell" in base          # 指明了能力来源
        assert "curl" in base               # 给了具体例子
        assert "wttr.in" in base            # 天气场景示范

    def test_guidance_in_static_block(self, tmp_workdir, monkeypatch):
        """引导在静态区（可被 prompt cache）。"""
        import runtime.state as st
        from context.prompt import build_system_prompt

        monkeypatch.setattr(st, "memory", None)
        monkeypatch.setattr(st, "skills", None)
        blocks = build_system_prompt()
        assert "NEVER say you cannot" in blocks[0]["text"]
