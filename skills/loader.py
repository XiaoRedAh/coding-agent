"""
skills/loader.py - 技能文件加载器

从 skills/ 目录下递归查找 SKILL.md 文件，解析前置元数据（YAML frontmatter），
并提供按名称加载技能内容的功能。
"""

import re
from pathlib import Path


class SkillLoader:
    """技能文件加载器，从 SKILL.md 文件中读取专业知识"""

    def __init__(self, skills_dir: Path):
        """
        初始化技能加载器，扫描指定目录下的所有 SKILL.md 文件。

        Args:
            skills_dir: 技能文件所在的根目录
        """
        self.skills = {}
        if skills_dir.exists():
            for f in sorted(skills_dir.rglob("SKILL.md")):
                text = f.read_text()
                match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
                meta, body = {}, text
                if match:
                    for line in match.group(1).strip().splitlines():
                        if ":" in line:
                            k, v = line.split(":", 1)
                            meta[k.strip()] = v.strip()
                    body = match.group(2).strip()
                name = meta.get("name", f.parent.name)
                self.skills[name] = {"meta": meta, "body": body}

    def descriptions(self) -> str:
        """获取所有技能的简短描述列表"""
        if not self.skills:
            return "(no skills)"
        return "\n".join(
            f"  - {n}: {s['meta'].get('description', '-')}"
            for n, s in self.skills.items()
        )

    def load(self, name: str) -> str:
        """按名称加载技能的完整内容"""
        s = self.skills.get(name)
        if not s:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
        return f"<skill name=\"{name}\">\n{s['body']}\n</skill>"
