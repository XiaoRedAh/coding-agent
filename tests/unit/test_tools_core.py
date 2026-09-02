"""Unit tests for core tools: FileRead / FileWrite / ListFiles / Todo / Task / Skill.

覆盖正常、异常（错误输入/路径逃逸/不存在）、边界（截断/上限/空值）场景。
GrepSearchTool 依赖系统 grep（Windows 无原生 grep），其测试见 test_grep_tool.py。
"""

import json
import queue as queue_mod

import pytest

from tools import FileReadTool, FileWriteTool, ListFilesTool, TodoTool, SkillTool


@pytest.fixture
def tool_workdir(tmp_path, monkeypatch):
    """隔离工具的工作目录（S2 后只需 patch runtime.state.WORKDIR 一处）。"""
    monkeypatch.setattr("runtime.state.WORKDIR", tmp_path)
    return tmp_path


# ──────────────────────────────────────────────
#  FileReadTool
# ──────────────────────────────────────────────

class TestFileReadTool:
    def test_read_with_line_numbers(self, tool_workdir):
        f = tool_workdir / "a.txt"
        f.write_text("first\nsecond\nthird", encoding="utf-8")
        out = FileReadTool.handle("a.txt")
        assert "   1 | first" in out
        assert "   2 | second" in out
        assert "   3 | third" in out

    def test_read_limit_truncates(self, tool_workdir):
        f = tool_workdir / "long.txt"
        f.write_text("\n".join(f"line{i}" for i in range(10)), encoding="utf-8")
        out = FileReadTool.handle("long.txt", limit=3)
        assert "line0" in out
        assert "line9" not in out
        assert "... (7 more lines)" in out

    def test_read_nonexistent_returns_error(self, tool_workdir):
        out = FileReadTool.handle("no_such_file.txt")
        assert out.startswith("Error reading file:")
        assert out.ok is False
        assert out.error == "not_found"

    def test_read_path_escape_blocked(self, tool_workdir):
        out = FileReadTool.handle("../../etc/passwd")
        assert out.startswith("Error reading file:")
        assert "escapes workspace" in out
        assert out.error == "path_escape"

    def test_read_utf8_chinese(self, tool_workdir):
        f = tool_workdir / "cn.txt"
        f.write_text("你好，世界", encoding="utf-8")
        out = FileReadTool.handle("cn.txt")
        assert "你好，世界" in out

    def test_read_empty_file(self, tool_workdir):
        (tool_workdir / "empty.txt").write_text("", encoding="utf-8")
        out = FileReadTool.handle("empty.txt")
        assert out == ""  # splitlines() 为空列表 → join 为空串


# ──────────────────────────────────────────────
#  FileWriteTool
# ──────────────────────────────────────────────

class TestFileWriteTool:
    def test_write_creates_file_with_parents(self, tool_workdir):
        out = FileWriteTool.handle("src/deep/nested/mod.py", "print('hi')")
        assert out.startswith("Successfully wrote to")
        content = (tool_workdir / "src/deep/nested/mod.py").read_text(encoding="utf-8")
        assert content == "print('hi')"

    def test_write_overwrites_existing(self, tool_workdir):
        f = tool_workdir / "f.txt"
        f.write_text("old", encoding="utf-8")
        FileWriteTool.handle("f.txt", "new content")
        assert f.read_text(encoding="utf-8") == "new content"

    def test_write_reports_byte_count(self, tool_workdir):
        out = FileWriteTool.handle("f.txt", "12345")
        assert "(5 bytes)" in out

    def test_write_path_escape_blocked(self, tool_workdir):
        out = FileWriteTool.handle("../outside.txt", "x")
        assert out.startswith("Error writing file:")
        assert "escapes workspace" in out
        assert out.error == "path_escape"

    def test_write_utf8_chinese(self, tool_workdir):
        FileWriteTool.handle("cn.txt", "中文内容")
        assert (tool_workdir / "cn.txt").read_text(encoding="utf-8") == "中文内容"


# ──────────────────────────────────────────────
#  ListFilesTool
# ──────────────────────────────────────────────

class TestListFilesTool:
    def test_glob_match(self, tool_workdir):
        (tool_workdir / "a.py").write_text("x", encoding="utf-8")
        (tool_workdir / "b.txt").write_text("x", encoding="utf-8")
        out = ListFilesTool.handle("*.py")
        assert "a.py" in out
        assert "b.txt" not in out

    def test_recursive_glob(self, tool_workdir):
        (tool_workdir / "src").mkdir()
        (tool_workdir / "src" / "mod.py").write_text("x", encoding="utf-8")
        out = ListFilesTool.handle("**/*.py")
        assert "mod.py" in out

    def test_no_match(self, tool_workdir):
        out = ListFilesTool.handle("*.nonexistent")
        assert out == "No files found matching pattern."

    def test_sorted_by_mtime_newest_first(self, tool_workdir):
        import os
        import time
        old = tool_workdir / "old.py"
        old.write_text("x", encoding="utf-8")
        time.sleep(0.02)
        new = tool_workdir / "new.py"
        new.write_text("x", encoding="utf-8")
        out = ListFilesTool.handle("*.py")
        assert out.index("new.py") < out.index("old.py")

    def test_directories_excluded(self, tool_workdir):
        (tool_workdir / "subdir").mkdir()
        (tool_workdir / "file.py").write_text("x", encoding="utf-8")
        out = ListFilesTool.handle("*")
        assert "file.py" in out
        # 目录被过滤，只保留文件
        lines = [l for l in out.splitlines() if l.strip()]
        assert all("subdir" not in l or "file" in l for l in lines)

    def test_custom_path_arg(self, tool_workdir):
        sub = tool_workdir / "sub"
        sub.mkdir()
        (sub / "inner.py").write_text("x", encoding="utf-8")
        out = ListFilesTool.handle("*.py", path=str(sub))
        assert "inner.py" in out


