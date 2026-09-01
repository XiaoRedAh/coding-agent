"""
services/background.py - 后台任务管理器

实现异步后台命令执行（BackgroundManager）。
每个后台任务在独立的守护线程中运行，完成后通过通知队列报告结果。
支持按 ID 查询任务状态和批量获取完成通知。
"""

import subprocess
import threading
import uuid
from queue import Queue

from bootstrap import state


class BackgroundManager:
    """后台任务管理器，支持异步命令执行和状态查询"""

    def __init__(self):
        """初始化后台管理器"""
        self.tasks = {}
        self.notifications = Queue()

    def run(self, command: str, timeout: int = 120) -> str:
        """在后台线程中启动命令执行"""
        tid = str(uuid.uuid4())[:8]
        self.tasks[tid] = {"status": "running", "command": command, "result": None}
        threading.Thread(
            target=self._exec, args=(tid, command, timeout), daemon=True
        ).start()
        return f"Background task {tid} started: {command[:80]}"

    def _exec(self, tid: str, command: str, timeout: int):
        """后台任务执行函数（运行在独立线程中）"""
        try:
            r = subprocess.run(
                command, shell=True, cwd=state.WORKDIR,
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",  # S5: 显式 UTF-8
            )
            output = (r.stdout + r.stderr).strip()[:50000]
            self.tasks[tid].update({
                "status": "completed",
                "result": output or "(no output)",
            })
        except Exception as e:
            self.tasks[tid].update({"status": "error", "result": str(e)})
        self.notifications.put({
            "task_id": tid,
            "status": self.tasks[tid]["status"],
            "result": self.tasks[tid]["result"][:500],
        })

    def check(self, tid: str = None) -> str:
        """查询后台任务状态"""
        if tid:
            t = self.tasks.get(tid)
            return (
                f"[{t['status']}] {t.get('result') or '(running)'}"
                if t
                else f"Unknown: {tid}"
            )
        return (
            "\n".join(
                f"{k}: [{v['status']}] {v['command'][:60]}"
                for k, v in self.tasks.items()
            )
            or "No bg tasks."
        )

    def drain(self) -> list:
        """批量获取所有已完成的通知"""
        notifs = []
        while not self.notifications.empty():
            notifs.append(self.notifications.get_nowait())
        return notifs
