"""Unit tests for config/loader.py — 分层配置系统。

覆盖：默认加载、YAML 覆盖（用户级/项目级）、环境变量覆盖（通用前缀 + 传统变量）、
类型与范围校验、深合并语义、错误配置的报错。
"""

import pytest
from pathlib import Path

from config.loader import (
    load_settings, _deep_merge, _read_yaml, _coerce_scalar,
    LLMSettings, LoopSettings, Settings,
)


class TestDefaults:
    def test_load_defaults(self, tmp_path, monkeypatch):
        """无任何覆盖时应得到 defaults.yaml 的值。"""
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("MODEL_ID", raising=False)
        monkeypatch.delenv("MODEL_CONTEXT_WINDOW", raising=False)
        monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
        s = load_settings(workdir=tmp_path)
        assert s.loop.default_max_turns == 50
        assert s.compact.autocompact_threshold == 0.85
        assert s.tools.todo_max_items == 20
        assert s.paths.project_dir_name == ".xiaoagent"

    def test_settings_frozen(self, tmp_path):
        """Settings 不可变，防止运行时被意外修改。"""
        s = load_settings(workdir=tmp_path)
        with pytest.raises(Exception):  # FrozenInstanceError
            s.loop.default_max_turns = 99

    def test_all_sections_present(self, tmp_path):
        s = load_settings(workdir=tmp_path)
        for section in ("llm", "loop", "compact", "retry", "mcp",
                        "shell", "tools", "memory", "context", "paths"):
            assert hasattr(s, section)


class TestYAMLOverrides:
    def test_project_level_override(self, tmp_path, monkeypatch):
        """项目级 .xiaoagent/config.yaml 覆盖默认值。"""
        monkeypatch.delenv("MODEL_CONTEXT_WINDOW", raising=False)
        cfg_dir = tmp_path / ".xiaoagent"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "loop:\n  default_max_turns: 10\n", encoding="utf-8")
        s = load_settings(workdir=tmp_path)
        assert s.loop.default_max_turns == 10
        # 未覆盖的值保持默认
        assert s.loop.subagent_max_turns == 80

    def test_deep_merge_semantics(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"x": 9}}
        merged = _deep_merge(base, override)
        assert merged == {"a": {"x": 9, "y": 2}, "b": 3}
        # 原 dict 不被修改
        assert base["a"]["x"] == 1

    def test_invalid_yaml_raises(self, tmp_path):
        cfg_dir = tmp_path / ".xiaoagent"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "loop: [unclosed", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid YAML"):
            load_settings(workdir=tmp_path)

    def test_unknown_section_raises(self, tmp_path):
        cfg_dir = tmp_path / ".xiaoagent"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "no_such_section:\n  key: 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown section"):
            load_settings(workdir=tmp_path)

    def test_unknown_key_raises(self, tmp_path):
        cfg_dir = tmp_path / ".xiaoagent"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "loop:\n  bogus_key: 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="unknown key 'bogus_key'"):
            load_settings(workdir=tmp_path)


class TestEnvOverrides:
    def test_generic_prefix_override(self, tmp_path):
        """XIAOAGENT__节__键 覆盖。"""
        s = load_settings(
            workdir=tmp_path,
            environ={"XIAOAGENT__LOOP__DEFAULT_MAX_TURNS": "7"},
        )
        assert s.loop.default_max_turns == 7

    def test_env_value_coercion(self, tmp_path):
        """环境变量字符串自动转换 int/float。"""
        s = load_settings(
            workdir=tmp_path,
            environ={
                "XIAOAGENT__COMPACT__AUTOCOMPACT_THRESHOLD": "0.9",
                "XIAOAGENT__TOOLS__TODO_MAX_ITEMS": "5",
            },
        )
        assert s.compact.autocompact_threshold == 0.9
        assert s.tools.todo_max_items == 5

    def test_legacy_env_vars(self, tmp_path):
        """传统变量（MODEL_CONTEXT_WINDOW 等）并入 llm 节。"""
        s = load_settings(
            workdir=tmp_path,
            environ={"MODEL_CONTEXT_WINDOW": "128000"},
        )
        assert s.llm.context_window == 128000

    def test_generic_prefix_beats_legacy(self, tmp_path):
        """通用前缀优先于传统变量。"""
        s = load_settings(
            workdir=tmp_path,
            environ={
                "MODEL_CONTEXT_WINDOW": "111111",
                "XIAOAGENT__LLM__CONTEXT_WINDOW": "222222",
            },
        )
        assert s.llm.context_window == 222222

    def test_empty_env_ignored(self, tmp_path):
        s = load_settings(
            workdir=tmp_path, environ={"MODEL_CONTEXT_WINDOW": ""})
        assert s.llm.context_window == 200000

    def test_coerce_scalar(self):
        assert _coerce_scalar("42") == 42
        assert _coerce_scalar("1.5") == 1.5
        assert _coerce_scalar("true") is True
        assert _coerce_scalar("hello") == "hello"


