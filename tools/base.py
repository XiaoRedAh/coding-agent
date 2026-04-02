"""
tools/base.py - 基础工具函数

提供文件和命令行操作的核心工具：
- safe_path: 路径安全检查，防止路径逃逸
- run_bash: 执行 shell 命令（带危险命令过滤）
- run_read: 读取文件内容
- run_write: 写入文件内容
- run_edit: 精确替换文件中的文本
"""

import subprocess
from pathlib import Path

from config import WORKDIR


def safe_path(p: str) -> Path:
    """
    将相对路径解析为绝对路径，并确保不会逃逸出工作目录。

    Args:
        p: 文件路径字符串
    Returns:
        解析后的安全 Path 对象
    Raises:
        ValueError: 路径逃逸出工作目录时抛出
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def run_bash(command: str) -> str:
    """
    执行 shell 命令，带有危险命令过滤和超时保护。

    Args:
        command: 要执行的 shell 命令
    Returns:
        命令的标准输出和标准错误（截断到 50000 字符）
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(d in command for d in dangerous):
        return "Error: Dangerous command blocked"
    try:
        r = subprocess.run(command, shell=True, cwd=WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_read(path: str, limit: int = None) -> str:
    """
    读取文件内容，可选行数限制。

    Args:
        path: 文件路径
        limit: 最大读取行数（None 表示全部读取）
    Returns:
        文件内容字符串（截断到 50000 字符）
    """
    try:
        lines = safe_path(path).read_text().splitlines()
        if limit and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more)"]
        return "\n".join(lines)[:50000]
    except Exception as e:
        return f"Error: {e}"


def run_write(path: str, content: str) -> str:
    """
    将内容写入文件，自动创建父目录。

    Args:
        path: 文件路径
        content: 要写入的内容
    Returns:
        写入结果描述
    """
    try:
        fp = safe_path(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content)
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error: {e}"


def run_edit(path: str, old_text: str, new_text: str) -> str:
    """
    精确替换文件中的文本（只替换第一次出现）。

    Args:
        path: 文件路径
        old_text: 要查找的原始文本
        new_text: 替换后的新文本
    Returns:
        编辑结果描述
    """
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"
