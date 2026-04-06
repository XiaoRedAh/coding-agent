"""
agents/task_queue.py - 异步 Agent 任务通知队列

独立于 BackgroundManager 的通知机制，用于异步 SubAgent 结果回传。
主 Agent 在 query.py 的每轮循环中通过 drain() 接收完成通知。

对应 Claude Code 的 LocalAgentTask 系统（enqueueAgentNotification）。
"""

from queue import Queue


class AgentTaskQueue:
    """异步 Agent 任务的结果通知队列"""

    def __init__(self):
        self._results: Queue = Queue()

    def submit(self, task_id: str, agent_type: str, status: str, result: str):
        """子 Agent 完成后提交结果"""
        self._results.put({
            "task_id": task_id,
            "agent_type": agent_type,
            "status": status,
            "result": result,
        })

    def drain(self) -> list[dict]:
        """获取所有待处理的结果（清空队列）"""
        results = []
        while not self._results.empty():
            results.append(self._results.get_nowait())
        return results
