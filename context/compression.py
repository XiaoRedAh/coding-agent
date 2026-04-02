"""
context/compression.py - 上下文压缩模块

提供三层压缩策略：
1. estimate_tokens: 粗略估算消息列表的 token 数量
2. microcompact: 清除旧的工具结果，释放空间（保留最近 3 个）
3. auto_compact: 保存完整转录并用 LLM 生成摘要替换上下文
"""

import json
import time

from config import TRANSCRIPT_DIR, client, MODEL


def estimate_tokens(messages: list) -> int:
    """
    粗略估算消息列表的 token 数量。

    使用 JSON 序列化长度除以 4 的近似方法。

    Args:
        messages: 对话消息列表
    Returns:
        估算的 token 数量
    """
    return len(json.dumps(messages, default=str)) // 4


def microcompact(messages: list):
    """
    微压缩：清除旧的工具返回结果内容，只保留最近 3 个。

    直接修改传入的消息列表（原地操作），将超过 100 字符的旧工具结果
    替换为 "[cleared]" 占位符。

    Args:
        messages: 对话消息列表（会被原地修改）
    """
    indices = []
    for i, msg in enumerate(messages):
        if msg["role"] == "user" and isinstance(msg.get("content"), list):
            for part in msg["content"]:
                if isinstance(part, dict) and part.get("type") == "tool_result":
                    indices.append(part)
    if len(indices) <= 3:
        return
    for part in indices[:-3]:
        if isinstance(part.get("content"), str) and len(part["content"]) > 100:
            part["content"] = "[cleared]"


def auto_compact(messages: list) -> list:
    """
    自动压缩：保存完整转录到文件，然后用 LLM 生成摘要替换整个上下文。

    流程：
    1. 将当前所有消息保存为 .transcripts/transcript_{timestamp}.jsonl
    2. 取最近 80000 字符发送给 LLM 生成摘要
    3. 返回只包含摘要的新消息列表

    Args:
        messages: 当前完整的对话消息列表
    Returns:
        压缩后的新消息列表（只包含一条摘要消息）
    """
    TRANSCRIPT_DIR.mkdir(exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")
    conv_text = json.dumps(messages, default=str)[-80000:]
    resp = client.messages.create(
        model=MODEL,
        messages=[{"role": "user", "content": f"Summarize for continuity:\n{conv_text}"}],
        max_tokens=2000,
    )
    summary = resp.content[0].text
    return [
        {"role": "user", "content": f"[Compressed. Transcript: {path}]\n{summary}"},
    ]
