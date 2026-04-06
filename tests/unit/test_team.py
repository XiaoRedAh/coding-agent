"""单元测试：agents/team.py（TeammateManager 的配置/状态管理，不涉及 LLM）"""
import json
import pytest
from unittest.mock import MagicMock
import agents.team as team_module


class TestTeammateManager:
    def _make_manager(self, tmp_workdir, monkeypatch):
        """Create a TeammateManager with paths redirected to tmp_workdir."""
        team_dir = tmp_workdir / ".xiaoagent" / "team"
        team_dir.mkdir(parents=True, exist_ok=True)
        tasks_dir = tmp_workdir / ".xiaoagent" / "tasks"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        # Patch the module-level constants that __init__ reads
        monkeypatch.setattr(team_module, "TEAM_DIR", team_dir)
        monkeypatch.setattr(team_module, "TASKS_DIR", tasks_dir)

        from agents.team import TeammateManager
        bus = MagicMock()
        task_mgr = MagicMock()
        return TeammateManager(bus, task_mgr)

    def test_init_creates_config(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        assert mgr.config["team_name"] == "default"
        assert mgr.config["members"] == []

    def test_find_none(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        assert mgr._find("nonexistent") is None

    def test_list_all_empty(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        assert "No teammates" in mgr.list_all()

    def test_member_names_empty(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        assert mgr.member_names() == []

    def test_spawn_adds_member(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        result = mgr.spawn("researcher", "code search", "find TODOs", "explore")
        assert "Spawned" in result
        assert mgr._find("researcher") is not None
        assert mgr._find("researcher")["status"] == "working"

    def test_spawn_duplicate_working_fails(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        mgr.spawn("worker", "dev", "code", "general")
        result = mgr.spawn("worker", "dev", "more code", "general")
        assert "Error" in result

    def test_spawn_idle_reactivates(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        mgr.spawn("worker", "dev", "code", "general")
        mgr._set_status("worker", "idle")
        result = mgr.spawn("worker", "dev", "new task", "general")
        assert "Spawned" in result

    def test_set_status(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        mgr.spawn("worker", "dev", "code", "general")
        mgr._set_status("worker", "idle")
        assert mgr._find("worker")["status"] == "idle"

    def test_config_persistence(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        mgr.spawn("researcher", "search", "find bugs", "explore")
        config = json.loads(mgr.config_path.read_text())
        assert len(config["members"]) == 1
        assert config["members"][0]["name"] == "researcher"

    def test_list_all_with_members(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        mgr.spawn("alice", "frontend", "build UI", "general")
        mgr.spawn("bob", "backend", "build API", "general")
        listing = mgr.list_all()
        assert "alice" in listing
        assert "bob" in listing

    def test_build_system_prompt(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        import threading
        monkeypatch.setattr(threading, "Thread", lambda **kw: MagicMock())
        mgr.spawn("alice", "dev", "code", "general")
        mgr.spawn("bob", "test", "test", "general")
        prompt = mgr._build_system_prompt("alice", "dev")
        assert "alice" in prompt
        assert "bob" in prompt
        assert "send_message" in prompt

    def test_build_teammate_tools(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        defs, handlers = mgr._build_teammate_tools("general")
        tool_names = [d["name"] for d in defs]
        assert "send_message" in tool_names
        assert "idle" in tool_names

    def test_build_teammate_tools_explore(self, tmp_workdir, monkeypatch):
        mgr = self._make_manager(tmp_workdir, monkeypatch)
        defs, handlers = mgr._build_teammate_tools("explore")
        tool_names = [d["name"] for d in defs]
        assert "write_file" not in tool_names
        assert "read_file" in tool_names
