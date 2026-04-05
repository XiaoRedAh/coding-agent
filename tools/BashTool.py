"""
tools/BashTool.py - Shell 命令执行工具

执行 shell 命令，带有危险命令过滤、超时保护和退出码语义理解。
改进点：分离 stdout/stderr，报告退出码，理解 grep/diff 等命令的特殊退出码。

对应 Claude Code 的 BashTool（18 个源文件的大幅简化版）。
"""

import subprocess

from bootstrap.state import WORKDIR
from utils.truncate import truncate_result

DEFINITION = {
    "name": "run_shell",
    "description": (
        "Run a shell command. Use this only for actual shell operations. "
        "Prefer read_file, write_file, edit_file, list_files, grep_search "
        "for file operations."
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
        },
        "required": ["command"],
    },
}

# grep/diff/test 等命令的退出码 1 不代表错误
_EXIT1_OK_COMMANDS = {"grep", "diff", "test", "cmp", "comm"}


def handle(command: str, timeout: int = 120) -> str:
    """执行 shell 命令，分离 stdout/stderr 并报告退出码。

    危险命令检测已移至 services/permissions.py 的权限管线中，
    在 query.py 的工具执行前统一检查。
    """
    try:
        r = subprocess.run(
            command,
            shell=True,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stdout = r.stdout.strip()
        stderr = r.stderr.strip()

        if r.returncode == 0:
            return truncate_result(stdout if stdout else "(no output)")

        # 退出码 1 对某些命令是正常行为（如 grep 无匹配）
        cmd_name = command.strip().split()[0] if command.strip() else ""
        if r.returncode == 1 and cmd_name in _EXIT1_OK_COMMANDS:
            result = stdout if stdout else "(no matches)"
            if stderr:
                result += f"\nStderr: {stderr}"
            return truncate_result(result)

        # 真正的错误
        parts = [f"Command failed (exit code {r.returncode})"]
        if stdout:
            parts.append(f"Stdout:\n{stdout}")
        if stderr:
            parts.append(f"Stderr:\n{stderr}")
        return truncate_result("\n".join(parts))
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {timeout}s"
