"""
tools/CommTool.py - 团队通信工具

提供 Swarm Team 模式的通信功能。
队友创建通过 AgentTool（name 参数），本模块只负责通信和管理。
"""

import json
import uuid

from bootstrap import state

shutdown_requests = {}

DEFINITIONS = [
    {
        "name": "list_teammates",
        "description": (
            "List all teammates and their current status. "
            "Statuses: 'working' (executing task), 'idle' (waiting for new work), "
            "'shutdown' (terminated). Create teammates via agent(name=...)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "send_message",
        "description": (
            "Send a message to a teammate by name. "
            "If the teammate is idle, this wakes them up to process the message. "
            "Use to assign new tasks, provide feedback, or coordinate work. "
            "Teammates are created via agent(name=...). "
            "Use 'lead' as recipient to message the main agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient: teammate name (e.g. 'researcher') or 'lead'",
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
            "Read messages from your inbox sent by teammates. "
            "Messages are consumed after reading (each read only once). "
            "Returns empty list if no new messages."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "broadcast",
        "description": "Send a message to ALL active teammates at once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Message to broadcast"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "shutdown_teammate",
        "description": (
            "Request a teammate to shut down gracefully. "
            "The teammate finishes current work, then exits. "
            "Use list_teammates to check status afterward."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "teammate": {"type": "string", "description": "Teammate name to shut down"},
            },
            "required": ["teammate"],
        },
    },
]


def _handle_shutdown(teammate: str) -> str:
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    state.bus.send("lead", teammate, "Please shut down.", "shutdown_request", {"request_id": req_id})
    return f"Shutdown request {req_id} sent to '{teammate}'"


def get_handlers() -> dict:
    return {
        "list_teammates":    lambda **kw: state.team.list_all(),
        "send_message":      lambda **kw: state.bus.send("lead", kw["to"], kw["content"]),
        "read_inbox":        lambda **kw: json.dumps(state.bus.read_inbox("lead"), indent=2),
        "broadcast":         lambda **kw: state.bus.broadcast("lead", kw["content"], state.team.member_names()),
        "shutdown_teammate": lambda **kw: _handle_shutdown(kw["teammate"]),
    }
