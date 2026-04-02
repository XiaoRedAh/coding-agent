"""
context 包 - 上下文管理

包含对话上下文压缩和技能加载功能：
- compression: token 估算、微压缩、自动压缩
- skills: SKILL.md 文件加载器
"""

from .compression import estimate_tokens, microcompact, auto_compact
from .skills import SkillLoader

__all__ = ["estimate_tokens", "microcompact", "auto_compact", "SkillLoader"]
