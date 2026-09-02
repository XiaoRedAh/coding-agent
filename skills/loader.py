"""
skills/loader.py - 技能文件加载器（Agent Skills 规范兼容）

实现渐进式披露的技能系统（对齐 agentskills.io 官方规范）：
1. 启动时扫描技能目录，解析 SKILL.md 的 frontmatter
2. 在 System Prompt 中只放技能简介（名称 + 描述，约 100 token/技能）
3. LLM 通过 load_skill 工具按需加载完整内容（建议 < 5000 token）
4. 支持参数替换（$ARGUMENTS 等占位符）与 ${SKILL_DIR} 引用

规范兼容（https://agentskills.io/specification）：
- 必填字段：name（≤64 字符，小写字母数字连字符）、description（≤1024 字符）
- 可选字段安全忽略：license、compatibility、metadata、allowed-tools
  （不报错、不拦截，元数据保留在 meta 中供上层使用）
- 目录约定：技能 = 一个目录 + 一个 SKILL.md；references/scripts/assets
  按需通过 ${SKILL_DIR} 相对路径由 LLM 自行读取（agent 无需特殊支持）
- 第三层披露：超长正文可拆分为多个文件，SKILL.md 引用相对路径

多层来源（对齐 cc 的优先级）：
1. 项目级：{workdir}/skills/
2. 项目配置级：{workdir}/.xiaoagent/skills/
3. 用户级：~/.xiaoagent/skills/

对应 Claude Code 的 skills/loadSkillsDir.ts。
"""

import re
from pathlib import Path

# Agent Skills 规范约束
MAX_NAME_CHARS = 64
MAX_DESC_CHARS = 1024
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


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

        规范兼容性说明：
        - name/description 缺失或非法的技能被跳过（规范必填项），
          其余技能照常加载 —— 坏文件不影响整体
        - 规范外的可选字段（license/compatibility/metadata/allowed-tools）
          保留在 meta 中，不做校验（宽容解析，兼容开源生态）

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
                if not self._is_valid(meta, name):
                    continue
                # 先注册的优先（高优先级目录先扫描）
                if name not in self.skills:
                    self.skills[name] = {
                        "meta": meta,
                        "body": body,
                        "path": f,
                        "skill_dir": str(f.parent),
                    }

    @staticmethod
    def _is_valid(meta: dict, name: str) -> bool:
        """规范必填项校验：name 合法 + description 非空。

        不合规的技能跳过加载（开源生态里的坏文件不应拖垮整个技能表）。
        可选字段一律不校验。
        """
        if not (1 <= len(name) <= MAX_NAME_CHARS):
            return False
        if not _NAME_PATTERN.match(name):
            return False
        desc = meta.get("description", "")
        if not desc or len(desc) > MAX_DESC_CHARS:
            return False
        return True

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
        - $ARG_1, $ARG_2, ... → 空格分隔的参数
        - ${SKILL_DIR} → SKILL.md 所在目录（规范第三层披露的入口：
          LLM 据此用 read_file 读取技能携带的 references/scripts/assets）

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
