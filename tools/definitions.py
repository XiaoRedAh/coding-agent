"""
tools/definitions.py - 工具 JSON Schema 定义

定义所有可供 LLM 使用的工具的 JSON schema，包括名称、描述和输入参数格式。
这些定义会传递给 Anthropic API 的 tools 参数。
"""

from config import VALID_MSG_TYPES


def get_tool_definitions() -> list:
    """
    返回所有工具的 JSON schema 定义列表。

    Returns:
        工具定义列表，每个元素是包含 name、description、input_schema 的字典
    """
    return [
        # === 基础文件操作工具 ===
        {
            "name": "bash",
            "description": "Run a shell command.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file contents.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "edit_file",
            "description": "Replace exact text in file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },

        # === 待办事项工具 ===
        {
            "name": "TodoWrite",
            "description": "Update task tracking list.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                                "activeForm": {"type": "string"},
                            },
                            "required": ["content", "status", "activeForm"],
                        },
                    }
                },
                "required": ["items"],
            },
        },

        # === 子代理工具 ===
        {
            "name": "task",
            "description": "Spawn a subagent for isolated exploration or work.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "agent_type": {
                        "type": "string",
                        "enum": ["Explore", "general-purpose"],
                    },
                },
                "required": ["prompt"],
            },
        },

        # === 技能加载工具 ===
        {
            "name": "load_skill",
            "description": "Load specialized knowledge by name.",
            "input_schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },

        # === 上下文压缩工具 ===
        {
            "name": "compress",
            "description": "Manually compress conversation context.",
            "input_schema": {"type": "object", "properties": {}},
        },

        # === 后台任务工具 ===
        {
            "name": "background_run",
            "description": "Run command in background thread.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "integer"},
                },
                "required": ["command"],
            },
        },
        {
            "name": "check_background",
            "description": "Check background task status.",
            "input_schema": {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
            },
        },

        # === 持久化任务管理工具 ===
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

        # === 团队协作工具 ===
        {
            "name": "spawn_teammate",
            "description": "Spawn a persistent autonomous teammate.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["name", "role", "prompt"],
            },
        },
        {
            "name": "list_teammates",
            "description": "List all teammates.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "send_message",
            "description": "Send a message to a teammate.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "content": {"type": "string"},
                    "msg_type": {
                        "type": "string",
                        "enum": list(VALID_MSG_TYPES),
                    },
                },
                "required": ["to", "content"],
            },
        },
        {
            "name": "read_inbox",
            "description": "Read and drain the lead's inbox.",
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "broadcast",
            "description": "Send message to all teammates.",
            "input_schema": {
                "type": "object",
                "properties": {"content": {"type": "string"}},
                "required": ["content"],
            },
        },

        # === 关闭与计划审批工具 ===
        {
            "name": "shutdown_request",
            "description": "Request a teammate to shut down.",
            "input_schema": {
                "type": "object",
                "properties": {"teammate": {"type": "string"}},
                "required": ["teammate"],
            },
        },
        {
            "name": "plan_approval",
            "description": "Approve or reject a teammate's plan.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "request_id": {"type": "string"},
                    "approve": {"type": "boolean"},
                    "feedback": {"type": "string"},
                },
                "required": ["request_id", "approve"],
            },
        },

        # === 空闲与任务认领工具 ===
        {
            "name": "idle",
            "description": "Enter idle state.",
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
