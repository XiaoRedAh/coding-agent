"""计划引导（plan-and-solve 落地）测试。

覆盖：
  A. base.md 计划引导注入（触发/结束信号/换任务/与委托的关系）
  B. reminder 增强：带清单内容 + 阈值来自 config
  C. 主 Agent 专属工具排除（TodoWrite / run_workflow 不进子 Agent）
  D. TodoTool 基础行为回归（校验 / 渲染 / 进度）
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import runtime.state as st
from tools.TodoTool import TodoManager


# ──────────────────────────────────────────────
#  A. 计划引导注入
# ──────────────────────────────────────────────

class TestPlanningGuidance:
    def test_base_md_contains_planning_section(self):
        from prompts.loader import PromptLoader
        base = PromptLoader(user_dir=Path("nonexistent_user_dir_xyz")).load("base.md")
        assert "Planning (todo list)" in base
        assert "create a plan FIRST with TodoWrite" in base
        # 结束信号：全部完成即收尾
        assert "summarize results and finish" in base
        # 换任务重写清单
        assert "replace the todo list" in base
        # 与委托的关系说明（WHAT vs HOW，防两段提示词打架）
        assert "WHAT to do" in base and "HOW each step runs" in base
        # 简单任务跳过
        assert "skip the todo list" in base

    def test_planning_in_static_block(self, tmp_workdir, monkeypatch):
        """计划引导在静态区（可被 prompt cache）。"""
        from context.prompt import build_system_prompt

        monkeypatch.setattr(st, "memory", None)
        monkeypatch.setattr(st, "skills", None)
        blocks = build_system_prompt()
        assert "Planning (todo list)" in blocks[0]["text"]


# ──────────────────────────────────────────────
#  B. reminder 增强
# ──────────────────────────────────────────────

class TestTodoReminder:
    def _make_hooks(self):
        from context.compact import TokenTracker, CircuitBreaker
        from agents.session import _MainLoopHooks
        return _MainLoopHooks(TokenTracker(), CircuitBreaker(), {})

    def test_reminder_contains_list_content(self, monkeypatch):
        """reminder 附带当前清单内容（LLM 无需翻上下文考古）。"""
        mgr = TodoManager()
        mgr.update([
            {"content": "step 1", "status": "completed", "activeForm": "doing 1"},
            {"content": "step 2", "status": "in_progress", "activeForm": "doing 2"},
        ])
        monkeypatch.setattr(st, "todo", mgr)

        hooks = self._make_hooks()
        hooks.rounds_without_todo = 5  # 已超过提醒阈值
        tool_msg = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}
        ctx = SimpleNamespace(turn_count=1, max_turns=10)
        hooks.post_tools(ctx, [], tool_msg)

        reminders = [b for b in tool_msg["content"] if b.get("type") == "text"]
        assert len(reminders) == 1
        text = reminders[0]["text"]
        assert "Update your todos" in text
        assert "step 2" in text          # 清单内容附带了
        assert "1/2 completed" in text

    def test_reminder_threshold_from_config(self):
        """阈值来自 config（tools.todo_reminder_rounds），不再硬编码。"""
        from runtime.state import settings
        assert settings.tools.todo_reminder_rounds == 3

    def test_no_reminder_when_all_done(self, monkeypatch):
        """全部完成时不提醒。"""
        mgr = TodoManager()
        mgr.update([{"content": "only", "status": "completed", "activeForm": "x"}])
        monkeypatch.setattr(st, "todo", mgr)

        hooks = self._make_hooks()
        hooks.rounds_without_todo = 10
        tool_msg = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}
        ctx = SimpleNamespace(turn_count=1, max_turns=10)
        hooks.post_tools(ctx, [], tool_msg)
        assert not [b for b in tool_msg["content"] if b.get("type") == "text"]

    def test_no_reminder_below_threshold(self, monkeypatch):
        """未到阈值不提醒。"""
        mgr = TodoManager()
        mgr.update([{"content": "a", "status": "pending", "activeForm": "x"}])
        monkeypatch.setattr(st, "todo", mgr)

        hooks = self._make_hooks()
        hooks.rounds_without_todo = 1  # < 3
        tool_msg = {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}
        ctx = SimpleNamespace(turn_count=1, max_turns=10)
        hooks.post_tools(ctx, [], tool_msg)
        assert not [b for b in tool_msg["content"] if b.get("type") == "text"]


# ──────────────────────────────────────────────
#  C. 主 Agent 专属工具排除
# ──────────────────────────────────────────────

class TestMainAgentOnlyTools:
    def test_todowrite_excluded_from_subagents(self):
        """自定义 YAML 声明 TodoWrite 也会被剔除（防清单覆写）。"""
        from agents.definitions import get_filtered_tools

        defs, handlers = get_filtered_tools(frozenset({
            "read_file", "write_file", "TodoWrite",
        }))
        names = [d["name"] for d in defs]
        assert "TodoWrite" not in names
        assert "TodoWrite" not in handlers
        assert "read_file" in names  # 其余工具不受影响

    def test_run_workflow_excluded_from_subagents(self):
        """run_workflow 被剔除（防 workflow 嵌套递归）。"""
        from agents.definitions import get_filtered_tools

        defs, handlers = get_filtered_tools(frozenset({
            "read_file", "run_workflow",
        }))
        assert "run_workflow" not in [d["name"] for d in defs]
        assert "run_workflow" not in handlers

    def test_builtin_agents_unaffected(self):
        """内置 agent 的常规工具不受排除影响。"""
        from agents.definitions import get_filtered_tools

        defs, _ = get_filtered_tools(frozenset({
            "read_file", "write_file", "edit_file", "run_shell",
        }))
        assert len(defs) == 4


# ──────────────────────────────────────────────
#  D. TodoTool 基础行为回归
# ──────────────────────────────────────────────

class TestTodoManagerRegression:
    def test_update_validates(self):
        mgr = TodoManager()
        with pytest.raises(ValueError):
            mgr.update([{"content": "", "status": "pending", "activeForm": "x"}])
        with pytest.raises(ValueError):
            mgr.update([{"content": "a", "status": "bogus", "activeForm": "x"}])
        with pytest.raises(ValueError):
            mgr.update([
                {"content": "a", "status": "in_progress", "activeForm": "x"},
                {"content": "b", "status": "in_progress", "activeForm": "y"},
            ])

    def test_render_shows_progress(self):
        mgr = TodoManager()
        out = mgr.update([
            {"content": "a", "status": "completed", "activeForm": "x"},
            {"content": "b", "status": "in_progress", "activeForm": "y"},
            {"content": "c", "status": "pending", "activeForm": "z"},
        ])
        assert "[x] a" in out and "[>] b" in out and "[ ] c" in out
        assert "1/3 completed" in out

    def test_has_open_items(self):
        mgr = TodoManager()
        assert not mgr.has_open_items()
        mgr.update([{"content": "a", "status": "completed", "activeForm": "x"}])
        assert not mgr.has_open_items()
        mgr.update([{"content": "a", "status": "pending", "activeForm": "x"}])
        assert mgr.has_open_items()
