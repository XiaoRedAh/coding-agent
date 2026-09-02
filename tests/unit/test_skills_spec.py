"""Agent Skills 规范兼容性测试（skills/loader.py）

覆盖：
  A. 规范校验：name 约束（小写/连字符/长度）、description 非空且 ≤1024、
     非法技能跳过但不影响其他技能加载
  B. 可选字段宽容解析：license/compatibility/allowed-tools/metadata 不报错、保留在 meta
  C. 开源生态真实技能验证：anthropics/skills 下载的 algorithmic-art 与
     brand-guidelines 能被扫描、简介注入、按需加载
  D. 斜杠命令触发（REPL 集成）
"""

import pytest
from pathlib import Path

from skills.loader import SkillLoader

# 从官方仓库下载的开源技能（_fetch_skills.py 产物）
OPEN_SOURCE_SKILLS_DIR = (
    Path(__file__).parent.parent.parent / "_verify_skills"
)


def _write_skill(base_dir, name, description="test skill", body="# Test",
                 extra_frontmatter=""):
    d = base_dir / name
    d.mkdir(parents=True, exist_ok=True)
    front = f"name: {name}\ndescription: {description}"
    if extra_frontmatter:
        front += f"\n{extra_frontmatter}"
    (d / "SKILL.md").write_text(
        f"---\n{front}\n---\n{body}", encoding="utf-8")


# ──────────────────────────────────────────────
#  A. 规范必填项校验
# ──────────────────────────────────────────────

class TestSpecValidation:
    def test_valid_name_accepted(self, tmp_path):
        _write_skill(tmp_path, "pdf-processing")
        assert "pdf-processing" in SkillLoader(tmp_path).skills

    def test_uppercase_name_rejected(self, tmp_path):
        """规范：name 仅小写字母数字连字符。"""
        _write_skill(tmp_path, "PDF-Processing")
        assert "PDF-Processing" not in SkillLoader(tmp_path).skills

    def test_leading_hyphen_rejected(self, tmp_path):
        _write_skill(tmp_path, "-bad")
        assert "-bad" not in SkillLoader(tmp_path).skills

    def test_double_hyphen_rejected(self, tmp_path):
        _write_skill(tmp_path, "a--b")
        assert "a--b" not in SkillLoader(tmp_path).skills

    def test_missing_description_rejected(self, tmp_path):
        d = tmp_path / "nodesc"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\nname: nodesc\n---\nBody", encoding="utf-8")
        assert "nodesc" not in SkillLoader(tmp_path).skills

    def test_empty_description_rejected(self, tmp_path):
        _write_skill(tmp_path, "empty", description="")
        assert "empty" not in SkillLoader(tmp_path).skills

    def test_overlong_description_rejected(self, tmp_path):
        """规范：description ≤ 1024 字符。"""
        _write_skill(tmp_path, "long", description="x" * 1025)
        assert "long" not in SkillLoader(tmp_path).skills

    def test_max_boundary_accepted(self, tmp_path):
        """1024 字符整（边界值）应通过。"""
        _write_skill(tmp_path, "ok", description="x" * 1024)
        assert "ok" in SkillLoader(tmp_path).skills

    def test_invalid_skill_does_not_break_others(self, tmp_path):
        """坏文件只跳过自身，不拖垮整个技能表。"""
        _write_skill(tmp_path, "good-one", description="fine")
        _write_skill(tmp_path, "Bad_Name", description="invalid name")
        loader = SkillLoader(tmp_path)
        assert "good-one" in loader.skills
        assert "Bad_Name" not in loader.skills

    def test_name_defaults_to_dir_name(self, tmp_path):
        """frontmatter 缺 name 时取目录名（目录名合法即注册）。"""
        d = tmp_path / "dir-skill"
        d.mkdir()
        (d / "SKILL.md").write_text(
            "---\ndescription: has desc only\n---\nBody", encoding="utf-8")
        assert "dir-skill" in SkillLoader(tmp_path).skills


