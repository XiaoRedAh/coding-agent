"""单元测试：skills/loader.py"""
import pytest
from pathlib import Path
from skills.loader import SkillLoader


def _create_skill(base_dir, name, description="test skill", body="# Test"):
    d = base_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}"
    )


class TestSkillLoader:
    def test_scan_skills(self, tmp_path):
        _create_skill(tmp_path, "commit", "Git commit helper")
        _create_skill(tmp_path, "review", "Code review")
        loader = SkillLoader(tmp_path)
        assert "commit" in loader.skills
        assert "review" in loader.skills
        assert len(loader.skills) == 2

    def test_descriptions(self, tmp_path):
        _create_skill(tmp_path, "commit", "Git commit helper")
        loader = SkillLoader(tmp_path)
        desc = loader.descriptions()
        assert "commit" in desc
        assert "Git commit helper" in desc

    def test_descriptions_empty(self, tmp_path):
        loader = SkillLoader(tmp_path)
        assert loader.descriptions() == "(no skills)"

    def test_load_skill(self, tmp_path):
        _create_skill(tmp_path, "commit", body="Step 1: git status")
        loader = SkillLoader(tmp_path)
        content = loader.load("commit")
        assert "Step 1: git status" in content
        assert '<skill name="commit">' in content

    def test_load_unknown_skill(self, tmp_path):
        loader = SkillLoader(tmp_path)
        result = loader.load("nonexistent")
        assert "Error" in result

    def test_argument_substitution(self, tmp_path):
        _create_skill(tmp_path, "greet", body="Hello $ARGUMENTS!")
        loader = SkillLoader(tmp_path)
        content = loader.load("greet", "World")
        assert "Hello World!" in content

    def test_arg_n_substitution(self, tmp_path):
        _create_skill(tmp_path, "test", body="File: $ARG_1, Mode: $ARG_2")
        loader = SkillLoader(tmp_path)
        content = loader.load("test", "main.py strict")
        assert "File: main.py" in content
        assert "Mode: strict" in content

    def test_multi_directory(self, tmp_path):
        dir1 = tmp_path / "high"
        dir2 = tmp_path / "low"
        _create_skill(dir1, "shared", "From high priority")
        _create_skill(dir2, "shared", "From low priority")
        _create_skill(dir2, "extra", "Only in low")
        loader = SkillLoader(dir1, dir2)
        assert "From high priority" in loader.skills["shared"]["meta"]["description"]
        assert "extra" in loader.skills

    def test_missing_directory(self, tmp_path):
        loader = SkillLoader(tmp_path / "nonexistent")
        assert len(loader.skills) == 0

    def test_description_truncation(self, tmp_path):
        _create_skill(tmp_path, "long", description="x" * 300)
        loader = SkillLoader(tmp_path)
        desc = loader.descriptions()
        assert "..." in desc

    def test_frontmatter_parsing(self, tmp_path):
        d = tmp_path / "test"
        d.mkdir()
        (d / "SKILL.md").write_text("---\nname: test\ndescription: A test\nversion: 1.0\n---\nBody here")
        loader = SkillLoader(tmp_path)
        assert loader.skills["test"]["meta"]["version"] == "1.0"
