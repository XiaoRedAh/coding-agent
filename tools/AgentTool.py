"""
tools/AgentTool.py - 统一的 Agent 派生工具

LLM 通过此工具派生子 Agent（一次性任务执行）。
S6 后 agent 类型来自注册表（内置 + 用户自定义），
get_definition() 每次调用时动态生成 enum。
"""


def get_definition() -> dict:
    """动态构建工具定义（enum 反映注册表当前的全部 agent 类型）。"""
    from agents.registry import default_registry
    names = default_registry().names()
    return {
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
                    "enum": names,
                    "description": (
                        "Agent type (built-in and custom). "
                        "'explore': read-only codebase search (fast, safe). "
                        "'plan': structured implementation planning (read-only). "
                        "'general': full tools (read/write/edit/shell). "
                        "'verification': adversarial testing (read-only, always background). "
                        "Custom types may also be available. Default: general."
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


# 向后兼容快照（静态引用场景）；动态场景请用 get_definition()
DEFINITION = get_definition()


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
