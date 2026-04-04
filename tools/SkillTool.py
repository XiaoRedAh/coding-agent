"""
tools/SkillTool.py - 技能加载工具

按名称加载 SKILL.md 专业知识文件。
"""

from bootstrap import state

DEFINITION = {
    "name": "load_skill",
    "description": "Load specialized knowledge by name.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}


def handle(name: str) -> str:
    """加载指定技能"""
    return state.skills.load(name)
