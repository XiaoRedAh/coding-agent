"""
tools/AgentTool.py - 子代理派生工具

LLM 通过此工具派生独立的子 Agent 执行隔离任务。
支持同步（阻塞）和异步（后台）两种执行方式。

同步/异步决策：
- run_in_background=True → 异步
- agent 定义 background=True（如 verification）→ 异步
- 否则 → 同步

对应 Claude Code 的 AgentTool.tsx。
"""

from agents.definitions import AGENT_DEFINITIONS

DEFINITION = {
    "name": "agent",
    "description": (
        "Launch a sub-agent to handle a task autonomously. "
        "Types: 'explore' (read-only fast search), 'plan' (structured planning), "
        "'general' (full tools), 'verification' (adversarial testing). "
        "Set run_in_background=true for long tasks that shouldn't block you."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short (3-5 word) description of the task",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed task instructions. Must be self-contained — "
                    "include file paths, context, and expected output."
                ),
            },
            "type": {
                "type": "string",
                "enum": list(AGENT_DEFINITIONS.keys()),
                "description": "Agent type (default: general)",
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "Run in background (async). You'll be notified when done. "
                    "Use for long-running tasks."
                ),
            },
        },
        "required": ["description", "prompt"],
    },
}


def handle(
    prompt: str,
    description: str = "",
    type: str = "general",
    run_in_background: bool = False,
) -> str:
    """派生子代理执行任务。"""
    from agents.definitions import get_agent_config
    config = get_agent_config(type)

    # 异步决策：用户显式指定 or Agent 定义强制后台
    should_async = run_in_background or config.get("background", False)

    if should_async:
        from agents.subagent import run_subagent_async
        return run_subagent_async(prompt, type, description)
    else:
        from agents.subagent import run_subagent
        return run_subagent(prompt, type)
