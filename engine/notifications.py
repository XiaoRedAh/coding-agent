"""
core/notifications.py - 通知收集（S4 从 query.py 拆出）

统一处理两类运行时通知的收集与消息注入：
1. 后台 Shell 任务（BackgroundManager）
2. 异步子 Agent（AgentTaskQueue，主循环"有任务在飞即等待"的等待语义）

返回纯数据（content 字符串 + skip 决策），由调用方决定注入。
"""

from __future__ import annotations

from ui.console import ok_sym


def collect_bg_notifications(state) -> str | None:
    """
    收集后台 Shell 任务通知。

    Returns:
        可注入的 <background-results> 消息内容，无通知时返回 None。
    """
    bg_notifs = state.bg.drain()
    if not bg_notifs:
        return None
    txt = "\n".join(
        f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in bg_notifs
    )
    return f"<background-results>\n{txt}\n</background-results>"


def process_agent_notifications(
    state, wait_for_inflight: bool, wait_timeout: float
) -> tuple[str | None, bool]:
    """
    收集异步子 Agent 通知（主循环统一等待语义）。

    Args:
        state: runtime.state（需有 agent_tasks 属性）
        wait_for_inflight: 是否执行"有任务在飞就等待/继续收集"的等待语义。
            主 Agent 固定传 True（这是普通模式的基础能力）；子 Agent 无后台任务用不到。
        wait_timeout: 等待 Worker 完成的超时（秒）

    Returns:
        (content, skip_llm):
        - content: 可注入的 <task-notification> 消息内容，无通知时为 None
        - skip_llm: True 表示本轮应跳过 LLM 调用继续等待
    """
    agent_notifs, in_flight = state.agent_tasks.drain()
    has_new_notifications = bool(agent_notifs)

    # 没有新完成的通知但仍有任务在飞 → 阻塞等待一轮
    if wait_for_inflight and not has_new_notifications and in_flight > 0:
        print(f"\033[90m[agent-wait] 等待 {in_flight} 个 Worker 完成...\033[0m")
        agent_notifs, in_flight = state.agent_tasks.wait_and_drain(timeout=wait_timeout)
        if not agent_notifs:
            print(f"\033[93m[agent-wait] 等待超时，仍有 {in_flight} 个任务在运行，继续等待...\033[0m")
            return None, True  # 跳过 LLM 调用，继续等待
        has_new_notifications = True
        print(f"\033[90m[agent-wait] 收到 {len(agent_notifs)} 个通知，继续\033[0m")

    if not agent_notifs:
        return None, False

    parts = []
    for n in agent_notifs:
        print(f"\033[35m  {ok_sym()} Agent [{n['agent_type']}] {n['status']}\033[0m")
        parts.append(
            f"<task-notification>\n"
            f"  <task-id>{n['task_id']}</task-id>\n"
            f"  <type>{n['agent_type']}</type>\n"
            f"  <status>{n['status']}</status>\n"
            f"  <result>{n['result']}</result>\n"
            f"</task-notification>"
        )

    if wait_for_inflight and in_flight > 0:
        parts.append(f"<in-flight-count>{in_flight}</in-flight-count>")
    elif wait_for_inflight:
        parts.append("<all-complete/>")

    # 收到通知但仍有任务在飞：跳过 LLM 调用，继续收集
    if wait_for_inflight and has_new_notifications and in_flight > 0:
        print(f"\033[35m[agent-wait] 已收集结果，但仍有 {in_flight} 个任务在运行。继续等待...\033[0m")
        return "\n".join(parts), True

    return "\n".join(parts), False
