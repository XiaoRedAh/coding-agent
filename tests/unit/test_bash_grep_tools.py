"""Unit tests for BashTool and GrepSearchTool.

BashTool 使用跨平台命令（echo / python）避免 shell 差异。
GrepSearchTool 依赖系统 grep 二进制 —— Windows 无原生 grep，自动跳过。
"""

import queue as queue_mod
import shutil
import sys
import time
from types import SimpleNamespace

import pytest

from tools import BashTool, GrepSearchTool


@pytest.fixture
def bash_workdir(tmp_path, monkeypatch):
    monkeypatch.setattr("runtime.state.WORKDIR", tmp_path)
    return tmp_path


class TestBashToolSync:
    def test_simple_command_output(self, bash_workdir):
        out = BashTool.handle("echo hello")
        assert out == "hello"

    def test_command_failure_reports_exit_code(self, bash_workdir):
        out = BashTool.handle(f'"{sys.executable}" -c "import sys; sys.exit(2)"')
        assert out.startswith("Command failed (exit code 2)")
        assert out.ok is False
        assert out.error == "command_failed"

    def test_command_stderr_included_on_failure(self, bash_workdir):
        out = BashTool.handle(
            f'"{sys.executable}" -c "import sys; print(\'boom\', file=sys.stderr); sys.exit(1)"')
        assert "Command failed (exit code 1)" in out
        assert "boom" in out

    def test_no_output_placeholder(self, bash_workdir):
        out = BashTool.handle("rem") if sys.platform == "win32" else BashTool.handle("true")
        assert out == "(no output)"

    def test_timeout_returns_error(self, bash_workdir):
        out = BashTool.handle(f'"{sys.executable}" -c "import time; time.sleep(3)"', timeout=1)
        assert out == "Error: Command timed out after 1s"
        assert out.error == "timeout"

    def test_cwd_is_workdir(self, bash_workdir):
        # 在工作目录执行 cd（Windows cmd 的 cd 输出当前目录）
        out = BashTool.handle("cd")
        assert str(bash_workdir).lower() in out.lower()


class TestBashToolBackground:
    """S5 后后台路径统一走 BackgroundManager（state.bg.run）。"""

    def _bg_manager(self, bash_workdir):
        from services.background import BackgroundManager
        return BackgroundManager()

    def test_background_returns_immediately(self, bash_workdir, monkeypatch):
        """后台任务应立即返回 started 消息，结果稍后进入通知队列。"""
        from services.background import BackgroundManager
        bg = BackgroundManager()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(WORKDIR=bash_workdir, bg=bg))

        start = time.time()
        out = BashTool.handle("echo bg-result", run_in_background=True)
        elapsed = time.time() - start

        assert elapsed < 1.0  # 立即返回，不阻塞
        assert out.startswith("Background task")
        assert "started" in out

        # 等待后台线程完成并验证通知
        notif = bg.notifications.get(timeout=10)
        assert notif["status"] == "completed"
        assert "bg-result" in notif["result"]

    def test_background_failure_notifies_error(self, bash_workdir, monkeypatch):
        from services.background import BackgroundManager
        bg = BackgroundManager()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(WORKDIR=bash_workdir, bg=bg))

        BashTool.handle(
            f'"{sys.executable}" -c "raise SystemExit(2)"', run_in_background=True)
        notif = bg.notifications.get(timeout=10)
        # 命令失败但后台执行本身未异常 → status 为 completed（含非零退出输出）
        assert notif["status"] in ("completed", "error")
        assert notif["task_id"]

    def test_background_timeout_notifies_error(self, bash_workdir, monkeypatch):
        from services.background import BackgroundManager
        bg = BackgroundManager()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(WORKDIR=bash_workdir, bg=bg))

        BashTool.handle(
            f'"{sys.executable}" -c "import time; time.sleep(5)"',
            timeout=1, run_in_background=True)
        notif = bg.notifications.get(timeout=10)
        assert notif["status"] == "error"
        assert "timed out" in notif["result"]

    def test_background_uses_global_bg_when_available(self, bash_workdir, monkeypatch):
        """state.bg 已是 BackgroundManager 时应复用全局实例（通知对齐 drain 消费方）。"""
        from services.background import BackgroundManager
        bg = BackgroundManager()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(WORKDIR=bash_workdir, bg=bg))
        out = BashTool.handle("echo reuse-check", run_in_background=True)
        assert "started" in out
        notif = bg.notifications.get(timeout=10)
        assert "reuse-check" in notif["result"]


