"""
tools/TaskTool.py - 持久化任务管理工具

提供任务的创建、查询、更新、列表和认领功能。
底层使用 services/tasks.py 的 TaskManager。
"""

from bootstrap import state

DEFINITIONS = [
    {
        "name": "task_create",
        "description": "Create a persistent file task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "task_get",
        "description": "Get task details by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "task_update",
        "description": "Update task status or dependencies.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                },
                "add_blocked_by": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "remove_blocked_by": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_list",
        "description": "List all tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "claim_task",
        "description": "Claim a task from the board.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


def get_handlers() -> dict:
    """返回任务相关工具的处理函数映射"""
    return {
        "task_create":  lambda **kw: state.task_mgr.create(kw["subject"], kw.get("description", "")),
        "task_get":     lambda **kw: state.task_mgr.get(kw["task_id"]),
        "task_update":  lambda **kw: state.task_mgr.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("remove_blocked_by")),
        "task_list":    lambda **kw: state.task_mgr.list_all(),
        "claim_task":   lambda **kw: state.task_mgr.claim(kw["task_id"], "lead"),
    }
