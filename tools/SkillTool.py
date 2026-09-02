"""
tools/SkillTool.py - 技能加载工具

LLM 通过此工具按需加载专业知识/最佳实践。
这是渐进式披露的第二阶段——System Prompt 中只有简介，
LLM 判断需要时调用此工具加载完整内容。

对应 Claude Code 的 tools/SkillTool/SkillTool.ts。
"""

from runtime import state
from engine.results import ToolResult

DEFINITION = {
    "name": "load_skill",
    "description": (
        "Load specialized knowledge/best-practices by name. "
        "Available skills are listed in the system prompt under "
        "'Available skills'. Use this when you need domain-specific "
        "guidance for a task."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name (from the available skills list)",
            },
            "args": {
                "type": "string",
                "description": "Optional arguments to pass to the skill (replaces $ARGUMENTS)",
            },
        },
        "required": ["name"],
    },
}


def handle(name: str, args: str = "") -> str:
    """加载指定技能的完整内容"""
    result = state.skills.load(name, args)
    if isinstance(result, str) and result.startswith("Error:"):
        return ToolResult.failure(result, "unknown_skill")
    return result
