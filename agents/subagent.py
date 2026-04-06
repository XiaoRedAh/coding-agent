"""
agents/subagent.py - SubAgent 模式（同步 + 异步）

支持两种执行方式：
1. 同步（run_subagent）— 阻塞主 Agent 直到完成
2. 异步（run_subagent_async）— 后台线程执行，通过 AgentTaskQueue 通知主 Agent

异步结果通过独立的 AgentTaskQueue 传递（不依赖 BackgroundManager），
主 Agent 在 query.py 中通过 state.agent_tasks.drain() 接收。

对应 Claude Code 的 runAgent + registerAsyncAgent + LocalAgentTask。
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
    """子 Agent 的通用循环：LLM 调用 → 工具执行 → 返回最终文本。"""
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


def run_subagent(prompt: str, agent_type: str = "general") -> str:
    """同步子代理：阻塞主 Agent 直到完成。"""
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


def run_subagent_async(
    prompt: str,
    agent_type: str = "general",
    description: str = "",
) -> str:
    """
    异步子代理：后台线程执行，通过 AgentTaskQueue 传递结果。

    结果不再依赖 BackgroundManager，而是通过独立的 state.agent_tasks 队列。
    主 Agent 在 query.py 中通过 agent_tasks.drain() 接收 <task-notification>。
    """
    task_id = f"agent-{uuid.uuid4().hex[:8]}"

    def _run():
        try:
            result = run_subagent(prompt, agent_type)
            state.agent_tasks.submit(task_id, agent_type, "completed", result[:2000])
        except Exception as e:
            state.agent_tasks.submit(task_id, agent_type, "error", str(e))

    threading.Thread(target=_run, daemon=True).start()
    label = description or agent_type
    print(f"  [subagent:{agent_type}] started in background (id: {task_id})")
    return f"Background agent '{label}' started (id: {task_id}). You'll be notified when done."
