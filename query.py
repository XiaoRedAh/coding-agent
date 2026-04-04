"""
query.py - 核心查询循环

管理单次查询的完整生命周期状态机：
    压缩管道(L1-L3) → 后台通知 → 收件箱 → LLM 调用 → Token更新
    → 工具执行 → AutoCompact检查(L5) → 循环/返回

对应 Claude Code 源码中的 query.ts。

压缩管道编排：
    while True:
        run_compression_pipeline()   # L1-L3（零 API 成本）
        response = call_api()
        tracker.update_from_response()
        execute_tools()
        check_and_compact()          # L5（如果需要）
"""

import json

from bootstrap import state
from bootstrap.state import client, MODEL, WARNING_THRESHOLD, EFFECTIVE_WINDOW
from services.compact import (
    TokenTracker, CircuitBreaker,
    run_compression_pipeline, check_and_compact, auto_compact,
)
from tools import get_all_definitions, get_all_handlers
from context import build_system_prompt


def agent_loop(
    messages: list,
    tracker: TokenTracker = None,
    breaker: CircuitBreaker = None,
):
    """
    主代理循环：每轮执行压缩管道、后台通知、收件箱检查、LLM 调用、工具执行。

    循环持续进行直到 LLM 返回非工具调用的停止原因（即给出最终回答）。

    Args:
        messages: 对话消息列表（会被原地修改）
        tracker: Token 追踪器（跨 agent_loop 调用保持状态）
        breaker: 断路器（跨 agent_loop 调用保持状态）
    """
    if tracker is None:
        tracker = TokenTracker()
    if breaker is None:
        breaker = CircuitBreaker()

    system_prompt = build_system_prompt()
    tool_defs = get_all_definitions()
    tool_handlers = get_all_handlers()

    rounds_without_todo = 0
    while True:
        # === L1-L3 压缩管道（零 API 成本） ===
        run_compression_pipeline(messages, tracker)

        # === 上下文利用率警告 ===
        utilization = tracker.get_utilization()
        if utilization >= WARNING_THRESHOLD:
            print(f"[warning: context at {utilization:.0%}, consider /compact]")

        # === 后台通知 ===
        notifs = state.bg.drain()
        if notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            msg = {
                "role": "user",
                "content": f"<background-results>\n{txt}\n</background-results>",
            }
            messages.append(msg)
            tracker.track_new_message(msg)

        # === 收件箱检查 ===
        inbox = state.bus.read_inbox("lead")
        if inbox:
            msg = {
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            }
            messages.append(msg)
            tracker.track_new_message(msg)

        # === LLM 调用 ===
        response = client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=messages,
            tools=tool_defs,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        # === 更新 Token 锚点 ===
        tracker.update_from_response(response)

        if response.stop_reason != "tool_use":
            return tracker, breaker

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

        tool_msg = {"role": "user", "content": results}
        messages.append(tool_msg)
        tracker.track_new_message(tool_msg)

        # === 手动压缩 ===
        if manual_compress:
            print("[manual compact]")
            messages[:] = auto_compact(messages, tracker)
            breaker.record_success()  # 手动压缩成功重置断路器
            return tracker, breaker

        # === L5: AutoCompact 检查（在工具执行后） ===
        compacted = check_and_compact(messages, tracker, breaker)
        if compacted is not None:
            messages[:] = compacted
