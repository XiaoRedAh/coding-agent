"""
tools/GrepSearchTool.py - 内容搜索工具（纯 Python 实现，S5 重构）

在文件中搜索匹配正则表达式的内容，返回带行号的匹配结果。
原实现依赖系统 grep 二进制（Windows 不可用、编码不可控），
S5 改为纯 Python 实现：跨平台、显式 UTF-8、行为可控。

对应 Claude Code 的 GrepTool（其内部为 ripgrep）。
"""

import os
import re
import time

from runtime import state
from runtime.state import settings
from utils.truncate import truncate_result
from engine.results import ToolResult

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

# 跳过的目录（对齐 rg 默认行为 + 版本控制目录）
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".mypy_cache", ".pytest_cache",
    "node_modules", ".venv", "venv", ".idea", ".vscode", ".xiaoagent",
}


def _iter_files(search_root: str, include: str | None):
    """遍历搜索根下的文件（目录递归），按 include glob 过滤。"""
    import fnmatch

    if os.path.isfile(search_root):
        yield search_root
        return

    if include:
        include_matcher = fnmatch.fnmatch
    for dirpath, dirnames, filenames in os.walk(search_root):
        # 原地过滤目录，阻止进入跳过项
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            if include and not include_matcher(fname, include):
                continue
            yield os.path.join(dirpath, fname)


def _read_lines_safe(path: str) -> list[tuple[int, str]] | None:
    """
    读取文件行。二进制文件或解码失败 → None（跳过）。

    编码策略：UTF-8 优先，失败时用本地编码兜底再试一次，
    仍失败则视为二进制跳过（对齐 grep 对二进制文件的行为）。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None

    # NUL 字节是二进制文件的强信号（grep 同款启发式）
    if b"\x00" in raw[:8192]:
        return None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return None

    lines = text.splitlines()
    return list(enumerate(lines, start=1))


def handle(pattern: str, path: str = None, include: str = None) -> str:
    """搜索文件内容（纯 Python 实现，跨平台）"""
    max_matches = settings.tools.grep_max_matches
    timeout_s = settings.tools.grep_timeout

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return ToolResult.failure(f"Error: Invalid regex pattern: {e}", "invalid_input")

    # path 为相对路径时相对 WORKDIR 解析（默认 "." 即整个工作目录）
    if path and not os.path.isabs(path):
        search_path = os.path.join(str(state.WORKDIR), path)
    elif path:
        search_path = path
    else:
        search_path = str(state.WORKDIR)

    if not os.path.exists(search_path):
        return ToolResult.failure(f"Error: Path not found: {search_path}", "not_found")

    started = time.time()
    matches: list[str] = []
    truncated = False

    for file_path in _iter_files(search_path, include):
        if time.time() - started > timeout_s:
            return ToolResult.failure(
                f"Error: Search timed out ({timeout_s}s)", "timeout")

        numbered = _read_lines_safe(file_path)
        if numbered is None:
            continue

        # 显示相对路径（相对 WORKDIR，退回相对搜索根）
        try:
            display = os.path.relpath(file_path, str(state.WORKDIR))
        except ValueError:
            display = file_path

        for lineno, line in numbered:
            if regex.search(line):
                if len(matches) >= max_matches:
                    truncated = True
                    break
                matches.append(f"{display}:{lineno}:{line.rstrip()}")
        if truncated:
            break

    if not matches:
        return "No matches found."

    result = "\n".join(matches)
    if truncated:
        result += f"\n\n... and more matches (showing first {max_matches})"
    return truncate_result(result)
