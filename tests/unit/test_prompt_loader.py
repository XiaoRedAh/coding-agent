"""提示词体系测试（P1）——三级覆盖加载器 + 记忆写入引导（第一层）。

覆盖的链路：
  A. PromptLoader 三级覆盖：项目级 > 用户级 > 内置；新增资产；缺失报错
  B. 主模板 base.md 经加载器注入 system prompt（含静态/动态分界不破坏）
  C. 记忆片段 fragments/memory.md：占位符替换、主动写入引导存在、索引追加
  D. 工作流模板经加载器加载（可被项目级覆盖）
"""

import pytest
from pathlib import Path

import runtime.state as st
from prompts.loader import PromptLoader


@pytest.fixture
def isolated_loader(tmp_path):
    """显式注入三个来源目录的加载器（不读 state，不碰 ~/.xiaoagent）。"""
    return PromptLoader(
        user_dir=tmp_path / "user_prompts",
        project_dir=tmp_path / "proj_prompts",
    )


def _write(directory: Path, rel_path: str, content: str):
    target = directory / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ──────────────────────────────────────────────
#  A. 三级覆盖语义
# ──────────────────────────────────────────────

class TestThreeTierOverride:
    def test_builtin_assets_loadable(self, isolated_loader):
        """内置资产（base.md / fragments/memory.md / workflow 模板）可直接加载。"""
        base = isolated_loader.load("base.md")
        assert "XiaoAgent" in base
        assert "# Environment" in base  # 静态/动态分界标记仍在

        fragment = isolated_loader.load("fragments/memory.md")
        assert "# auto memory" in fragment

        workflow = isolated_loader.load("workflow/analyst.md")
        assert workflow.strip()

    def test_user_overrides_builtin(self, tmp_path, isolated_loader):
        user_dir = tmp_path / "user_prompts"
        _write(user_dir, "base.md", "USER LEVEL PROMPT")
        assert isolated_loader.load("base.md") == "USER LEVEL PROMPT"

    def test_project_overrides_user_and_builtin(self, tmp_path, isolated_loader):
        _write(tmp_path / "user_prompts", "base.md", "USER LEVEL PROMPT")
        _write(tmp_path / "proj_prompts", "base.md", "PROJECT LEVEL PROMPT")
        assert isolated_loader.load("base.md") == "PROJECT LEVEL PROMPT"

    def test_new_asset_only_in_project_dir(self, tmp_path, isolated_loader):
        """项目级可新增内置没有的资产（如自定义片段）。"""
        _write(tmp_path / "proj_prompts", "fragments/my_style.md", "# my style rules")
        assert isolated_loader.exists("fragments/my_style.md")
        assert isolated_loader.load("fragments/my_style.md") == "# my style rules"

    def test_missing_asset_raises(self, isolated_loader):
        with pytest.raises(FileNotFoundError):
            isolated_loader.load("no_such_asset.md")

    def test_find_returns_highest_priority_path(self, tmp_path, isolated_loader):
        expected = _write(tmp_path / "proj_prompts", "base.md", "P")
        assert isolated_loader.find("base.md") == expected

    def test_project_dir_lazy_from_state(self, tmp_path, monkeypatch):
        """默认加载器的 project_dir 每次动态解析 state（monkeypatch 后无需重建）。"""
        monkeypatch.setattr(st, "PROJECT_DIR", tmp_path / ".xiaoagent")
        loader = PromptLoader(user_dir=tmp_path / "nonexistent_user")
        _write(tmp_path / ".xiaoagent" / "prompts", "base.md", "FROM STATE")
        assert loader.load("base.md") == "FROM STATE"


# ──────────────────────────────────────────────
#  B. 主模板接线（system prompt 经加载器构建）
# ──────────────────────────────────────────────

