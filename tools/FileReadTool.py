"""
tools/FileReadTool.py - 文件读取工具

读取文件内容并附加行号，支持行数限制。
行号帮助 LLM 定位代码位置，与 edit_file 的精确匹配策略配合。

对应 Claude Code 的 FileReadTool（cat -n 风格行号输出）。
"""

from utils.path import safe_path
from utils.truncate import truncate_result

DEFINITION = {
    "name": "read_file",
    "description": (
        "Read the contents of a file. Returns the file content with line numbers. "
        "Use this instead of cat, head, tail, or sed."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The path to the file to read",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to read",
            },
        },
        "required": ["file_path"],
    },
}


def handle(file_path: str, limit: int = None) -> str:
    """读取文件内容，返回带行号的文本"""
    try:
        lines = safe_path(file_path).read_text(encoding="utf-8").splitlines()
        total = len(lines)
        if limit and limit < total:
            lines = lines[:limit]
            truncated_note = f"\n... ({total - limit} more lines)"
        else:
            truncated_note = ""
        numbered = [
            f"{str(i + 1).rjust(4)} | {line}" for i, line in enumerate(lines)
        ]
        return truncate_result("\n".join(numbered) + truncated_note)
    except Exception as e:
        return f"Error reading file: {e}"
