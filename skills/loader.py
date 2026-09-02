"""
skills/loader.py - 技能文件加载器

实现渐进式披露的技能系统：
1. 启动时扫描 skills/ 目录，解析 SKILL.md 的 frontmatter
2. 在 System Prompt 中只放技能简介（名称 + 描述）
3. LLM 通过 load_skill 工具按需加载完整内容
4. 支持参数替换（$ARGUMENTS 等占位符）

多层来源（对齐 cc 的优先级）：
1. 项目级：{workdir}/skills/
2. 项目配置级：{workdir}/.xiaoagent/skills/
3. 用户级：~/.xiaoagent/skills/

对应 Claude Code 的 skills/loadSkillsDir.ts。
"""

import re
from pathlib import Path


class SkillLoader:
    """
    技能文件加载器。

    扫描多个目录下的 SKILL.md 文件，解析 YAML frontmatter，
    提供按需加载机制（渐进式披露）。
    """

    def __init__(self, *skill_dirs: Path):
        """
        初始化技能加载器，扫描指定目录下的所有 SKILL.md 文件。

        支持多个目录（按优先级，先扫描的优先），重名技能先注册的胜出。

        Args:
            *skill_dirs: 技能文件搜索目录列表（按优先级排列）
        """
        self.skills: dict[str, dict] = {}

        for skills_dir in skill_dirs:
            if not skills_dir.exists():
                continue
            for f in sorted(skills_dir.rglob("SKILL.md")):
                try:
                    text = f.read_text(encoding="utf-8")
                except Exception:
                    continue
                meta, body = self._parse_frontmatter(text)
                name = meta.get("name", f.parent.name)
                # 先注册的优先（高优先级目录先扫描）
                if name not in self.skills:
                    self.skills[name] = {
                        "meta": meta,
                        "body": body,
                        "path": f,
                        "skill_dir": str(f.parent),
                    }

    @staticmethod
    def _parse_frontmatter(text: str) -> tuple[dict, str]:
        """解析 YAML frontmatter + Markdown body"""
        match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
        if not match:
            return {}, text.strip()
        meta = {}
        for line in match.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta, match.group(2).strip()

    def descriptions(self) -> str:
        """
        获取所有技能的简短描述列表（用于 System Prompt 注入）。

        这是渐进式披露的第一阶段：只放名称和一句话描述，
        全部技能的简介通常只消耗几百 token。
        """
        from runtime.state import settings
        if not self.skills:
            return "(no skills)"
        max_desc = settings.tools.skill_description_max_chars
        lines = []
        for name, skill in self.skills.items():
            desc = skill["meta"].get("description", "-")
            # 截断过长的描述（上限来自 config/defaults.yaml）
            if len(desc) > max_desc:
                desc = desc[:max_desc - 3] + "..."
            lines.append(f"  - {name}: {desc}")
        return "\n".join(lines)

    def load(self, name: str, arguments: str = "") -> str:
        """
        按名称加载技能的完整内容（渐进式披露的第二阶段）。

        支持参数替换：
        - $ARGUMENTS → 完整参数字符串
        - ${SKILL_DIR} → SKILL.md 所在目录

        Args:
            name: 技能名称
            arguments: 可选的参数字符串
        Returns:
            技能完整内容（XML 包裹），或错误信息
        """
        skill = self.skills.get(name)
        if not skill:
            available = ", ".join(self.skills.keys()) or "(none)"
            return f"Error: Unknown skill '{name}'. Available: {available}"

        content = skill["body"]

        # 参数替换（对齐 cc 的 substituteArguments）
        if arguments:
            content = content.replace("$ARGUMENTS", arguments)
            # $ARG_1, $ARG_2, ... 替换
            args_list = arguments.split()
            for i, arg in enumerate(args_list, 1):
                content = content.replace(f"$ARG_{i}", arg)

        # ${SKILL_DIR} 替换
        content = content.replace("${SKILL_DIR}", skill.get("skill_dir", ""))

        return f"<skill name=\"{name}\">\n{content}\n</skill>"

    def get_skill_meta(self, name: str) -> dict | None:
        """获取技能的元数据（不加载完整内容）"""
        skill = self.skills.get(name)
        return skill["meta"] if skill else None

    def list_names(self) -> list[str]:
        """列出所有可用技能名称"""
        return list(self.skills.keys())