class TestBasePromptWiring:
    def test_build_system_prompt_uses_loader(self, tmp_workdir, monkeypatch):
        """主模板可被项目级覆盖，且覆盖后仍按 # Environment 分块。"""
        from context.prompt import build_system_prompt

        proj_prompts = tmp_workdir / ".xiaoagent" / "prompts"
        _write(proj_prompts, "base.md",
               "CUSTOM STATIC PART\n# Environment\ncwd: {{cwd}}")

        blocks = build_system_prompt()
        assert "CUSTOM STATIC PART" in blocks[0]["text"]
        assert blocks[0]["cache_control"] == {"type": "ephemeral"}
        assert str(tmp_workdir) in blocks[1]["text"]

    def test_default_base_md_structure(self, isolated_loader):
        """内置 base.md 保持动静分界与占位符约定。"""
        base = isolated_loader.load("base.md")
        assert "{{cwd}}" in base and "{{date}}" in base
        assert base.index("# System") < base.index("# Environment")


# ──────────────────────────────────────────────
#  C. 记忆片段（第一层：主动写入引导）
# ──────────────────────────────────────────────

class TestMemoryFragment:
    def test_fragment_contains_proactive_write_triggers(self, isolated_loader):
        """【第一层核心】片段必须包含主动写入时机（任务完成/偏好/决策/纠正）。"""
        fragment = isolated_loader.load("fragments/memory.md")
        assert "When to Write" in fragment
        assert "Task completed" in fragment
        assert "preference" in fragment
        assert "decision" in fragment
        assert "Do NOT wait to be asked" in fragment

    def test_prompt_section_replaces_memory_dir_placeholder(self, tmp_workdir):
        """{{memory_dir}} 占位符必须替换为实际绝对路径（LLM 要用它调 write_file）。"""
        from services.memory import MemoryManager

        mgr = MemoryManager(memory_dir=st.MEMORY_DIR)
        section = mgr.get_prompt_section()
        assert "{{memory_dir}}" not in section
        assert str(st.MEMORY_DIR) in section

    def test_prompt_section_appends_index(self, tmp_workdir):
        from services.memory import MemoryManager

        st.MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        (st.MEMORY_DIR / "MEMORY.md").write_text(
            "- [pref](pref.md) — user prefers dark mode\n", encoding="utf-8")
        section = MemoryManager(memory_dir=st.MEMORY_DIR).get_prompt_section()
        assert "Current Memory Index" in section
        assert "dark mode" in section
        assert "When to Write" in section  # 写入引导与索引共存

    def test_memory_fragment_overridable_at_project_level(self, tmp_workdir):
        """项目级覆盖记忆片段（如调整触发规则）后立即生效。"""
        from services.memory import MemoryManager

        proj_prompts = tmp_workdir / ".xiaoagent" / "prompts"
        _write(proj_prompts, "fragments/memory.md",
               "# auto memory\nCUSTOM RULES at `{{memory_dir}}`")
        section = MemoryManager(memory_dir=st.MEMORY_DIR).get_prompt_section()
        assert "CUSTOM RULES" in section
        assert str(st.MEMORY_DIR) in section

    def test_write_guidance_not_in_static_cache_block(self, tmp_workdir, monkeypatch):
        """记忆内容必须在动态块——泄漏进静态区会击穿 prompt cache。"""
        from context.prompt import build_system_prompt

        monkeypatch.setattr(st, "memory", None)
        blocks = build_system_prompt()
        assert "auto memory" not in blocks[0]["text"]


# ──────────────────────────────────────────────
#  D. 工作流模板接线
# ──────────────────────────────────────────────

class TestWorkflowTemplates:
    def test_workflow_template_via_loader(self, tmp_path):
        from workflows.prompting import PromptBuilderForWorkflow

        loader = PromptLoader(user_dir=tmp_path / "u", project_dir=tmp_path / "p")
        builder = PromptBuilderForWorkflow(loader=loader)
        rendered = builder.build_role_prompt(
            "analyst.md", "build a parser", [], [], [], 0, 2)
        assert "build a parser" in rendered

    def test_workflow_template_project_override(self, tmp_path):
        from workflows.prompting import PromptBuilderForWorkflow

        _write(tmp_path / "p", "workflow/analyst.md", "ROLE: {requirement}")
        loader = PromptLoader(user_dir=tmp_path / "u", project_dir=tmp_path / "p")
        builder = PromptBuilderForWorkflow(loader=loader)
        rendered = builder.build_role_prompt(
            "analyst.md", "REQ", [], [], [], 0, 2)
        assert rendered.strip() == "ROLE: REQ"
