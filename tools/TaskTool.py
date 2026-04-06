"""
tools/TaskTool.py - 持久化任务管理工具

提供任务的创建、查询、更新、列表和认领功能。
任务持久化到 .xiaoagent/tasks/ 目录（JSON 文件），支持依赖关系。
适合多步骤工作和团队协作中的任务分配。
"""

from bootstrap import state

DEFINITIONS = [
    {
        "name": "task_create",
        "description": (
            "Create a persistent task (saved to disk, survives restarts). "
            "Use for multi-step work or team task boards. "
            "Returns the created task with its ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Brief task title",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed requirements and success criteria (optional)",
                },
            },
            "required": ["subject"],
        },
    },
    {
        "name": "task_get",
        "description": "Get details of a specific task by ID (status, owner, dependencies).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_update",
        "description": (
            "Update a task's status or dependencies. "
            "Only specified fields are changed (merge, not overwrite). "
            "Setting status to 'completed' auto-unblocks dependent tasks. "
            "Setting status to 'deleted' permanently removes the task."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "completed", "deleted"],
                    "description": "New status",
                },
                "add_blocked_by": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Task IDs that must complete before this task can start",
                },
                "remove_blocked_by": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Remove dependency on these task IDs",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "task_list",
        "description": "List all tasks with status, owner, and dependency info.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "claim_task",
        "description": "Claim an unclaimed task (assign to yourself and set to in_progress).",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "integer", "description": "Task ID to claim"},
            },
            "required": ["task_id"],
        },
    },
]


def get_handlers() -> dict:
    return {
        "task_create":  lambda **kw: state.task_mgr.create(kw["subject"], kw.get("description", "")),
        "task_get":     lambda **kw: state.task_mgr.get(kw["task_id"]),
        "task_update":  lambda **kw: state.task_mgr.update(kw["task_id"], kw.get("status"), kw.get("add_blocked_by"), kw.get("remove_blocked_by")),
        "task_list":    lambda **kw: state.task_mgr.list_all(),
        "claim_task":   lambda **kw: state.task_mgr.claim(kw["task_id"], "lead"),
    }
