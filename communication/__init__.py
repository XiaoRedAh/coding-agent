"""
communication 包 - 通信系统

包含消息总线和协议处理：
- bus: MessageBus 消息收发与广播
- protocols: 关闭请求和计划审批协议
"""

from .bus import MessageBus
from .protocols import (
    shutdown_requests,
    plan_requests,
    handle_shutdown_request,
    handle_plan_review,
)

__all__ = [
    "MessageBus",
    "shutdown_requests",
    "plan_requests",
    "handle_shutdown_request",
    "handle_plan_review",
]
