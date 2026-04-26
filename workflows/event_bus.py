from __future__ import annotations

from collections import defaultdict, deque

from .schemas import StructuredMessage


class EventBus:
    """内存版发布-订阅总线。

    设计要点：
    1. 订阅关系：topic -> role
    2. 每个角色独立 inbox，避免消息抢占
    3. 维护 event_log 便于回放与审计
    """

    def __init__(self):
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        self._inboxes: dict[str, deque[StructuredMessage]] = defaultdict(deque)
        self._event_log: list[StructuredMessage] = []

    def subscribe(self, role_name: str, topics: list[str]) -> None:
        # 一个角色可订阅多个 topic
        for topic in topics:
            self._subscriptions[topic].add(role_name)

    def publish(self, message: StructuredMessage) -> None:
        # 先记录总线日志，再做路由
        self._event_log.append(message)
        role_names = set(self._subscriptions.get(message.topic, set()))
        role_names.update(self._subscriptions.get("*", set()))

        if message.send_to:
            # 如果消息带 send_to，则做二次过滤（定向投递）
            role_names = {name for name in role_names if name in message.send_to}

        for role_name in role_names:
            self._inboxes[role_name].append(message)

    def consume(self, role_name: str) -> list[StructuredMessage]:
        # 读取后清空，语义是“本轮全部消费”
        inbox = self._inboxes.get(role_name)
        if not inbox:
            return []
        items = list(inbox)
        inbox.clear()
        return items

    def has_pending(self) -> bool:
        return any(self._inboxes.values())

    @property
    def event_log(self) -> list[StructuredMessage]:
        return list(self._event_log)
