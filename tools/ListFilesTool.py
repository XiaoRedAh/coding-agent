"""
tools/ListFilesTool.py - 文件列表工具

按 glob 模式列出匹配的文件路径，按修改时间排序。
用于替代 find 或 ls 命令，提供更安全和结构化的文件发现能力。

对应 Claude Code 的 GlobTool（基于 fast-glob）。
"""

import glob as globmod
import os

from bootstrap.state import WORKDIR
from utils.truncate import truncate_result

DEFINITION = {
    "name": "list_files",
    "description": (
        "List files matching a glob pattern. Returns file paths "
        "sorted by modification time (newest first). Use this instead of find or ls."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": 'Glob pattern to match (e.g. "**/*.py", "src/**/*.ts")',
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: working directory)",
            },
        },
        "required": ["pattern"],
    },
}


def handle(pattern: str, path: str = None) -> str:
    """按 glob 模式列出匹配的文件"""
    try:
        search_dir = path or str(WORKDIR)
        full_pattern = os.path.join(search_dir, pattern)

        matches = globmod.glob(full_pattern, recursive=True)
        # 过滤掉目录，只保留文件
        files = [f for f in matches if os.path.isfile(f)]
        # 按修改时间排序（最近修改的在前）
        files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

        if not files:
            return "No files found matching pattern."

        # 转为相对路径显示
        rel_files = []
        for f in files:
            try:
                rel_files.append(os.path.relpath(f, str(WORKDIR)))
            except ValueError:
                rel_files.append(f)

        result = "\n".join(rel_files)
        if len(files) > 200:
            result += f"\n\n({len(files)} files total, showing first 200)"
            result = "\n".join(rel_files[:200]) + result.split("\n")[-1]

        return truncate_result(result)
    except Exception as e:
        return f"Error listing files: {e}"
