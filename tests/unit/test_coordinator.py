"""单元测试：agents/coordinator.py（纯配置逻辑，不涉及 LLM）"""
import os
import pytest
from agents.coordinator import is_coordinator_mode, get_coordinator_config, COORDINATOR_ALLOWED_TOOLS


class TestCoordinatorMode:
    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("COORDINATOR_MODE", raising=False)
        # Re-import to pick up env change
        import importlib
        import agents.coordinator as coord
        importlib.reload(coord)
        assert not coord.is_coordinator_mode()

    def test_enabled(self, monkeypatch):
        monkeypatch.setenv("COORDINATOR_MODE", "1")
        import importlib
        import agents.coordinator as coord
        importlib.reload(coord)
        assert coord.is_coordinator_mode()

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("COORDINATOR_MODE", "true")
        import importlib
        import agents.coordinator as coord
        importlib.reload(coord)
        assert coord.is_coordinator_mode()

    def test_disabled_zero(self, monkeypatch):
        monkeypatch.setenv("COORDINATOR_MODE", "0")
        import importlib
        import agents.coordinator as coord
        importlib.reload(coord)
        assert not coord.is_coordinator_mode()


class TestCoordinatorConfig:
    def test_has_system_prompt(self):
        config = get_coordinator_config()
        assert "system_prompt" in config
        assert "Coordinator" in config["system_prompt"]

    def test_has_allowed_tools(self):
        config = get_coordinator_config()
        assert "allowed_tools" in config

    def test_agent_in_allowed(self):
        assert "agent" in COORDINATOR_ALLOWED_TOOLS

    def test_no_file_tools(self):
        """Coordinator should NOT have file operation tools."""
        assert "read_file" not in COORDINATOR_ALLOWED_TOOLS
        assert "write_file" not in COORDINATOR_ALLOWED_TOOLS
        assert "edit_file" not in COORDINATOR_ALLOWED_TOOLS
        assert "run_shell" not in COORDINATOR_ALLOWED_TOOLS

    def test_has_communication_tools(self):
        assert "send_message" in COORDINATOR_ALLOWED_TOOLS
        assert "read_inbox" in COORDINATOR_ALLOWED_TOOLS
        assert "broadcast" in COORDINATOR_ALLOWED_TOOLS

    def test_prompt_mentions_rules(self):
        config = get_coordinator_config()
        prompt = config["system_prompt"]
        assert "CANNOT modify files" in prompt
        assert "MUST delegate" in prompt
