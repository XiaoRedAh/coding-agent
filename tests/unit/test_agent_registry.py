"""Unit tests for agents/registry.py — 统一 Agent 注册表（S6）。

覆盖：内置类型加载、自定义 YAML/JSON 加载、优先级覆盖、校验报错、
与 definitions/AgentTool 的接线（enum 动态化）。
"""

import pytest

from agents.registry import AgentRegistry, rebuild_default


CUSTOM_YAML = """\
name: doc-writer
description: Writes documentation
system_prompt: |
  You are a documentation writer.
allowed_tools:
  - read_file
  - write_file
max_turns: 12
"""


@pytest.fixture
def fresh_registry():
    """隔离的默认注册表（不读取真实用户/项目目录）。"""
    return rebuild_default(
        user_dir=None, project_dir=None, extra_dirs=None,
    )


class TestBuiltinAgents:
    def test_four_builtins_present(self, fresh_registry):
        assert fresh_registry.names() == [
            "explore", "general", "plan", "verification"]

    def test_explore_config(self, fresh_registry):
        c = fresh_registry.get("explore")
        assert c["max_turns"] == 15
        assert c["background"] is False
        assert c["allowed_tools"] == frozenset(
            {"read_file", "list_files", "grep_search", "run_shell"})
        assert "Explore agent" in c["system_prompt"]

    def test_general_excludes_agent_tool(self, fresh_registry):
        """general 工具集不含 agent（防递归派生）。"""
        c = fresh_registry.get("general")
        assert "agent" not in c["allowed_tools"]
        assert "write_file" in c["allowed_tools"]

    def test_verification_always_background(self, fresh_registry):
        assert fresh_registry.get("verification")["background"] is True

    def test_case_insensitive_lookup(self, fresh_registry):
        assert fresh_registry.get("EXPLORE")["max_turns"] == 15

    def test_unknown_type_lists_available(self, fresh_registry):
        with pytest.raises(ValueError, match="explore"):
            fresh_registry.get("no_such_type")


