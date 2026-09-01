"""
services/tasks.py - 持久化任务管理器

实现基于 JSON 文件的持久化任务系统（TaskManager）。
每个任务存储为 {tasks_dir}/task_{id}.json 文件，支持状态管理、
依赖关系（blockedBy）、任务认领（claim）等功能。

S2 重构：目录在 __init__ 时解析（默认 state.TASKS_DIR），
支持显式注入，便于测试与多实例。
"""

import json

from bootstrap import state


class TaskManager:
    """基于文件的持久化任务管理器"""

    def __init__(self, tasks_dir=None):
        """初始化任务目录（默认动态读取 state.TASKS_DIR，便于测试注入）"""
        self._injected_dir = tasks_dir
        self.tasks_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tasks_dir(self):
        """任务目录（运行时动态解析，未显式注入时跟随 state.TASKS_DIR）。"""
        if self._injected_dir is not None:
            return self._injected_dir
        return state.TASKS_DIR

    def _next_id(self) -> int:
        """获取下一个可用的任务 ID"""
        ids = [int(f.stem.split("_")[1]) for f in self.tasks_dir.glob("task_*.json")]
        return max(ids, default=0) + 1

    def _load(self, tid: int) -> dict:
        """加载指定 ID 的任务"""
        p = self.tasks_dir / f"task_{tid}.json"
        if not p.exists():
            raise ValueError(f"Task {tid} not found")
        return json.loads(p.read_text())

    def _save(self, task: dict):
        """将任务保存到文件"""
        (self.tasks_dir / f"task_{task['id']}.json").write_text(json.dumps(task, indent=2))

    def create(self, subject: str, description: str = "") -> str:
        """创建新任务"""
        task = {
            "id": self._next_id(),
            "subject": subject,
            "description": description,
            "status": "pending",
            "owner": None,
            "blockedBy": [],
        }
        self._save(task)
        return json.dumps(task, indent=2)

    def get(self, tid: int) -> str:
        """获取指定 ID 的任务详情"""
        return json.dumps(self._load(tid), indent=2)

    def update(self, tid: int, status: str = None,
               add_blocked_by: list = None, remove_blocked_by: list = None) -> str:
        """更新任务状态或依赖关系"""
        task = self._load(tid)
        if status:
            task["status"] = status
            if status == "completed":
                for f in self.tasks_dir.glob("task_*.json"):
                    t = json.loads(f.read_text())
                    if tid in t.get("blockedBy", []):
                        t["blockedBy"].remove(tid)
                        self._save(t)
            if status == "deleted":
                (self.tasks_dir / f"task_{tid}.json").unlink(missing_ok=True)
                return f"Task {tid} deleted"
        if add_blocked_by:
            task["blockedBy"] = list(set(task["blockedBy"] + add_blocked_by))
        if remove_blocked_by:
            task["blockedBy"] = [
                x for x in task["blockedBy"] if x not in remove_blocked_by
            ]
        self._save(task)
        return json.dumps(task, indent=2)

    def list_all(self) -> str:
        """列出所有任务"""
        tasks = [
            json.loads(f.read_text()) for f in sorted(self.tasks_dir.glob("task_*.json"))
        ]
        if not tasks:
            return "No tasks."
        lines = []
        for t in tasks:
            m = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(
                t["status"], "[?]"
            )
            owner = f" @{t['owner']}" if t.get("owner") else ""
            blocked = (
                f" (blocked by: {t['blockedBy']})" if t.get("blockedBy") else ""
            )
            lines.append(f"{m} #{t['id']}: {t['subject']}{owner}{blocked}")
        return "\n".join(lines)

    def claim(self, tid: int, owner: str) -> str:
        """认领任务"""
        task = self._load(tid)
        task["owner"] = owner
        task["status"] = "in_progress"
        self._save(task)
        return f"Claimed task #{tid} for {owner}"
