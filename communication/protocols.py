"""
communication/protocols.py - 通信协议

实现关闭请求（shutdown）和计划审批（plan approval）协议。
使用模块级字典跟踪请求状态，通过 MessageBus 发送消息。
"""

import uuid

# === 全局状态追踪字典 ===
# 关闭请求追踪：{request_id: {"target": 队友名, "status": "pending"/"completed"}}
shutdown_requests = {}
# 计划审批请求追踪：{request_id: {"from": 发起者, "status": "pending"/"approved"/"rejected"}}
plan_requests = {}


def handle_shutdown_request(teammate: str, bus) -> str:
    """
    发起关闭请求，通知指定队友关闭。

    Args:
        teammate: 目标队友名称
        bus: MessageBus 实例
    Returns:
        关闭请求结果描述
    """
    req_id = str(uuid.uuid4())[:8]
    shutdown_requests[req_id] = {"target": teammate, "status": "pending"}
    bus.send(
        "lead", teammate, "Please shut down.",
        "shutdown_request", {"request_id": req_id}
    )
    return f"Shutdown request {req_id} sent to '{teammate}'"


def handle_plan_review(request_id: str, approve: bool,
                       feedback: str = "", bus=None) -> str:
    """
    处理计划审批响应（批准或拒绝）。

    Args:
        request_id: 计划请求 ID
        approve: 是否批准
        feedback: 反馈内容
        bus: MessageBus 实例
    Returns:
        审批结果描述
    """
    req = plan_requests.get(request_id)
    if not req:
        return f"Error: Unknown plan request_id '{request_id}'"
    req["status"] = "approved" if approve else "rejected"
    bus.send(
        "lead", req["from"], feedback, "plan_approval_response",
        {"request_id": request_id, "approve": approve, "feedback": feedback}
    )
    return f"Plan {req['status']} for '{req['from']}'"