class TestCustomAgents:
    def test_custom_yaml_loaded_from_project_dir(self, tmp_path):
        agents_dir = tmp_path / ".xiaoagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "doc-writer.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

        reg = AgentRegistry(project_dir=agents_dir)
        assert "doc-writer" in reg.names()
        c = reg.get("doc-writer")
        assert c["max_turns"] == 12
        assert c["allowed_tools"] == frozenset({"read_file", "write_file"})

    def test_name_defaults_to_file_stem(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        yaml_no_name = CUSTOM_YAML.replace("name: doc-writer\n", "")
        (agents_dir / "reviewer.yaml").write_text(yaml_no_name, encoding="utf-8")

        reg = AgentRegistry(project_dir=agents_dir)
        assert "reviewer" in reg.names()

    def test_project_overrides_builtin(self, tmp_path):
        """项目级同名定义覆盖内置类型。"""
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "explore.yaml").write_text(
            CUSTOM_YAML.replace("name: doc-writer", "name: explore"),
            encoding="utf-8")

        reg = AgentRegistry(project_dir=agents_dir)
        assert reg.get("explore")["max_turns"] == 12  # 被覆盖
        assert reg.get("explore")["allowed_tools"] == frozenset(
            {"read_file", "write_file"})

    def test_priority_project_beats_user(self, tmp_path):
        user_dir = tmp_path / "user_agents"
        proj_dir = tmp_path / "proj_agents"
        for d in (user_dir, proj_dir):
            d.mkdir()
        (user_dir / "helper.yaml").write_text(
            CUSTOM_YAML.replace("name: doc-writer", "name: helper")
                       .replace("max_turns: 12", "max_turns: 20"),
            encoding="utf-8")
        (proj_dir / "helper.yaml").write_text(
            CUSTOM_YAML.replace("name: doc-writer", "name: helper"),
            encoding="utf-8")

        reg = AgentRegistry(user_dir=user_dir, project_dir=proj_dir)
        assert reg.get("helper")["max_turns"] == 12  # 项目级胜出

    def test_json_definition_supported(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        import json
        (agents_dir / "helper.json").write_text(json.dumps({
            "name": "helper",
            "system_prompt": "You help.",
            "allowed_tools": ["read_file"],
            "max_turns": 5,
        }), encoding="utf-8")

        reg = AgentRegistry(project_dir=agents_dir)
        assert reg.get("helper")["max_turns"] == 5


class TestValidation:
    def test_missing_required_field(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yaml").write_text(
            "name: bad\nsystem_prompt: x\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing required field 'allowed_tools'"):
            AgentRegistry(project_dir=agents_dir)

    def test_unknown_field_rejected(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yaml").write_text(
            CUSTOM_YAML + "toolset: [read_file]\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown fields"):
            AgentRegistry(project_dir=agents_dir)

    def test_non_positive_max_turns(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yaml").write_text(
            CUSTOM_YAML.replace("max_turns: 12", "max_turns: 0"),
            encoding="utf-8")
        with pytest.raises(ValueError, match="must be positive"):
            AgentRegistry(project_dir=agents_dir)

    def test_invalid_yaml_syntax(self, tmp_path):
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "bad.yaml").write_text(
            "system_prompt: [unclosed\n", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid agent definition"):
            AgentRegistry(project_dir=agents_dir)


class TestWiring:
    def test_get_agent_config_supports_custom(self, tmp_path, monkeypatch):
        """definitions.get_agent_config 应能查到注册表中的自定义类型。"""
        import runtime.state as st
        monkeypatch.setattr(st, "PROJECT_DIR", tmp_path / ".xiaoagent")
        agents_dir = tmp_path / ".xiaoagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "doc-writer.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

        rebuild_default()  # 用新 PROJECT_DIR 重建
        from agents.definitions import get_agent_config
        assert get_agent_config("doc-writer")["max_turns"] == 12

        # 恢复默认注册表（避免污染其他测试）
        rebuild_default(user_dir=None, project_dir=None)

    def test_agent_tool_enum_includes_custom(self, tmp_path, monkeypatch):
        """AgentTool.get_definition 的 enum 应动态包含自定义类型。"""
        import runtime.state as st
        monkeypatch.setattr(st, "PROJECT_DIR", tmp_path / ".xiaoagent")
        agents_dir = tmp_path / ".xiaoagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "doc-writer.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

        rebuild_default()
        from tools import AgentTool, get_all_definitions
        d = AgentTool.get_definition()
        assert "doc-writer" in d["input_schema"]["properties"]["type"]["enum"]
        assert "explore" in d["input_schema"]["properties"]["type"]["enum"]

        # 工具注册表聚合也应包含动态 enum
        all_names = {t["name"] for t in get_all_definitions()}
        assert "agent" in all_names

        rebuild_default(user_dir=None, project_dir=None)

    def test_agent_tool_dispatches_custom_type(self, tmp_path, monkeypatch):
        """AgentTool.handle 应能用自定义类型派发（走对应配置）。"""
        import runtime.state as st
        monkeypatch.setattr(st, "PROJECT_DIR", tmp_path / ".xiaoagent")
        agents_dir = tmp_path / ".xiaoagent" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "doc-writer.yaml").write_text(CUSTOM_YAML, encoding="utf-8")

        rebuild_default()
        from unittest.mock import patch
        from tools import AgentTool
        with patch("agents.subagent.run_subagent", return_value="doc result") as mock_run:
            out = AgentTool.handle(prompt="write docs", description="d",
                                   type="doc-writer")
        assert out == "doc result"
        mock_run.assert_called_once_with("write docs", "doc-writer")

        rebuild_default(user_dir=None, project_dir=None)

    def test_definitions_compat_exports(self, fresh_registry):
        """旧导出（AGENT_DEFINITIONS/常量/函数）保持可用。"""
        from agents.definitions import (
            AGENT_DEFINITIONS, READ_ONLY_TOOLS, GENERAL_TOOLS,
            get_agent_config, get_filtered_tools,
        )
        assert set(AGENT_DEFINITIONS) >= {"explore", "plan", "general", "verification"}
        assert get_agent_config("general")["allowed_tools"] == GENERAL_TOOLS
        assert get_agent_config("explore")["allowed_tools"] == READ_ONLY_TOOLS
        defs, handlers = get_filtered_tools(READ_ONLY_TOOLS)
        assert all(d["name"] in READ_ONLY_TOOLS for d in defs)
        assert set(handlers) <= READ_ONLY_TOOLS
