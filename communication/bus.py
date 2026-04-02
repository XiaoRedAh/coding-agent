"""
communication/bus.py - 消息总线

实现基于文件的消息传递系统（MessageBus）。
每个接收者有一个 .jsonl 文件作为收件箱，消息以 JSON 行格式追加。
读取消息后自动清空收件箱（drain 语义）。
"""

import json
import time

from config import INBOX_DIR


class MessageBus:
    """基于文件的消息总线，支持点对点消息和广播"""

    def __init__(self):
        """初始化消息总线，确保收件箱目录存在"""
        INBOX_DIR.mkdir(parents=True, exist_ok=True)

    def send(self, sender: str, to: str, content: str,
             msg_type: str = "message", extra: dict = None) -> str:
        """
        发送一条消息到指定接收者的收件箱。

        Args:
            sender: 发送者名称
            to: 接收者名称
            content: 消息内容
            msg_type: 消息类型（默认 "message"）
            extra: 额外字段（会合并到消息中）
        Returns:
            发送结果描述
        """
        msg = {
            "type": msg_type,
            "from": sender,
            "content": content,
            "timestamp": time.time(),
        }
        if extra:
            msg.update(extra)
        with open(INBOX_DIR / f"{to}.jsonl", "a") as f:
            f.write(json.dumps(msg) + "\n")
        return f"Sent {msg_type} to {to}"

    def read_inbox(self, name: str) -> list:
        """
        读取并清空指定名称的收件箱。

        Args:
            name: 收件箱所有者名称
        Returns:
            消息列表（读取后收件箱被清空）
        """
        path = INBOX_DIR / f"{name}.jsonl"
        if not path.exists():
            return []
        msgs = [json.loads(l) for l in path.read_text().strip().splitlines() if l]
        path.write_text("")
        return msgs

    def broadcast(self, sender: str, content: str, names: list) -> str:
        """
        向所有指定接收者广播消息（排除发送者自己）。

        Args:
            sender: 发送者名称
            content: 广播内容
            names: 接收者名称列表
        Returns:
            广播结果描述
        """
        count = 0
        for n in names:
            if n != sender:
                self.send(sender, n, content, "broadcast")
                count += 1
        return f"Broadcast to {count} teammates"
