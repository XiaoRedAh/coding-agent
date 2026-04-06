"""
tools/AgentTool.py - 统一的 Agent 派生工具

LLM 通过此工具派生子 Agent 或创建持久队友（统一入口）。

路由逻辑（对齐 CC 的 AgentTool.tsx）：
- 有 name 参数 → Team 路径（创建持久队友）
- 无 name 参数 → SubAgent 路径（一次性子代理）
  - run_in_background=True 或 agent.background=True → 异步
  - 否则 → 同步
"""

from agents.definitions import AGENT_DEFINITIONS

DEFINITION = {
    "name": "agent",
    "description": (
        "Launch a sub-agent or create a persistent teammate. "
        "Sub-agents run independently with isolated context. "
        "Add 'name' to create a persistent teammate (Swarm Team mode) "
        "that stays running and can communicate via send_message."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "Short (3-5 word) task description",
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Detailed task instructions. Must be self-contained: "
                    "include file paths, context, and expected output."
                ),
            },
            "type": {
                "type": "string",
                "enum": list(AGENT_DEFINITIONS.keys()),
                "description": (
                    "Agent type. "
                    "'explore': read-only codebase search (fast, safe). "
                    "'plan': structured implementation planning (read-only). "
                    "'general': full tools (read/write/edit/shell). "
                    "'verification': adversarial testing (read-only, always background). "
                    "Default: general."
                ),
            },
            "run_in_background": {
                "type": "boolean",
                "description": (
                    "Run asynchronously in background. You'll receive a "
                    "<task-notification> when done. Use for long-running tasks."
                ),
            },
            "name": {
                "type": "string",
                "description": (
                    "If provided, creates a persistent teammate (Swarm Team mode). "
                    "The teammate runs in a background thread, stays alive until "
                    "shutdown, and can communicate via send_message. "
                    "Omit for a one-shot sub-agent. Example: 'researcher', 'reviewer'."
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
    name: str = None,
) -> str:
    """统一入口：SubAgent 或 Team 队友。"""
    if name:
        from bootstrap import state
        if not state.team:
            return "Error: Team system not initialized"
        return state.team.spawn(name, role=description, prompt=prompt, agent_type=type)

    from agents.definitions import get_agent_config
    config = get_agent_config(type)
    should_async = run_in_background or config.get("background", False)

    if should_async:
        from agents.subagent import run_subagent_async
        return run_subagent_async(prompt, type, description)
    else:
        from agents.subagent import run_subagent
        return run_subagent(prompt, type)
