"""
skills 包 - 技能系统

从 SKILL.md 文件加载专业知识，供 LLM 按需调用。
"""

from .loader import SkillLoader

__all__ = ["SkillLoader"]
