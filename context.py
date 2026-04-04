"""
context.py - 上下文构建

组装系统提示词，整合工作目录信息和可用技能描述。
对应 Claude Code 源码中的 context.ts（getSystemContext / getUserContext）。
"""

from bootstrap.state import WORKDIR
from bootstrap import state


def build_system_prompt() -> str:
    """
    构建主代理的系统提示词。

    整合工作目录路径、任务管理使用建议、可用技能列表等信息。

    Returns:
        完整的系统提示词字符串
    """
    return (
        f"You are a coding agent at {WORKDIR}. Use tools to solve tasks.\n"
        f"Prefer task_create/task_update/task_list for multi-step work. "
        f"Use TodoWrite for short checklists.\n"
        f"Use task for subagent delegation. Use load_skill for specialized knowledge.\n"
        f"Skills: {state.skills.descriptions()}"
    )
