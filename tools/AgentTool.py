"""
tools/AgentTool.py - 统一的 Agent 派生工具

LLM 通过此工具派生子 Agent（一次性任务执行）。
"""

from agents.definitions import AGENT_DEFINITIONS

DEFINITION = {
    "name": "agent",
    "description": (
        "Launch a sub-agent to execute a task with isolated context. "
        "Sub-agents run independently and return results when complete."
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
    """统一入口：SubAgent。"""
    from agents.definitions import get_agent_config
    config = get_agent_config(type)
    should_async = run_in_background or config.get("background", False)

    if should_async:
        from agents.subagent import run_subagent_async
        return run_subagent_async(prompt, type, description)
    else:
        from agents.subagent import run_subagent
        return run_subagent(prompt, type)
