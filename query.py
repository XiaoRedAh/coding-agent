"""
query.py - 核心查询循环

管理单次查询的完整生命周期状态机：
    压缩检查 → 后台通知注入 → 收件箱检查 → LLM API 调用 → 工具执行 → 循环/返回

对应 Claude Code 源码中的 query.ts。
"""

import json

from bootstrap import state
from bootstrap.state import client, MODEL, TOKEN_THRESHOLD
from services.compact import estimate_tokens, microcompact, auto_compact
from tools import get_all_definitions, get_all_handlers
from context import build_system_prompt


def agent_loop(messages: list):
    """
    主代理循环：每轮执行压缩检查、后台通知、收件箱检查、LLM 调用、工具执行。

    循环持续进行直到 LLM 返回非工具调用的停止原因（即给出最终回答）。

    Args:
        messages: 对话消息列表（会被原地修改）
    """
    system_prompt = build_system_prompt()
    tool_defs = get_all_definitions()
    tool_handlers = get_all_handlers()

    rounds_without_todo = 0
    while True:
        # === 压缩管道 ===
        microcompact(messages)
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            print("[auto-compact triggered]")
            messages[:] = auto_compact(messages)

        # === 后台通知 ===
        notifs = state.bg.drain()
        if notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{txt}\n</background-results>",
            })

        # === 收件箱检查 ===
        inbox = state.bus.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            })

        # === LLM 调用 ===
        response = client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=messages,
            tools=tool_defs,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            return

        # === 工具执行 ===
        results = []
        used_todo = False
        manual_compress = False
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "compress":
                    manual_compress = True
                handler = tool_handlers.get(block.name)
                try:
                    output = (
                        handler(**block.input)
                        if handler
                        else f"Unknown tool: {block.name}"
                    )
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}:")
                print(str(output)[:200])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
                if block.name == "TodoWrite":
                    used_todo = True

        # === 待办提醒 ===
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if state.todo.has_open_items() and rounds_without_todo >= 3:
            results.append({
                "type": "text",
                "text": "<reminder>Update your todos.</reminder>",
            })
        messages.append({"role": "user", "content": results})

        # === 手动压缩 ===
        if manual_compress:
            print("[manual compact]")
            messages[:] = auto_compact(messages)
            return
