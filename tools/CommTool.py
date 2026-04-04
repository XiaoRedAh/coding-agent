"""
tools/CommTool.py - 通信工具

提供团队通信功能：消息发送、收件箱读取、广播、关闭请求、计划审批、空闲信号。
包含关闭请求和计划审批的协议状态追踪。
"""

import json
import uuid

from bootstrap import state
from bootstrap.state import VALID_MSG_TYPES

# === 协议状态追踪 ===
shutdown_requests = {}
plan_requests = {}

DEFINITIONS = [
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
    {
        "name": "idle",
        "description": "Enter idle state.",
        "input_schema": {"type": "object", "properties": {}},
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


def _handle_plan_review(request_id: str, approve: bool, feedback: str = "") -> str:
    """处理计划审批响应"""
    req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    state.bus.send(
        "lead", req["from"], feedback, "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback},
    )
    return f"Plan {req['status']} for '{req['from']}'"


def get_handlers() -> dict:
    """返回通信工具的处理函数映射"""
    return {
        "spawn_teammate":   lambda **kw: state.team.spawn(kw["name"], kw["role"], kw["prompt"]),
        "list_teammates":   lambda **kw: state.team.list_all(),
        "send_message":     lambda **kw: state.bus.send("lead", kw["to"], kw["content"], kw.get("msg_type", "message")),
        "read_inbox":       lambda **kw: json.dumps(state.bus.read_inbox("lead"), indent=2),
        "broadcast":        lambda **kw: state.bus.broadcast("lead", kw["content"], state.team.member_names()),
        "shutdown_request": lambda **kw: _handle_shutdown(kw["teammate"]),
        "plan_approval":    lambda **kw: _handle_plan_review(kw["request_id"], kw["approve"], kw.get("feedback", "")),
        "idle":             lambda **kw: "Lead does not idle.",
    }
