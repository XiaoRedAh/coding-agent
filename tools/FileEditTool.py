"""
tools/FileEditTool.py - 文件编辑工具

精确替换文件中的文本（search-and-replace 策略）。
实现了三个关键机制：
1. 唯一匹配检查 — old_string 必须恰好出现一次，防止歧义编辑
2. 引号容错 — 自动处理 curly quotes → straight quotes 的转换
3. Diff 输出 — 编辑成功后显示变更行号和修改内容

对应 Claude Code 的 FileEditTool（14 步验证流水线的简化版）。
"""

import re

from utils.path import safe_path
from core.results import ToolResult

DEFINITION = {
    "name": "edit_file",
    "description": (
        "Edit a file by replacing an exact string match with new content. "
        "The old_string must match exactly and appear only once in the file. "
        "Prefer this over write_file for modifying existing files."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "The path to the file to edit",
            },
            "old_string": {
                "type": "string",
                "description": "The exact string to find and replace",
            },
            "new_string": {
                "type": "string",
                "description": "The string to replace it with",
            },
        },
        "required": ["file_path", "old_string", "new_string"],
    },
}


def _normalize_quotes(s: str) -> str:
    """将 curly quotes 标准化为 straight quotes（模型输出容错）"""
    s = re.sub(r"[\u2018\u2019\u2032]", "'", s)   # curly single → straight
    s = re.sub(r"[\u201C\u201D\u2033]", '"', s)    # curly double → straight
    return s


def _find_actual_string(file_content: str, search_string: str) -> str | None:
    """
    在文件内容中查找目标字符串，支持引号容错。

    先尝试精确匹配，失败后用标准化引号匹配。
    返回文件中实际匹配到的原始字符串，或 None。
    """
    if search_string in file_content:
        return search_string
    norm_search = _normalize_quotes(search_string)
    norm_file = _normalize_quotes(file_content)
    idx = norm_file.find(norm_search)
    if idx != -1:
        return file_content[idx : idx + len(search_string)]
    return None


def _generate_diff(
    old_content: str, new_content: str, old_string: str, new_string: str
) -> str:
    """生成简易 diff 输出，显示变更行号和修改内容"""
    line_num = old_content.split(old_string)[0].count("\n") + 1
    old_lines = old_string.splitlines()
    new_lines = new_string.splitlines()
    parts = [f"@@ -{line_num},{len(old_lines)} +{line_num},{len(new_lines)} @@"]
    for line in old_lines:
        parts.append(f"- {line}")
    for line in new_lines:
        parts.append(f"+ {line}")
    return "\n".join(parts)


def handle(file_path: str, old_string: str, new_string: str) -> str:
    """精确替换文件中的文本，带唯一性检查和引号容错"""
    try:
        fp = safe_path(file_path)
        content = fp.read_text(encoding="utf-8")

        # 查找匹配（支持引号容错）
        actual = _find_actual_string(content, old_string)
        if actual is None:
            return ToolResult.failure(
                f"Error: old_string not found in {file_path}", "not_found")

        # 唯一匹配检查
        count = content.count(actual)
        if count > 1:
            return ToolResult.failure(
                f"Error: old_string found {count} times in {file_path}. "
                f"Must be unique. Provide more surrounding context to disambiguate.",
                "ambiguous_match")

        # 执行替换
        new_content = content.replace(actual, new_string, 1)
        fp.write_text(new_content, encoding="utf-8")

        # 生成 diff 输出
        via_note = ""
        if actual != old_string:
            via_note = " (matched via quote normalization)"
        diff = _generate_diff(content, new_content, actual, new_string)
        return f"Successfully edited {file_path}{via_note}\n\n{diff}"
    except ValueError as e:
        return ToolResult.failure(f"Error editing file: {e}", "path_escape")
    except FileNotFoundError as e:
        return ToolResult.failure(f"Error editing file: {e}", "not_found")
    except Exception as e:
        return ToolResult.failure(f"Error editing file: {e}", "io_error")
