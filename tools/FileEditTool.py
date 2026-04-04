"""
tools/FileEditTool.py - 文件编辑工具

精确替换文件中的文本（search-and-replace 策略）。
"""

from utils.path import safe_path

DEFINITION = {
    "name": "edit_file",
    "description": "Replace exact text in file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
        },
        "required": ["path", "old_text", "new_text"],
    },
}


def handle(path: str, old_text: str, new_text: str) -> str:
    """精确替换文件中的文本"""
    try:
        fp = safe_path(path)
        c = fp.read_text()
        if old_text not in c:
            return f"Error: Text not found in {path}"
        fp.write_text(c.replace(old_text, new_text, 1))
        return f"Edited {path}"
    except Exception as e:
        return f"Error: {e}"
