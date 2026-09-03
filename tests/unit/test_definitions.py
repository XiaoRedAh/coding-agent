"""单元测试：agents/definitions.py"""
import pytest
from agents.definitions import get_agent_config, AGENT_DEFINITIONS, READ_ONLY_TOOLS, GENERAL_TOOLS


class TestAgentConfig:
    def test_explore(self):
        c = get_agent_config("explore")
        assert c["allowed_tools"] == READ_ONLY_TOOLS
        assert c["max_turns"] == 25
        assert c["background"] is False

    def test_plan(self):
        c = get_agent_config("plan")
        assert c["allowed_tools"] == READ_ONLY_TOOLS
        assert c["max_turns"] == 20

    def test_general(self):
        c = get_agent_config("general")
        assert c["allowed_tools"] == GENERAL_TOOLS
        assert "agent" not in c["allowed_tools"]  # 防递归

    def test_verification(self):
        c = get_agent_config("verification")
        assert c["background"] is True

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown agent type"):
            get_agent_config("nonexistent")

    def test_case_insensitive(self):
        c = get_agent_config("EXPLORE")
        assert c["max_turns"] == 25

    def test_all_types_have_required_fields(self):
        for name, config in AGENT_DEFINITIONS.items():
            assert "system_prompt" in config, f"{name} missing system_prompt"
            assert "allowed_tools" in config, f"{name} missing allowed_tools"
            assert "max_turns" in config, f"{name} missing max_turns"
