"""
tools/FileWriteTool.py - 文件写入工具

将内容写入文件，自动创建父目录。
System Prompt 中约束 LLM "优先用 edit_file，只对新文件用 write_file"。

对应 Claude Code 的 FileWriteTool。
"""

from utils.path import safe_path
from core.results import ToolResult

DEFINITION = {
    "name": "write_file",
    "description": (
        "Write content to a file. Creates the file if it doesn't exist, "
        "overwrites if it does. For modifying existing files, prefer edit_file."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The path to the file to write",
            },
            "content": {
                "type": "string",
                "description": "The content to write to the file",
            },
        },
        "required": ["file_path", "content"],
    },
}


def handle(file_path: str, content: str) -> str:
    """写入文件内容"""
    try:
        fp = safe_path(file_path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {file_path} ({len(content)} bytes)"
    except ValueError as e:
        # safe_path 路径逃逸
        return ToolResult.failure(f"Error writing file: {e}", "path_escape")
    except Exception as e:
        return ToolResult.failure(f"Error writing file: {e}", "io_error")