# S5 后 grep 为纯 Python 实现，跨平台可用，无需 skip
class TestGrepSearchTool:
    @pytest.fixture
    def grep_workdir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("runtime.state.WORKDIR", tmp_path)
        monkeypatch.chdir(tmp_path)
        (tmp_path / "a.py").write_text("hello world\nfoo bar\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("hello again\n", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.py").write_text("nested hello\n", encoding="utf-8")
        return tmp_path

    def test_basic_search(self, grep_workdir):
        out = GrepSearchTool.handle("hello", path=".")
        assert "hello world" in out
        assert "hello again" in out
        assert "nested hello" in out

    def test_search_with_include_filter(self, grep_workdir):
        out = GrepSearchTool.handle("hello", path=".", include="*.py")
        assert "a.py" in out
        assert "b.txt" not in out

    def test_no_matches(self, grep_workdir):
        out = GrepSearchTool.handle("zzz_nonexistent_pattern", path=".")
        assert out == "No matches found."

    def test_regex_pattern(self, grep_workdir):
        """正则量词与字符类：fo+ 应匹配 foo（注意 fo+r 不匹配 "foo bar"——foo 后无 r）。"""
        out = GrepSearchTool.handle("fo+", path=".")
        assert "foo bar" in out
        out2 = GrepSearchTool.handle("h[ea]llo", path=".")
        assert "hello world" in out2
        assert "hello again" in out2

    def test_line_numbers_included(self, grep_workdir):
        out = GrepSearchTool.handle("hello", path="a.py")
        assert "a.py:1:hello world" in out

    def test_invalid_regex_returns_error(self, grep_workdir):
        out = GrepSearchTool.handle("(unclosed", path=".")
        assert out.startswith("Error")
        assert out.error == "invalid_input"

    def test_path_not_found_returns_error(self, grep_workdir):
        out = GrepSearchTool.handle("x", path="no_such_dir")
        assert out.startswith("Error")
        assert out.error == "not_found"

    def test_recursive_search(self, grep_workdir):
        """子目录文件也应被搜索到。"""
        out = GrepSearchTool.handle("nested", path=".")
        assert "nested hello" in out
        assert "sub" in out

    def test_skip_dirs_excluded(self, grep_workdir):
        """.git / __pycache__ 等目录应被跳过。"""
        skip_dir = grep_workdir / "__pycache__"
        skip_dir.mkdir()
        (skip_dir / "cached.py").write_text("hidden_marker\n", encoding="utf-8")
        out = GrepSearchTool.handle("hidden_marker", path=".")
        assert out == "No matches found."

    def test_binary_file_skipped(self, grep_workdir):
        """含 NUL 字节的二进制文件应被跳过。"""
        (grep_workdir / "blob.bin").write_bytes(b"marker\x00binary\x00data")
        out = GrepSearchTool.handle("marker", path=".")
        assert "blob.bin" not in out

    def test_utf8_chinese_content(self, grep_workdir):
        (grep_workdir / "cn.txt").write_text("你好世界\n", encoding="utf-8")
        out = GrepSearchTool.handle("你好", path=".")
        assert "你好世界" in out

    def test_nonexistent_path_returns_error(self, grep_workdir):
        out = GrepSearchTool.handle("x", path="no_such_dir")
        assert out.startswith("Error")

    def test_max_matches_truncation(self, grep_workdir, monkeypatch):
        """超过上限的匹配应截断并提示（直接 patch 模块内读取的常量）。"""
        # handle 内每次调用从 settings 读取，patch settings.tools 的 getter 行不通
        # （冻结 dataclass），改 patch tools.GrepSearchTool.settings
        from types import SimpleNamespace
        import runtime.state as st
        fake_settings = SimpleNamespace(
            tools=SimpleNamespace(
                grep_max_matches=2,
                grep_timeout=st.settings.tools.grep_timeout,
            ))
        monkeypatch.setattr("tools.GrepSearchTool.settings", fake_settings)
        # 3 个 hello 匹配 > 上限 2
        out = GrepSearchTool.handle("hello", path=".")
        assert "more matches" in out
        assert "showing first 2" in out