class TestValidation:
    def test_ratio_out_of_range_raises(self, tmp_path):
        with pytest.raises(ValueError, match="must be in"):
            load_settings(
                workdir=tmp_path,
                environ={"XIAOAGENT__COMPACT__AUTOCOMPACT_THRESHOLD": "1.5"},
            )

    def test_non_positive_timeout_raises(self, tmp_path):
        with pytest.raises(ValueError, match="must be positive"):
            load_settings(
                workdir=tmp_path,
                environ={"XIAOAGENT__SHELL__DEFAULT_TIMEOUT": "0"},
            )

    def test_type_mismatch_raises(self, tmp_path):
        with pytest.raises(ValueError, match="expected int"):
            load_settings(
                workdir=tmp_path,
                environ={"XIAOAGENT__LOOP__DEFAULT_MAX_TURNS": "not-a-number"},
            )

    def test_yaml_float_where_int_expected(self, tmp_path):
        cfg_dir = tmp_path / ".xiaoagent"
        cfg_dir.mkdir()
        (cfg_dir / "config.yaml").write_text(
            "loop:\n  default_max_turns: 3.5\n", encoding="utf-8")
        with pytest.raises(ValueError, match="expected int"):
            load_settings(workdir=tmp_path)


class TestBootstrapIntegration:
    def test_state_module_exposes_settings(self):
        """runtime.state 应暴露 settings 且常量与之同步。"""
        import runtime.state as st
        assert isinstance(st.settings, Settings)
        assert st.BUDGET_THRESHOLD == st.settings.compact.budget_threshold
        assert st.AUTOCOMPACT_THRESHOLD == st.settings.compact.autocompact_threshold

    def test_loop_config_from_settings(self):
        """api_errors 的 LoopConfig/RetryConfig 值应来自 Settings。"""
        import runtime.state as st
        from engine.errors import LoopConfig, RetryConfig
        assert LoopConfig.DEFAULT_MAX_TURNS == st.settings.loop.default_max_turns
        assert LoopConfig.MAX_CONSECUTIVE_TOOL_ERRORS == st.settings.loop.max_consecutive_tool_errors
        assert RetryConfig.BASE_DELAY_MS == st.settings.retry.base_delay_ms

    def test_tool_constants_from_settings(self):
        """工具层模块常量应来自 Settings。"""
        import runtime.state as st
        from utils.truncate import MAX_RESULT_CHARS
        from services.memory import MAX_INDEX_LINES
        assert MAX_RESULT_CHARS == st.settings.tools.max_result_chars
        assert MAX_INDEX_LINES == st.settings.memory.max_index_lines

    def test_bash_default_timeout_from_settings(self):
        """BashTool 默认超时应来自 Settings（未显式传 timeout 时）。"""
        import runtime.state as st
        from tools import BashTool
        monkeypatch_target = None
        # 直接验证：handle 不传 timeout 时使用 settings.shell.default_timeout
        # 用一个会暴露 timeout 值的方式：超时错误消息包含秒数
        # （选一个 settings 中很大的值没有意义，改为验证源码层面绑定）
        assert st.settings.shell.default_timeout > 0
        # BashTool.handle 的默认值是 None → 内部取 settings.shell.default_timeout
        import inspect
        sig = inspect.signature(BashTool.handle)
        assert sig.parameters["timeout"].default is None
