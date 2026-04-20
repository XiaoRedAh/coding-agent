"""
agents/task_queue.py - 异步 Agent 任务通知队列

独立于 BackgroundManager 的通知机制，用于异步 SubAgent 结果回传。
主 Agent 在 query.py 的每轮循环中通过 drain() 接收完成通知。

对应 Claude Code 的 LocalAgentTask 系统（enqueueAgentNotification）。

通知格式：
{
    "task_id": str,       # 任务 ID
    "agent_type": str,    # Worker 类型
    "status": str,        # "completed" | "error"
    "result": str,        # 执行结果
}
"""

from queue import Queue, Empty
import threading


class AgentTaskQueue:
    """
    异步 Agent 任务的结果通知队列。

    支持追踪进行中的任务数量和阻塞等待：
    - submit(): Worker 启动时调用，count + 1
    - drain(): 返回已完成通知，同时返回剩余进行中的数量
    - wait_and_drain(): 阻塞等待直到有通知到达，然后返回所有通知
    """

    def __init__(self):
        self._results: Queue = Queue()
        self._in_flight: int = 0  # 进行中的任务计数
        self._lock = threading.Lock()
        self._event = threading.Event()  # 有新通知时 set()

    def submit(self, task_id: str, agent_type: str, status: str, result: str):
        """子 Agent 完成后提交结果，唤醒等待者"""
        with self._lock:
            self._results.put({
                "task_id": task_id,
                "agent_type": agent_type,
                "status": status,
                "result": result,
            })
            self._in_flight = max(0, self._in_flight - 1)
            self._event.set()  # 唤醒阻塞等待者

    def increment(self):
        """派发 Worker 时调用，计数 +1"""
        with self._lock:
            self._in_flight += 1

    def drain(self) -> tuple[list[dict], int]:
        """
        获取所有已完成的通知，同时返回剩余进行中的任务数量。

        Returns:
            (notifications, in_flight): 已完成的通知列表 + 仍在执行的任务数
        """
        with self._lock:
            notifications = []
            while not self._results.empty():
                notifications.append(self._results.get_nowait())

            # 更新 in_flight
            self._in_flight = max(0, self._in_flight)

            # 如果队列空了，清除事件
            if self._results.empty():
                self._event.clear()

            return notifications, self._in_flight

    def wait_and_drain(self, timeout: float = 120) -> tuple[list[dict], int]:
        """
        阻塞等待直到有通知到达，然后返回所有待处理的通知。

        用于 Coordinator 模式：当没有通知但还有任务在执行时，
        阻塞等待直到至少有一个 Worker 完成。

        Args:
            timeout: 最大等待时间（秒）

        Returns:
            (notifications, in_flight): 已完成的通知列表 + 仍在执行的任务数
        """
        # 等待事件（带超时）
        self._event.wait(timeout=timeout)

        # 不管超时与否，都尝试 drain
        return self.drain()

    def get_in_flight(self) -> int:
        """查询还有多少任务正在执行（不含已完成的）"""
        with self._lock:
            return self._in_flight