# ──────────────────────────────────────────────
#  TodoTool（TodoManager）
# ──────────────────────────────────────────────

class TestTodoManager:
    def _item(self, content="task", status="pending", af="Doing task"):
        return {"content": content, "status": status, "activeForm": af}

    def test_update_and_render(self):
        m = TodoTool.TodoManager()
        out = m.update([self._item("write code"), self._item("test", "completed", "Testing")])
        assert "[ ] write code" in out
        assert "[x] test" in out
        assert "(1/2 completed)" in out

    def test_render_in_progress_marker(self):
        m = TodoTool.TodoManager()
        out = m.update([self._item("work", "in_progress", "Working hard")])
        assert "[>] work <- Working hard" in out

    def test_empty_list(self):
        m = TodoTool.TodoManager()
        assert m.update([]) == "No todos."

    def test_missing_content_raises(self):
        m = TodoTool.TodoManager()
        with pytest.raises(ValueError, match="content required"):
            m.update([{"status": "pending", "activeForm": "x"}])

    def test_invalid_status_raises(self):
        m = TodoTool.TodoManager()
        with pytest.raises(ValueError, match="invalid status"):
            m.update([self._item(status="bogus")])

    def test_multiple_in_progress_raises(self):
        m = TodoTool.TodoManager()
        with pytest.raises(ValueError, match="one in_progress"):
            m.update([self._item("a", "in_progress"), self._item("b", "in_progress")])

    def test_over_20_items_raises(self):
        m = TodoTool.TodoManager()
        with pytest.raises(ValueError, match="Max 20"):
            m.update([self._item(f"t{i}") for i in range(21)])

    def test_boundary_exactly_20_ok(self):
        m = TodoTool.TodoManager()
        out = m.update([self._item(f"t{i}") for i in range(20)])
        assert "(0/20 completed)" in out

    def test_has_open_items(self):
        m = TodoTool.TodoManager()
        assert not m.has_open_items()
        m.update([self._item("a"), self._item("b", "completed")])
        assert m.has_open_items()
        m.update([self._item("a", "completed"), self._item("b", "completed")])
        assert not m.has_open_items()

    def test_full_replacement_semantics(self):
        m = TodoTool.TodoManager()
        m.update([self._item("old1"), self._item("old2")])
        m.update([self._item("new1")])
        assert len(m.items) == 1
        assert m.items[0]["content"] == "new1"


# ──────────────────────────────────────────────
#  TaskManager（services/tasks.py）+ TaskTool 接线
# ──────────────────────────────────────────────

@pytest.fixture
def task_mgr(tmp_path, monkeypatch):
    from services.tasks import TaskManager
    tasks_dir = tmp_path / ".xiaoagent" / "tasks"
    monkeypatch.setattr("runtime.state.TASKS_DIR", tasks_dir)
    return TaskManager()


