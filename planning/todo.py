"""
planning/todo.py - 待办事项管理器

实现轻量级内存待办清单（TodoManager），用于短期任务跟踪。
支持 pending / in_progress / completed 三种状态，最多 20 条，
同一时间只允许一条处于 in_progress 状态。
"""


class TodoManager:
    """内存待办清单管理器"""

    def __init__(self):
        """初始化空的待办列表"""
        self.items = []

    def update(self, items: list) -> str:
        """
        更新整个待办列表（全量替换）。

        Args:
            items: 待办项列表，每项需包含 content、status、activeForm
        Returns:
            格式化的待办列表渲染结果
        Raises:
            ValueError: 校验失败时抛出（缺少字段、状态无效、超出限制等）
        """
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
        if len(validated) > 20:
            raise ValueError("Max 20 todos")
        if ip > 1:
            raise ValueError("Only one in_progress allowed")
        self.items = validated
        return self.render()

    def render(self) -> str:
        """
        渲染待办列表为可读文本格式。

        Returns:
            格式化的待办列表字符串
        """
        if not self.items:
            return "No todos."
        lines = []
        for item in self.items:
            m = {"completed": "[x]", "in_progress": "[>]", "pending": "[ ]"}.get(
                item["status"], "[?]"
            )
            suffix = (
                f" <- {item['activeForm']}" if item["status"] == "in_progress" else ""
            )
            lines.append(f"{m} {item['content']}{suffix}")
        done = sum(1 for t in self.items if t["status"] == "completed")
        lines.append(f"\n({done}/{len(self.items)} completed)")
        return "\n".join(lines)

    def has_open_items(self) -> bool:
        """
        检查是否还有未完成的待办项。

        Returns:
            True 表示存在未完成项
        """
        return any(item.get("status") != "completed" for item in self.items)
