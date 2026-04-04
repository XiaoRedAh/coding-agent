"""
agents/subagent.py - SubAgent 模式（同步 + 异步）

支持两种执行方式：
1. 同步（run_subagent）— 阻塞主 Agent 直到完成
2. 异步（run_subagent_async）— 后台线程执行，通过 task-notification 通知主 Agent

同步/异步的选择由 AgentTool 根据以下条件决定：
- LLM 显式指定 run_in_background=True → 异步
- Agent 定义 background=True（如 verification）→ 异步
- 否则 → 同步

设计要点：
- 工具定义从全局 tools/ 包动态过滤（零重复）
- 异步结果通过 BackgroundManager 的通知队列传递给主 Agent
  （复用已有的 bg.drain() 机制，在 query.py 中统一处理）

对应 Claude Code 的 AgentTool 同步/异步执行路径。
"""

import threading
import uuid

from bootstrap.state import client, MODEL
from bootstrap import state
from agents.definitions import get_agent_config, get_filtered_tools
from utils.truncate import truncate_result


def _run_agent_loop(
    system_prompt: str,
    messages: list,
    tool_defs: list,
    tool_handlers: dict,
    max_turns: int,
) -> str:
    """
    子 Agent 的通用循环：LLM 调用 → 工具执行 → 返回最终文本。

    与 query.py 的 agent_loop 独立，因为子 Agent 不需要
    压缩管道、后台通知、收件箱检查、Token 追踪等。
    """
    resp = None
    for _ in range(max_turns):
        resp = client.messages.create(
            model=MODEL,
            system=system_prompt,
            messages=messages,
            tools=tool_defs,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                handler = tool_handlers.get(block.name)
                try:
                    output = str(handler(**block.input)) if handler else f"Unknown tool: {block.name}"
                except Exception as e:
                    output = f"Error: {e}"
                print(f"  [sub] {block.name}: {output[:120]}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": truncate_result(output),
                })
        messages.append({"role": "user", "content": results})

    if resp:
        return "".join(b.text for b in resp.content if hasattr(b, "text")) or "(no output)"
    return "(subagent failed)"


# ──────────────────────────────────────────────
#  同步执行
# ──────────────────────────────────────────────

def run_subagent(prompt: str, agent_type: str = "general") -> str:
    """
    同步子代理：阻塞主 Agent 直到完成。

    Args:
        prompt: 任务指令（必须自包含）
        agent_type: Agent 类型 (explore/plan/general/verification)
    Returns:
        子代理的最终文本输出
    """
    config = get_agent_config(agent_type)
    tool_defs, tool_handlers = get_filtered_tools(config["allowed_tools"])
    messages = [{"role": "user", "content": prompt}]

    print(f"  [subagent:{agent_type}] starting (sync)...")
    result = _run_agent_loop(
        config["system_prompt"], messages, tool_defs, tool_handlers,
        config["max_turns"],
    )
    print(f"  [subagent:{agent_type}] done.")
    return result


# ──────────────────────────────────────────────
#  异步执行
# ──────────────────────────────────────────────

def run_subagent_async(
    prompt: str,
    agent_type: str = "general",
    description: str = "",
) -> str:
    """
    异步子代理：后台线程执行，通过通知队列传递结果。

    结果通过 state.bg 的通知队列传递，主 Agent 在 query.py 的
    每轮循环中通过 bg.drain() 接收 <background-results>。

    Args:
        prompt: 任务指令
        agent_type: Agent 类型
        description: 简短描述
    Returns:
        启动确认消息
    """
    task_id = f"agent-{uuid.uuid4().hex[:8]}"

    def _run():
        try:
            result = run_subagent(prompt, agent_type)
            # 复用 BackgroundManager 的通知队列
            state.bg.notifications.put({
                "task_id": task_id,
                "status": "completed",
                "result": f"[{agent_type}] {result[:2000]}",
            })
        except Exception as e:
            state.bg.notifications.put({
                "task_id": task_id,
                "status": "error",
                "result": f"[{agent_type}] Error: {e}",
            })

    threading.Thread(target=_run, daemon=True).start()
    label = description or agent_type
    print(f"  [subagent:{agent_type}] started in background (id: {task_id})")
    return f"Background agent '{label}' started (id: {task_id}). You'll be notified when done."