class TestTaskManager:
    def test_create_assigns_incrementing_ids(self, task_mgr):
        t1 = json.loads(task_mgr.create("first task", "desc"))
        t2 = json.loads(task_mgr.create("second task"))
        assert t1["id"] == 1
        assert t2["id"] == 2
        assert t1["status"] == "pending"
        assert t1["blockedBy"] == []

    def test_get_returns_task(self, task_mgr):
        task_mgr.create("my task")
        t = json.loads(task_mgr.get(1))
        assert t["subject"] == "my task"

    def test_get_nonexistent_raises(self, task_mgr):
        with pytest.raises(ValueError, match="not found"):
            task_mgr.get(999)

    def test_update_status(self, task_mgr):
        task_mgr.create("t")
        t = json.loads(task_mgr.update(1, status="in_progress"))
        assert t["status"] == "in_progress"

    def test_add_and_remove_blocked_by(self, task_mgr):
        task_mgr.create("blocker")
        task_mgr.create("blocked")
        t = json.loads(task_mgr.update(2, add_blocked_by=[1]))
        assert t["blockedBy"] == [1]
        t = json.loads(task_mgr.update(2, remove_blocked_by=[1]))
        assert t["blockedBy"] == []

    def test_completion_unblocks_dependents(self, task_mgr):
        task_mgr.create("blocker")
        task_mgr.create("dependent")
        task_mgr.update(2, add_blocked_by=[1])
        task_mgr.update(1, status="completed")
        t = json.loads(task_mgr.get(2))
        assert t["blockedBy"] == []

    def test_delete_removes_file(self, task_mgr, tmp_path, monkeypatch):
        import runtime.state as st
        task_mgr.create("temp")
        out = task_mgr.update(1, status="deleted")
        assert out == "Task 1 deleted"
        assert not (st.TASKS_DIR / "task_1.json").exists()

    def test_list_all_empty(self, task_mgr):
        assert task_mgr.list_all() == "No tasks."

    def test_list_all_format(self, task_mgr):
        task_mgr.create("alpha")
        task_mgr.create("beta")
        task_mgr.update(2, add_blocked_by=[1])
        out = task_mgr.list_all()
        assert "[ ] #1: alpha" in out
        assert "blocked by: [1]" in out

    def test_claim_sets_owner_and_status(self, task_mgr):
        task_mgr.create("job")
        out = task_mgr.claim(1, "alice")
        assert out == "Claimed task #1 for alice"
        t = json.loads(task_mgr.get(1))
        assert t["owner"] == "alice"
        assert t["status"] == "in_progress"

    def test_persistence_across_instances(self, task_mgr, tmp_path, monkeypatch):
        task_mgr.create("survives")
        # 新实例应能读到旧实例写入的任务（动态读取 state.TASKS_DIR）
        mgr2 = type(task_mgr)()
        t = json.loads(mgr2.get(1))
        assert t["subject"] == "survives"


class TestTaskToolWiring:
    def test_handlers_dispatch_to_state_task_mgr(self, monkeypatch, task_mgr):
        """TaskTool.get_handlers 的 handler 应转发到 state.task_mgr。"""
        from runtime import state
        from tools import TaskTool
        monkeypatch.setattr(state, "task_mgr", task_mgr)

        handlers = TaskTool.get_handlers()
        assert set(handlers.keys()) == {
            "task_create", "task_get", "task_update", "task_list", "claim_task"}

        created = json.loads(handlers["task_create"](subject="wired", description="d"))
        assert created["subject"] == "wired"
        fetched = json.loads(handlers["task_get"](task_id=created["id"]))
        assert fetched["id"] == created["id"]
        claimed = handlers["claim_task"](task_id=created["id"])
        assert "Claimed task" in claimed


# ──────────────────────────────────────────────
#  SkillTool
# ──────────────────────────────────────────────

class TestSkillTool:
    @pytest.fixture
    def skill_env(self, tmp_path, monkeypatch):
        from skills.loader import SkillLoader
        from runtime import state
        skill_dir = tmp_path / "skills"
        (skill_dir / "demo").mkdir(parents=True)
        (skill_dir / "demo" / "SKILL.md").write_text(
            "---\nname: demo\ndescription: Demo skill\n---\n# Demo\nArgs: $ARGUMENTS",
            encoding="utf-8",
        )
        loader = SkillLoader(skill_dir)
        monkeypatch.setattr(state, "skills", loader)
        return loader

    def test_load_existing_skill(self, skill_env):
        from tools import SkillTool
        out = SkillTool.handle("demo", "my-arg")
        assert "<skill name=\"demo\">" in out
        assert "Args: my-arg" in out

    def test_load_unknown_skill_returns_error(self, skill_env):
        from tools import SkillTool
        out = SkillTool.handle("nonexistent")
        assert out.startswith("Error: Unknown skill")
        assert "demo" in out  # 列出可用技能
        assert out.ok is False
        assert out.error == "unknown_skill"

    def test_definition_schema(self):
        from tools import SkillTool
        d = SkillTool.DEFINITION
        assert d["name"] == "load_skill"
        assert d["input_schema"]["required"] == ["name"]


# ──────────────────────────────────────────────
#  工具注册表（tools/__init__.py）
# ──────────────────────────────────────────────

class TestToolRegistry:
    def test_all_builtin_tools_registered(self, monkeypatch):
        """内置工具的定义与 handler 应完整注册（MCP 未连接时）。"""
        from runtime import state
        from tools import get_all_definitions, get_all_handlers
        monkeypatch.setattr(state, "mcp", None)
        monkeypatch.setattr(state, "todo", TodoTool.TodoManager())

        defs = get_all_definitions()
        names = {d["name"] for d in defs}
        expected = {
            "read_file", "write_file", "edit_file", "list_files",
            "grep_search", "run_shell", "agent", "load_skill",
            "TodoWrite", "task_create", "task_get", "task_update",
            "task_list", "claim_task",
        }
        assert expected <= names

        handlers = get_all_handlers()
        assert expected <= set(handlers.keys())

    def test_definitions_have_valid_schema(self, monkeypatch):
        from runtime import state
        from tools import get_all_definitions
        monkeypatch.setattr(state, "mcp", None)
        for d in get_all_definitions():
            assert d["name"], "definition must have a name"
            assert "description" in d
            assert d["input_schema"]["type"] == "object"
