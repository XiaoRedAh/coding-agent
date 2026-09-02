"""
tools/TodoTool.py - 待办事项工具

轻量级内存待办清单，用于短期任务跟踪（会话内有效，不持久化）。
支持 pending / in_progress / completed 三种状态，条数上限可配置
（config/defaults.yaml tools.todo_max_items）。
"""

from runtime.state import settings

DEFINITION = {
    "name": "TodoWrite",
    "description": (
        "Update the task plan / checklist (in-memory, session-scoped). "
        "This REPLACES the entire list — include all items you want to keep. "
        "Max 20 items, only 1 can be in_progress at a time. "
        "Use when starting complex or multi-step work (plan first, then "
        "execute step by step), when the plan changes, or when completing "
        "items — not for simple single-step tasks."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Complete list of todo items (replaces existing list)",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Task description",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Task state",
                        },
                        "activeForm": {
                            "type": "string",
                            "description": (
                                "Present-continuous description shown for in_progress items "
                                "(e.g. 'Running tests', 'Writing auth module'). "
                                "Use a short phrase for any status."
                            ),
                        },
                    },
                    "required": ["content", "status", "activeForm"],
                },
            }
        },
        "required": ["items"],
    },
}


class TodoManager:
    """内存待办清单管理器"""

    def __init__(self):
        self.items = []

    def update(self, items: list) -> str:
        """全量替换待办列表"""
        validated, ip = [], 0
        for i, item in enumerate(items):
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "pending")).lower()
            af = str(item.get("activeForm", "")).strip()
            if not content:
                raise ValueError(f"Item {i}: content required")
            if status not in ("pending", "in_progress", "completed"):
                raise ValueError(f"Item {i}: invalid status '{status}'")
            if not af:
                raise ValueError(f"Item {i}: activeForm required")
            if status == "in_progress":
                ip += 1
            validated.append({"content": content, "status": status, "activeForm": af})
        if len(validated) > settings.tools.todo_max_items:
            raise ValueError(f"Max {settings.tools.todo_max_items} todos")
        if ip > 1:
            raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(item["status"], "[?]")
            suffix = f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        return any(item.get("status") != "completed" for item in self.items)
