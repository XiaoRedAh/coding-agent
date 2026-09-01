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
        # 当前提示词定位为 Orchestrator（项目管理者）
        assert "Orchestrator" in config["system_prompt"]

    def test_has_allowed_tools(self):
        config = get_coordinator_config()
        assert "allowed_tools" in config

    def test_agent_in_allowed(self):
        assert "agent" in COORDINATOR_ALLOWED_TOOLS

    def test_no_write_tools(self):
        """Coordinator 不应有写文件工具（不直接修改文件，全部委托 Worker）。"""
        assert "write_file" not in COORDINATOR_ALLOWED_TOOLS
        assert "edit_file" not in COORDINATOR_ALLOWED_TOOLS

    def test_has_readonly_investigation_tools(self):
        """Coordinator 保留只读调研工具（用于规划前的分析）。"""
        assert "read_file" in COORDINATOR_ALLOWED_TOOLS
        assert "list_files" in COORDINATOR_ALLOWED_TOOLS
        assert "grep_search" in COORDINATOR_ALLOWED_TOOLS

    def test_prompt_mentions_rules(self):
        config = get_coordinator_config()
        prompt = config["system_prompt"]
        # 当前提示词的关键行为规则
        assert "delegates to Workers" in prompt  # 必须委托
        assert "independent" in prompt.lower()  # 子任务必须独立
        assert "PARALLEL" in prompt  # 并行执行指引
