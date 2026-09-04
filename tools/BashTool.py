"""
tools/BashTool.py - Shell 命令执行工具

支持同步和异步（后台）两种执行方式。
- 同步（默认）：阻塞等待命令完成
- 异步（run_in_background=True）：后台线程执行，结果通过通知队列回传

对应 Claude Code 的 BashTool（同时包含 run_in_background 参数）。
"""

import re
import subprocess

from runtime.state import settings
from runtime import state
from utils.truncate import truncate_result
from engine.results import ToolResult

DEFINITION = {
    "name": "run_shell",
    "description": (
        "Run a shell command. Use this only for actual shell operations. "
        "Prefer read_file, write_file, edit_file, list_files, grep_search "
        "for file operations. Set run_in_background=true for long-running commands."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 120)",
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "Run in background. You'll be notified when done. "
                    "Use for long-running commands (build, install, test suites)."
                ),
            },
        },
        "required": ["command"],
    },
}

# grep/diff/test 等命令的退出码 1 不代表错误
_EXIT1_OK_COMMANDS = {"grep", "diff", "test", "cmp", "comm"}

# ── 自杀防护 ──────────────────────────────────────────────
# 终止 python 系进程的命令会连 agent 自身一起杀死（agent 就是 python 进程），
# 导致工作流/会话无痕中断（真实事故：metagpt 流程在 Engineer 轮被自身清理
# 命令杀掉，无 traceback、无转录落盘）。此类命令在工具层直接拒绝——
# bypass 权限模式也无法绕过（权限层危险清单只覆盖 taskkill，漏 wmic/Stop-Process）。
_KILL_VERBS = re.compile(
    r"\b(taskkill|stop-process|wmic|killall|pkill|tskill)\b", re.IGNORECASE)
_KILL_TARGET_PY = re.compile(
    r"\b(python\w*|py\.exe|python3(\.\d+)?)\b", re.IGNORECASE)
# 通配/无差别的进程终止（wmic process delete / killall python 之外的裸杀）
_KILL_ANY = re.compile(r"\bwmic\s+process\b", re.IGNORECASE)


def _would_kill_self(command: str) -> bool:
    """命令是否可能终止 agent 自身（python 进程）。"""
    if not _KILL_VERBS.search(command):
        return False
    # 无差别终止（如 taskkill /f /im python.exe 之外的宽泛写法）
    if _KILL_ANY.search(command) and _KILL_TARGET_PY.search(command):
        return True
    # 定向 python：taskkill python.exe / Stop-Process -Name python 等
    return bool(_KILL_TARGET_PY.search(command))


def handle(command: str, timeout: int = None, run_in_background: bool = False) -> str:
    """执行 shell 命令。run_in_background=True 时在后台线程执行。"""
    if not command or not command.strip():
        return ToolResult.failure("command cannot be empty", "invalid_input")
    # 工具级护栏：先于权限系统，任何模式都不可执行（防 agent 自杀）
    if _would_kill_self(command):
        return ToolResult.failure(
            "Refused: this command terminates python processes, which would kill "
            "the agent itself. If a process is stuck, prefer run_in_background "
            "with a timeout instead of killing python.",
            "self_kill_guard")
    if timeout is None:
        timeout = settings.shell.default_timeout
    if run_in_background:
        return _run_background(command, timeout)
    return _run_sync(command, timeout)


def _run_sync(command: str, timeout: int) -> str:
    """同步执行 shell 命令"""
    try:
        r = subprocess.run(
            command, shell=True, cwd=state.WORKDIR,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",  # S5: 显式 UTF-8，避免 GBK 解码崩溃
        )
        stdout = r.stdout.strip()
        stderr = r.stderr.strip()

        if r.returncode == 0:
            return truncate_result(stdout if stdout else "(no output)")

        cmd_name = command.strip().split()[0] if command.strip() else ""
        if r.returncode == 1 and cmd_name in _EXIT1_OK_COMMANDS:
            result = stdout if stdout else "(no matches)"
            if stderr:
                result += f"\nStderr: {stderr}"
            return truncate_result(result)

        parts = [f"Command failed (exit code {r.returncode})"]
        if stdout:
            parts.append(f"Stdout:\n{stdout}")
        if stderr:
            parts.append(f"Stderr:\n{stderr}")
        return ToolResult.failure(truncate_result("\n".join(parts)), "command_failed")
    except subprocess.TimeoutExpired:
        return ToolResult.failure(
            f"Error: Command timed out after {timeout}s", "timeout")


def _run_background(command: str, timeout: int) -> str:
    """后台线程执行，结果通过 state.bg 通知队列回传（S5: 复用 BackgroundManager，单一后台路径）"""
    from services.background import BackgroundManager
    # BashTool 始终通过全局单例运行（与 query.py 的 drain 消费方对齐）
    bg = state.bg if isinstance(state.bg, BackgroundManager) else BackgroundManager()
    return bg.run(command, timeout)