# ──────────────────────────────────────────────
#  B. 可选字段宽容解析
# ──────────────────────────────────────────────

class TestOptionalFields:
    def test_spec_optional_fields_preserved(self, tmp_path):
        """license / compatibility / allowed-tools 保留在 meta，不报错。"""
        _write_skill(
            tmp_path, "full-spec",
            extra_frontmatter=(
                "license: Apache-2.0\n"
                "compatibility: Requires git, docker\n"
                "allowed-tools: Bash(git:*) Read\n"
                "metadata: author=someone"
            ))
        loader = SkillLoader(tmp_path)
        assert "full-spec" in loader.skills
        meta = loader.get_skill_meta("full-spec")
        assert meta["license"] == "Apache-2.0"
        assert meta["allowed-tools"] == "Bash(git:*) Read"

    def test_body_with_reference_links(self, tmp_path):
        """规范第三层披露：正文引用相对路径文件（agent 不需特殊处理）。"""
        _write_skill(
            tmp_path, "with-refs",
            body="See [reference](references/REFERENCE.md) for details.")
        loader = SkillLoader(tmp_path)
        content = loader.load("with-refs")
        assert "references/REFERENCE.md" in content


# ──────────────────────────────────────────────
#  C. 开源生态真实技能（anthropics/skills）
# ──────────────────────────────────────────────

class TestOpenSourceSkills:
    @pytest.mark.skipif(
        not OPEN_SOURCE_SKILLS_DIR.exists(),
        reason="开源技能未下载（运行 _fetch_skills.py）")
    def test_algorithmic_art_loadable(self):
        loader = SkillLoader(OPEN_SOURCE_SKILLS_DIR)
        assert "algorithmic-art" in loader.skills, \
            f"algorithmic-art 未被加载: {list(loader.skills)}"

        # 第一阶段：简介注入（长描述被截断但仍可辨）
        desc = loader.descriptions()
        assert "algorithmic-art" in desc

        # 第二阶段：按需加载完整内容
        content = loader.load("algorithmic-art")
        assert "<skill name=\"algorithmic-art\">" in content
        assert "ALGORITHMIC PHILOSOPHY" in content  # 正文实际内容

    @pytest.mark.skipif(
        not OPEN_SOURCE_SKILLS_DIR.exists(),
        reason="开源技能未下载（运行 _fetch_skills.py）")
    def test_brand_guidelines_loadable(self):
        loader = SkillLoader(OPEN_SOURCE_SKILLS_DIR)
        assert "brand-guidelines" in loader.skills

        meta = loader.get_skill_meta("brand-guidelines")
        assert meta["license"] == "Complete terms in LICENSE.txt"  # 可选字段被保留

        content = loader.load("brand-guidelines")
        assert "Anthropic Brand Styling" in content
        assert "#d97757" in content  # 正文实际内容（品牌橙色值）


# ──────────────────────────────────────────────
#  D. 斜杠命令触发
# ──────────────────────────────────────────────

class TestSlashInvocation:
    def test_slash_command_matches_skill(self, tmp_path):
        """REPL 的 /技能名 解析逻辑：技能存在时替换为加载内容。"""
        _write_skill(tmp_path, "commit", body="Step: $ARGUMENTS")
        loader = SkillLoader(tmp_path)

        stripped = "/commit fix the bug"
        parts = stripped[1:].split(None, 1)
        name, args = parts[0], (parts[1] if len(parts) > 1 else "")
        assert name in loader.skills
        content = loader.load(name, args)
        assert "Step: fix the bug" in content

    def test_unknown_slash_not_skill(self, tmp_path):
        """未知斜杠命令不命中技能表（应作为普通输入放行）。"""
        _write_skill(tmp_path, "commit")
        loader = SkillLoader(tmp_path)
        assert "unknown" not in loader.skills
