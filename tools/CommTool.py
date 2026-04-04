"""
tools/CommTool.py - 团队通信工具

提供 Swarm Team 模式的通信功能：
- spawn_teammate: 创��持久化队友（独立线程，有自己的工具集和上下文）
- list_teammates: 查看所有队友的状态
- send_message: 向队友发消息（触发队友处理）
- read_inbox: 读取主 Agent 的收件箱（队友发来的消息）
- broadcast: 向所有队友广播消息
- shutdown_teammate: 请求队友关闭

在 CC 中，Team 相关功能集成在 AgentTool（spawn）和 SendMessageTool（通信）中。
当前项目将它们作为独立工具注册，与 AgentTool（子Agent）分离。
"""

import json
import uuid

from bootstrap import state

# === 协议状态追踪 ===
shutdown_requests = {}

DEFINITIONS = [
    {
        "name": "spawn_teammate",
        "description": (
            "Create a persistent autonomous teammate that runs in a background thread. "
            "Teammates have their own tools (read/write/edit/shell) and can communicate "
            "with you and other teammates via messages. Use for long-running collaborative tasks. "
            "The teammate will work independently and report back via your inbox."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique name for the teammate (used for messaging)",
                },
                "role": {
                    "type": "string",
                    "description": "Role description (e.g. 'frontend developer', 'test writer')",
                },
                "prompt": {
                    "type": "string",
                    "description": "Initial task instructions for the teammate",
                },
            },
            "required": ["name", "role", "prompt"],
        },
    },
    {
        "name": "list_teammates",
        "description": "List all teammates and their current status (working/idle/shutdown).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_message",
        "description": (
            "Send a message to a specific teammate by name. "
            "If the teammate is idle, this will wake them up to process the message. "
            "Use this to assign new tasks, provide feedback, or coordinate work."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Teammate name to send message to",
                },
                "content": {
                    "type": "string",
                    "description": "Message content",
                },
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "read_inbox",
        "description": (
            "Read messages from your inbox (sent by teammates). "
            "Messages are drained after reading (each message is read only once)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "broadcast",
        "description": "Send a message to ALL teammates at once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Message to broadcast",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "shutdown_teammate",
        "description": "Request a specific teammate to shut down gracefully.",
        "input_schema": {
            "type": "object",
            "properties": {
                "teammate": {
                    "type": "string",
                    "description": "Name of teammate to shut down",
                },
            },
            "required": ["teammate"],
        },
    },
]


def _handle_shutdown(teammate: str) -> str:
    """发起关闭请求"""
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    state.bus.send(
        "lead", teammate, "Please shut down.",
        "shutdown_request", {"request_id": req_id},
    )
    return f"Shutdown request {req_id} sent to '{teammate}'"


def get_handlers() -> dict:
    """返回通信工具的处理函数映射"""
    return {
        "spawn_teammate":    lambda **kw: state.team.spawn(kw["name"], kw["role"], kw["prompt"]),
        "list_teammates":    lambda **kw: state.team.list_all(),
        "send_message":      lambda **kw: state.bus.send("lead", kw["to"], kw["content"]),
        "read_inbox":        lambda **kw: json.dumps(state.bus.read_inbox("lead"), indent=2),
        "broadcast":         lambda **kw: state.bus.broadcast("lead", kw["content"], state.team.member_names()),
        "shutdown_teammate":  lambda **kw: _handle_shutdown(kw["teammate"]),
    }
