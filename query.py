"""
query.py - 核心查询循环

管理单次查询的完整生命周期状态机：
    压缩管道(L1-L3) → 后台通知 → 收件箱 → LLM 调用 → Token更新
    → 工具执行 → AutoCompact检查(L5) → 循环/返回

在 Coordinator 模式下，系统提示和工具池被替换为协调者配置，
主 Agent 变为只能调度 Worker 的协调者。

对应 Claude Code 源码中的 query.ts。
"""

import json

from bootstrap import state
from bootstrap.state import WARNING_THRESHOLD
from services.compact import (
    TokenTracker, CircuitBreaker,
    run_compression_pipeline, check_and_compact,
)
from tools import get_all_definitions, get_all_handlers
from context import build_system_prompt
from agents.coordinator import is_coordinator_mode, get_coordinator_config
from services.permissions import check_permission


def agent_loop(
    messages: list,
    tracker: TokenTracker = None,
    breaker: CircuitBreaker = None,
):
    """
    主代理循环。

    在 Coordinator 模式下，系统提示和工具池被替换，主 Agent 变为协调者。
    """
    if tracker is None:
        tracker = TokenTracker()
    if breaker is None:
        breaker = CircuitBreaker()

    # === 根据模式选择配置 ===
    all_defs = get_all_definitions()
    all_handlers = get_all_handlers()

    if is_coordinator_mode():
        coord_config = get_coordinator_config()
        system_prompt = coord_config["system_prompt"]
        allowed = coord_config["allowed_tools"]
        tool_defs = [d for d in all_defs if d["name"] in allowed]
        tool_handlers = {k: v for k, v in all_handlers.items() if k in allowed}
        print("[coordinator mode active]")
    else:
        system_prompt = build_system_prompt()
        tool_defs = all_defs
        tool_handlers = all_handlers

    rounds_without_todo = 0
    while True:
        # === L1-L3 压缩管道 ===
        run_compression_pipeline(messages, tracker)

        utilization = tracker.get_utilization()
        if utilization >= WARNING_THRESHOLD:
            print(f"[warning: context at {utilization:.0%}, consider /compact]")

        # === 后台 Shell 通知 ===
        bg_notifs = state.bg.drain()
        if bg_notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in bg_notifs
            )
            msg = {"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"}
            messages.append(msg)
            tracker.track_new_message(msg)

        # === 异步 Agent 通知（独立于 Shell 后台） ===
        if state.agent_tasks:
            agent_notifs = state.agent_tasks.drain()
            if agent_notifs:
                parts = []
                for n in agent_notifs:
                    parts.append(
                        f"<task-notification>\n"
                        f"  <task-id>{n['task_id']}</task-id>\n"
                        f"  <type>{n['agent_type']}</type>\n"
                        f"  <status>{n['status']}</status>\n"
                        f"  <result>{n['result']}</result>\n"
                        f"</task-notification>"
                    )
                msg = {"role": "user", "content": "\n".join(parts)}
                messages.append(msg)
                tracker.track_new_message(msg)

        # === 收件箱检查 ===
        inbox = state.bus.read_inbox("lead")
        if inbox:
            msg = {"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"}
            messages.append(msg)
            tracker.track_new_message(msg)

        # === LLM 调用（流式输出） ===
        def _on_text(delta):
            print(delta, end="", flush=True)

        response = state.llm.chat(
            system_prompt, messages, tool_defs,
            stream=True, on_text=_on_text,
        )
        # 流式文本已逐字打印，补一个换行
        if response.stop_reason != "tool_use":
            print()  # 最终回答打印完换行
        messages.append({"role": "assistant", "content": response.content})
        tracker.update_from_response(response)

        if response.stop_reason != "tool_use":
            return tracker, breaker

        # === 工具执行（含权限检查） ===
        results = []
        used_todo = False
        perm_mode = state.PERMISSION_MODE
        for block in response.content:
            if block.type == "tool_use":
                # --- 权限检查 ---
                perm = check_permission(block.name, block.input, perm_mode, state.perm_rules)

                if perm["action"] == "deny":
                    output = f"Permission denied: {perm['reason']}"
                    print(f"> {block.name}: [DENIED] {perm['reason']}")
                elif perm["action"] == "confirm":
                    # 交互式确认
                    print(f"\n  ⚠ {perm['reason']}")
                    try:
                        answer = input("  Allow? (y/n): ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    if answer.startswith("y"):
                        # 记住用户授权（会话级白名单）
                        from services.permissions import _get_content_key
                        key = f"{block.name}:{_get_content_key(block.name, block.input)}"
                        state.perm_rules.add_session_allow(key)
                        handler = tool_handlers.get(block.name)
                        try:
                            output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                        except Exception as e:
                            output = f"Error: {e}"
                        print(f"> {block.name}:")
                        print(str(output)[:200])
                    else:
                        output = "User denied this action."
                        print(f"> {block.name}: [USER DENIED]")
                else:  # allow
                    handler = tool_handlers.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
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
        if state.todo and state.todo.has_open_items() and rounds_without_todo >= 3:
            results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})

        tool_msg = {"role": "user", "content": results}
        messages.append(tool_msg)
        tracker.track_new_message(tool_msg)

        # === L5: AutoCompact 检查 ===
        compacted = check_and_compact(messages, tracker, breaker)
        if compacted is not None:
            messages[:] = compacted
