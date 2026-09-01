"""单元测试：agents/task_queue.py"""
from agents.task_queue import AgentTaskQueue


class TestAgentTaskQueue:
    def test_empty_drain(self):
        q = AgentTaskQueue()
        notifications, in_flight = q.drain()
        assert notifications == []
        assert in_flight == 0

    def test_submit_and_drain(self):
        q = AgentTaskQueue()
        q.increment()
        q.submit("t1", "explore", "completed", "Found 5 files")
        notifications, in_flight = q.drain()
        assert len(notifications) == 1
        assert notifications[0]["task_id"] == "t1"
        assert notifications[0]["agent_type"] == "explore"
        assert in_flight == 0  # 已完成，无在途任务

    def test_drain_clears(self):
        q = AgentTaskQueue()
        q.increment()
        q.submit("t1", "general", "completed", "done")
        q.drain()
        notifications, _ = q.drain()
        assert notifications == []

    def test_multiple_items(self):
        q = AgentTaskQueue()
        q.increment()
        q.increment()
        q.submit("t1", "explore", "completed", "r1")
        q.submit("t2", "general", "error", "r2")
        notifications, in_flight = q.drain()
        assert len(notifications) == 2
        assert notifications[0]["task_id"] == "t1"
        assert notifications[1]["status"] == "error"
        assert in_flight == 0

    def test_fifo_order(self):
        q = AgentTaskQueue()
        for i in range(5):
            q.increment()
            q.submit(f"t{i}", "general", "completed", f"r{i}")
        notifications, _ = q.drain()
        assert [r["task_id"] for r in notifications] == ["t0", "t1", "t2", "t3", "t4"]

    def test_in_flight_count(self):
        """increment 增加 in_flight，submit 递减。"""
        q = AgentTaskQueue()
        q.increment()
        q.increment()
        q.increment()
        _, in_flight = q.drain()
        assert in_flight == 3
        q.submit("t1", "general", "completed", "done")
        _, in_flight = q.drain()
        assert in_flight == 2
        assert q.get_in_flight() == 2

    def test_in_flight_never_negative(self):
        """无 increment 的 submit 不会使 in_flight 变为负数。"""
        q = AgentTaskQueue()
        q.submit("t1", "general", "completed", "done")
        _, in_flight = q.drain()
        assert in_flight == 0

    def test_wait_and_drain_returns_after_submit(self):
        """wait_and_drain 在有通知后立即返回。"""
        import threading

        q = AgentTaskQueue()
        q.increment()

        def _submit_later():
            import time
            time.sleep(0.1)
            q.submit("t1", "explore", "completed", "result")

        t = threading.Thread(target=_submit_later)
        t.start()
        notifications, in_flight = q.wait_and_drain(timeout=5)
        t.join()
        assert len(notifications) == 1
        assert notifications[0]["result"] == "result"
        assert in_flight == 0
