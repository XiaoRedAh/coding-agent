"""
services/memory.py - 记忆系统

实现跨会话的持久化记忆：让 Agent "记住"用户偏好、项目上下文、历史决策。

核心机制：
1. 四种记忆类型：user / feedback / project / reference
2. 存储格式：Markdown + YAML frontmatter（每条记忆一个文件）
3. MEMORY.md 索引：始终注入 System Prompt（200 行上限）
4. 读写方式：LLM 通过 write_file/edit_file 工具直接操作记忆文件
   （对齐 CC 的做法——CC 也是让 LLM 用 Write 工具写记忆，不是单独的工具）

渐进式注入：
- MEMORY.md 索引始终在 System Prompt 中（指针列表，~500 token）
- 具体记忆文件由 LLM 按需通过 read_file 读取

对应 Claude Code 的 memdir/ 模块。
"""

import re
from pathlib import Path

from runtime import state
from runtime.state import settings

# 记忆类型
MEMORY_TYPES = {"user", "feedback", "project", "reference"}

# MEMORY.md 索引文件限制（config/defaults.yaml memory 节）
MAX_INDEX_LINES = settings.memory.max_index_lines
MAX_INDEX_BYTES = settings.memory.max_index_bytes

# 单个记忆文件限制
MAX_MEMORY_FILES = settings.memory.max_memory_files


class MemoryManager:
    """
    记忆管理器。

    管理 .xiaoagent/memory/ 目录下的记忆文件：
    - MEMORY.md — 索引文件（始终在 System Prompt 中）
    - *.md — 具体记忆文件（LLM 按需读取）
    """

    def __init__(self, memory_dir=None):
        """记忆目录（默认动态读取 state.MEMORY_DIR，支持显式注入便于测试）"""
        self.memory_dir = memory_dir if memory_dir is not None else state.MEMORY_DIR

    def ensure_dir(self):
        """确保记忆目录存在"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def get_index_content(self) -> str:
        """
        读取 MEMORY.md 索引内容。

        如果不存在，返回空字符串。
        如果超过限制（200 行或 25KB），截断并附加警告。
        """
        index_path = self.memory_dir / "MEMORY.md"
        if not index_path.exists():
            return ""
        try:
            content = index_path.read_text(encoding="utf-8")
        except Exception:
            return ""

        # 截断检查
        lines = content.splitlines()
        if len(lines) > MAX_INDEX_LINES:
            content = "\n".join(lines[:MAX_INDEX_LINES])
            content += f"\n\n[WARNING: MEMORY.md truncated at {MAX_INDEX_LINES} lines]"
        if len(content.encode("utf-8")) > MAX_INDEX_BYTES:
            content = content[:MAX_INDEX_BYTES]
            content += "\n\n[WARNING: MEMORY.md truncated at 25KB]"

        return content

    def get_prompt_section(self) -> str:
        """
        构建记忆系统的 System Prompt 片段。

        包含：
        1. 记忆系统使用说明（四种类型、如何保存、何时访问、不存什么）
        2. MEMORY.md 索引内容
        """
        self.ensure_dir()
        memory_dir_str = str(self.memory_dir)
        index_content = self.get_index_content()

        instructions = f"""# auto memory

You have a persistent, file-based memory system at `{memory_dir_str}`.

You should build up this memory system over time so that future conversations can have a complete picture of who the user is, how they'd like to collaborate with you, and the context behind the work.

If the user explicitly asks you to remember something, save it immediately. If they ask you to forget something, find and remove the relevant entry.

## Memory Types

- **user**: Information about the user's role, goals, preferences, knowledge level
  - When to save: When you learn details about the user
  - Example: "user is a data scientist, currently focused on logging"

- **feedback**: Guidance the user has given about how to approach work
  - When to save: When the user corrects your approach OR confirms a good approach
  - Structure: rule → **Why:** reason → **How to apply:** guidance
  - Example: "don't mock the database in tests — prior incident with mock/prod divergence"

- **project**: Information about ongoing work, goals, decisions NOT derivable from code/git
  - When to save: When you learn who is doing what, why, or by when
  - Structure: fact/decision → **Why:** motivation → **How to apply:** impact
  - Example: "merge freeze begins 2026-03-05 for mobile release cut"

- **reference**: Pointers to external systems and their purpose
  - When to save: When you learn about resources in external systems
  - Example: "pipeline bugs tracked in Linear project INGEST"

## How to Save Memories

Saving a memory is a two-step process:

**Step 1**: Write the memory file (e.g., `user_role.md`) using `write_file`:
```markdown
---
name: {{name}}
description: {{one-line description}}
type: {{user|feedback|project|reference}}
---
{{content}}
```

**Step 2**: Add a one-line entry to `MEMORY.md`:
```
- [Title](file.md) — one-line hook
```

## What NOT to Save

- Code patterns, architecture, file paths (derivable from code)
- Git history (use `git log`)
- Anything already in CLAUDE.md
- Current conversation details (use tasks instead)
- Debugging solutions (the fix is in the code)

## When to Access Memories

- When memories seem relevant to the current task
- When the user explicitly asks to recall something
- If unsure, check MEMORY.md index first"""

        # 追加 MEMORY.md 索引内容
        if index_content:
            instructions += f"\n\n## Current Memory Index\n\n{index_content}"
        else:
            instructions += f"\n\n## Current Memory Index\n\n(empty — no memories saved yet)"

        return instructions

    def list_memories(self) -> list[dict]:
        """
        扫描记忆目录，返回所有记忆文件的元数据。

        Returns:
            [{"name": ..., "description": ..., "type": ..., "path": ...}, ...]
        """
        if not self.memory_dir.exists():
            return []
        memories = []
        for f in sorted(self.memory_dir.glob("*.md")):
            if f.name == "MEMORY.md":
                continue
            try:
                text = f.read_text(encoding="utf-8")
                meta = self._parse_frontmatter(text)
                memories.append({
                    "name": meta.get("name", f.stem),
                    "description": meta.get("description", ""),
                    "type": meta.get("type", "unknown"),
                    "path": str(f),
                })
            except Exception:
                continue
        return memories

    def is_memory_path(self, file_path: str) -> bool:
        """检查文件路径是否在记忆目录内（用于权限白名单）"""
        try:
            resolved = Path(file_path).resolve()
            return resolved.is_relative_to(self.memory_dir.resolve())
        except (ValueError, OSError):
            return False

    @staticmethod
    def _parse_frontmatter(text: str) -> dict:
        """解析 YAML frontmatter"""
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        if not match:
            return {}
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta
