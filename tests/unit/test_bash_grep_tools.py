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
    monkeypatch.setattr("bootstrap.state.WORKDIR", tmp_path)
    return tmp_path


class TestBashToolSync:
    def test_simple_command_output(self, bash_workdir):
        out = BashTool.handle("echo hello")
        assert out == "hello"

    def test_command_failure_reports_exit_code(self, bash_workdir):
        out = BashTool.handle(f'"{sys.executable}" -c "import sys; sys.exit(2)"')
        assert out.startswith("Command failed (exit code 2)")

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

    def test_cwd_is_workdir(self, bash_workdir):
        # 在工作目录执行 cd（Windows cmd 的 cd 输出当前目录）
        out = BashTool.handle("cd")
        assert str(bash_workdir).lower() in out.lower()


class TestBashToolBackground:
    def test_background_returns_immediately(self, bash_workdir, monkeypatch):
        """后台任务应立即返回 started 消息，结果稍后进入通知队列。"""
        notifications = queue_mod.Queue()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(
                WORKDIR=bash_workdir,
                bg=SimpleNamespace(notifications=notifications)))

        start = time.time()
        out = BashTool.handle("echo bg-result", run_in_background=True)
        elapsed = time.time() - start

        assert elapsed < 1.0  # 立即返回，不阻塞
        assert out.startswith("Background task")
        assert "started" in out

        # 等待后台线程完成并验证通知
        notif = notifications.get(timeout=10)
        assert notif["status"] == "completed"
        assert "bg-result" in notif["result"]

    def test_background_failure_notifies_error(self, bash_workdir, monkeypatch):
        notifications = queue_mod.Queue()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(
                WORKDIR=bash_workdir,
                bg=SimpleNamespace(notifications=notifications)))

        BashTool.handle(
            f'"{sys.executable}" -c "raise SystemExit(2)"', run_in_background=True)
        notif = notifications.get(timeout=10)
        # 命令失败但后台执行本身未异常 → status 为 completed（含非零退出输出）
        assert notif["status"] in ("completed", "error")
        assert notif["task_id"]

    def test_background_timeout_notifies_error(self, bash_workdir, monkeypatch):
        notifications = queue_mod.Queue()
        monkeypatch.setattr(
            "tools.BashTool.state", SimpleNamespace(
                WORKDIR=bash_workdir,
                bg=SimpleNamespace(notifications=notifications)))

        BashTool.handle(
            f'"{sys.executable}" -c "import time; time.sleep(5)"',
            timeout=1, run_in_background=True)
        notif = notifications.get(timeout=10)
        assert notif["status"] == "error"
        assert "timed out" in notif["result"]


# grep 二进制是否可用（Windows 通常没有）
grep_available = shutil.which("grep") is not None


@pytest.mark.skipif(not grep_available, reason="system grep not available on this platform")
class TestGrepSearchTool:
    @pytest.fixture
    def grep_workdir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("bootstrap.state.WORKDIR", tmp_path)
        (tmp_path / "a.py").write_text("hello world\nfoo bar\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("hello again\n", encoding="utf-8")
        return tmp_path

    def test_basic_search(self, grep_workdir):
        out = GrepSearchTool.handle("hello", path=".")
        assert "hello world" in out
        assert "hello again" in out

    def test_search_with_include_filter(self, grep_workdir):
        out = GrepSearchTool.handle("hello", path=".", include="*.py")
        assert "a.py" in out
        assert "b.txt" not in out

    def test_no_matches(self, grep_workdir):
        out = GrepSearchTool.handle("zzz_nonexistent_pattern", path=".")
        assert out == "No matches found."

    def test_regex_pattern(self, grep_workdir):
        out = GrepSearchTool.handle("fo+r", path=".")
        assert "foo bar" in out

    def test_line_numbers_included(self, grep_workdir):
        out = GrepSearchTool.handle("hello", path="a.py")
        assert ":1:" in out or "a.py:1" in out

    def test_invalid_regex_returns_error(self, grep_workdir):
        out = GrepSearchTool.handle("(unclosed", path=".")
        assert out.startswith("Error")


@pytest.mark.skipif(grep_available, reason="grep available: testing Windows fallback behavior")
class TestGrepSearchToolNoGrep:
    def test_missing_grep_binary_returns_error(self, tmp_path, monkeypatch):
        """无 grep 二进制的平台上应返回错误信息而非崩溃。"""
        monkeypatch.setattr("bootstrap.state.WORKDIR", tmp_path)
        out = GrepSearchTool.handle("anything", path=".")
        assert out.startswith("Error")
