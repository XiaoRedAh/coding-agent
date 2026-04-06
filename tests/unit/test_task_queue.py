"""单元测试：agents/task_queue.py"""
from agents.task_queue import AgentTaskQueue


class TestAgentTaskQueue:
    def test_empty_drain(self):
        q = AgentTaskQueue()
        assert q.drain() == []

    def test_submit_and_drain(self):
        q = AgentTaskQueue()
        q.submit("t1", "explore", "completed", "Found 5 files")
        results = q.drain()
        assert len(results) == 1
        assert results[0]["task_id"] == "t1"
        assert results[0]["agent_type"] == "explore"

    def test_drain_clears(self):
        q = AgentTaskQueue()
        q.submit("t1", "general", "completed", "done")
        q.drain()
        assert q.drain() == []

    def test_multiple_items(self):
        q = AgentTaskQueue()
        q.submit("t1", "explore", "completed", "r1")
        q.submit("t2", "general", "error", "r2")
        results = q.drain()
        assert len(results) == 2
        assert results[0]["task_id"] == "t1"
        assert results[1]["status"] == "error"

    def test_fifo_order(self):
        q = AgentTaskQueue()
        for i in range(5):
            q.submit(f"t{i}", "general", "completed", f"r{i}")
        results = q.drain()
        assert [r["task_id"] for r in results] == ["t0", "t1", "t2", "t3", "t4"]
