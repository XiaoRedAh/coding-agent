"""
tools/registry.py - 工具注册表

将工具名称映射到对应的处理函数，以及提供工具定义列表。
使用延迟导入避免循环依赖问题。
"""

import json

from tools.base import run_bash, run_read, run_write, run_edit
from tools.definitions import get_tool_definitions


def get_tool_handlers(todo, skills, task_mgr, bg, bus, team) -> dict:
    """
    构建工具处理函数映射表。

    通过依赖注入的方式接收所有全局单例实例，避免循环导入。

    Args:
        todo: TodoManager 实例
        skills: SkillLoader 实例
        task_mgr: TaskManager 实例
        bg: BackgroundManager 实例
        bus: MessageBus 实例
        team: TeammateManager 实例
    Returns:
        字典，key 为工具名称，value 为对应的 lambda 处理函数
    """
    # 延迟导入，避免循环依赖
    from agents.subagent import run_subagent
    from communication.protocols import handle_shutdown_request, handle_plan_review

    return {
        "bash":             lambda **kw: run_bash(kw["command"]),
        "read_file":        lambda **kw: run_read(kw["path"], kw.get("limit")),
        "write_file":       lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file":        lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
        "TodoWrite":        lambda **kw: todo.update(kw["items"]),
        "task":             lambda **kw: run_subagent(kw["prompt"], kw.get("agent_type", "Explore")),
        "load_skill":       lambda **kw: skills.load(kw["name"]),
        "compress":         lambda **kw: "Compressing...",
        "background_run":   lambda **kw: bg.run(kw["command"], kw.get("timeout", 120)),
        "check_background": lambda **kw: bg.check(kw.get("task_id")),
        "task_create":      lambda **kw: task_mgr.create(kw["subject"], kw.get("description", "")),
        "task_get":         lambda **kw: task_mgr.get(kw["task_id"]),
        "task_update":      lambda **kw: task_mgr.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("remove_blocked_by")),
        "task_list":        lambda **kw: task_mgr.list_all(),
        "spawn_teammate":   lambda **kw: team.spawn(kw["name"], kw["role"], kw["prompt"]),
        "list_teammates":   lambda **kw: team.list_all(),
        "send_message":     lambda **kw: bus.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
        "read_inbox":       lambda **kw: json.dumps(bus.read_inbox("lead"), indent=2),
        "broadcast":        lambda **kw: bus.broadcast("lead", kw["content"], team.member_names()),
        "shutdown_request": lambda **kw: handle_shutdown_request(kw["teammate"], bus),
        "plan_approval":    lambda **kw: handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", ""), bus),
        "idle":             lambda **kw: "Lead does not idle.",
        "claim_task":       lambda **kw: task_mgr.claim(kw["task_id"], "lead"),
    }
