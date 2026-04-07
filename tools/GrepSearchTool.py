"""
tools/GrepSearchTool.py - 内容搜索工具

在文件中搜索匹配正则表达式的内容，返回带行号的匹配结果。
使用系统 grep 命令（Claude Code 使用 ripgrep，我们用系统 grep 减少依赖）。

对应 Claude Code 的 GrepTool。
"""

import subprocess

from bootstrap.state import WORKDIR
from utils.truncate import truncate_result

DEFINITION = {
    "name": "grep_search",
    "description": (
        "Search file contents using a regular expression pattern. Returns "
        "matching lines with file paths and line numbers. Use this instead of grep."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regular expression pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search in (default: working directory)",
            },
            "include": {
                "type": "string",
                "description": 'File pattern to include (e.g. "*.py", "*.ts")',
            },
        },
        "required": ["pattern"],
    },
}

# 最大返回匹配行数
_MAX_MATCHES = 100


def handle(pattern: str, path: str = None, include: str = None) -> str:
    """搜索文件内容"""
    try:
        search_path = path or "."
        args = ["grep", "--line-number", "--color=never", "-r", "-E"]  # -E for extended regex
        if include:
            args.append(f"--include={include}")
        args.append(pattern)
        args.append(search_path)

        r = subprocess.run(
            args,
            cwd=WORKDIR,
            capture_output=True,
            text=True,
            timeout=10,
        )

        if r.returncode == 1:
            return "No matches found."
        if r.returncode > 1:
            return f"Error: {r.stderr.strip()}"

        lines = [l for l in r.stdout.strip().split("\n") if l]
        total = len(lines)
        if total > _MAX_MATCHES:
            result = "\n".join(lines[:_MAX_MATCHES])
            result += f"\n\n... and {total - _MAX_MATCHES} more matches"
        else:
            result = "\n".join(lines)

        return truncate_result(result)
    except subprocess.TimeoutExpired:
        return "Error: Search timed out (10s)"
    except Exception as e:
        return f"Error: {e}"
