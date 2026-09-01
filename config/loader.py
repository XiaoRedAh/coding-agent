"""
config/loader.py - 分层配置加载器

配置优先级（低 → 高）：
1. config/defaults.yaml          内置默认
2. ~/.xiaoagent/config.yaml      用户全局覆盖
3. {cwd}/.xiaoagent/config.yaml  项目级覆盖
4. 环境变量                      XIAOAGENT__节__键（双下划线分层）

机密（API key）与模型选择仍通过 .env / 传统环境变量（LLM_PROVIDER、
MODEL_ID、MODEL_CONTEXT_WINDOW）注入，loader 会将它们并入 llm 节。

设计约束：
- 模块零副作用：本文件 import 时不读任何文件，只有 load_settings() 执行 IO
- Settings 为冻结 dataclass，全程序只读
"""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 环境变量覆盖前缀：XIAOAGENT__SECTION__KEY
_ENV_PREFIX = "XIAOAGENT__"

_CONFIG_DIR = Path(__file__).parent
_DEFAULTS_FILE = _CONFIG_DIR / "defaults.yaml"


# ──────────────────────────────────────────────
#  Settings 数据结构（与 defaults.yaml 一一对应）
# ──────────────────────────────────────────────

@dataclass(frozen=True)
class LLMSettings:
    provider: str = "anthropic"
    model_id: str = ""
    context_window: int = 200000
    max_output_tokens: int = 8000
    timeout_seconds: int = 300


@dataclass(frozen=True)
class LoopSettings:
    default_max_turns: int = 50
    subagent_max_turns: int = 30
    coordinator_max_turns: int = 20
    max_consecutive_tool_errors: int = 5
    max_consecutive_llm_errors: int = 3
    coordinator_wait_timeout: int = 120


@dataclass(frozen=True)
class CompactSettings:
    budget_threshold: float = 0.50
    snip_threshold: float = 0.60
    budget_tight_threshold: float = 0.70
    autocompact_threshold: float = 0.85
    warning_threshold: float = 0.82
    budget_normal_chars: int = 30000
    budget_tight_chars: int = 15000
    snip_keep_recent: int = 3
    microcompact_idle_seconds: int = 300
    max_autocompact_failures: int = 3
    post_compact_max_files: int = 5
    post_compact_max_tokens_per_file: int = 5000
    post_compact_skills_budget: int = 25000
    max_conversation_chars: int = 80000
    summary_max_tokens: int = 4096


@dataclass(frozen=True)
class RetrySettings:
    default_max_retries: int = 3
    prompt_too_long_max_retries: int = 2
    base_delay_ms: int = 1000
    max_delay_ms: int = 32000
    jitter_ratio: float = 0.25
    rate_limit_short_retry_ms: int = 20000
    rate_limit_cooldown_ms: int = 600000
    overload_max_retries: int = 3
    overload_base_delay_ms: int = 500


@dataclass(frozen=True)
class MCPSettings:
    tool_timeout: int = 120
    connect_timeout: int = 30


@dataclass(frozen=True)
class ShellSettings:
    default_timeout: int = 120


@dataclass(frozen=True)
class ToolSettings:
    max_result_chars: int = 50000
    list_files_max: int = 200
    grep_max_matches: int = 100
    grep_timeout: int = 10
    todo_max_items: int = 20
    skill_description_max_chars: int = 250


@dataclass(frozen=True)
class MemorySettings:
    max_index_lines: int = 200
    max_index_bytes: int = 25000
    max_memory_files: int = 200


@dataclass(frozen=True)
class ContextSettings:
    git_timeout: int = 3


@dataclass(frozen=True)
class PathSettings:
    project_dir_name: str = ".xiaoagent"
    tasks_dir_name: str = "tasks"
    transcripts_dir_name: str = "transcripts"
    memory_dir_name: str = "memory"
    settings_file_name: str = "settings.json"
    skills_dir_name: str = "skills"


@dataclass(frozen=True)
class Settings:
    llm: LLMSettings = field(default_factory=LLMSettings)
    loop: LoopSettings = field(default_factory=LoopSettings)
    compact: CompactSettings = field(default_factory=CompactSettings)
    retry: RetrySettings = field(default_factory=RetrySettings)
    mcp: MCPSettings = field(default_factory=MCPSettings)
    shell: ShellSettings = field(default_factory=ShellSettings)
    tools: ToolSettings = field(default_factory=ToolSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    context: ContextSettings = field(default_factory=ContextSettings)
    paths: PathSettings = field(default_factory=PathSettings)


# 节名 → dataclass 类型（用于构建和校验）
_SECTION_TYPES = {
    "llm": LLMSettings,
    "loop": LoopSettings,
    "compact": CompactSettings,
    "retry": RetrySettings,
    "mcp": MCPSettings,
    "shell": ShellSettings,
    "tools": ToolSettings,
    "memory": MemorySettings,
    "context": ContextSettings,
    "paths": PathSettings,
}

# 传统环境变量 → llm 节键（保持 .env 兼容）
_LEGACY_ENV_MAP = {
    "LLM_PROVIDER": ("llm", "provider"),
    "MODEL_ID": ("llm", "model_id"),
    "MODEL_CONTEXT_WINDOW": ("llm", "context_window"),
    "LLM_TIMEOUT_SECONDS": ("llm", "timeout_seconds"),
}


# ──────────────────────────────────────────────
#  合并与覆盖
# ──────────────────────────────────────────────

def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 中的值覆盖 base。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_yaml(path: Path) -> dict:
    """读取 yaml 文件；不存在返回空 dict；格式错误抛 ValueError。"""
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {path}: {e}") from e
    return data if isinstance(data, dict) else {}


def _collect_env_overrides(environ=None) -> dict:
    """
    收集环境变量覆盖。

    两种来源：
    1. XIAOAGENT__节__键=value（通用机制）
    2. 传统变量（LLM_PROVIDER 等，需调用方先 load .env）
    """
    env = environ if environ is not None else os.environ
    overrides: dict = {}

    # 通用前缀机制
    for raw_key, raw_value in env.items():
        if not raw_key.startswith(_ENV_PREFIX):
            continue
        rest = raw_key[len(_ENV_PREFIX):]
        parts = rest.lower().split("__")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            continue
        section, key = parts
        node = overrides.setdefault(section, {})
        if isinstance(node, dict):
            node[key] = _coerce_scalar(raw_value)

    # 传统变量（仅当对应键未被通用机制覆盖时生效）
    for env_name, (section, key) in _LEGACY_ENV_MAP.items():
        value = env.get(env_name)
        if value in (None, ""):
            continue
        node = overrides.setdefault(section, {})
        if isinstance(node, dict) and key not in node:
            node[key] = _coerce_scalar(value)

    return overrides


def _coerce_scalar(raw: str):
    """将环境变量字符串尽量转换为 int/float/bool。"""
    low = raw.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


# ──────────────────────────────────────────────
#  校验与构建
# ──────────────────────────────────────────────

def _validate(section: str, dataclass_cls, values: dict) -> None:
    """类型与范围校验，错配抛 ValueError（带定位信息）。"""
    hints = dataclass_cls.__dataclass_fields__
    for key, value in values.items():
        if key not in hints:
            raise ValueError(
                f"config[{section}]: unknown key '{key}' "
                f"(valid keys: {sorted(hints)})"
            )
        expected = hints[key].type
        # str 字段不接受数值（yaml 中误写 provider: 123 之类）
        if expected == "str" and not isinstance(value, str):
            raise ValueError(
                f"config[{section}].{key}: expected str, got {type(value).__name__}")
        if expected == "int" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(
                f"config[{section}].{key}: expected int, got {value!r}")
        if expected == "float" and not isinstance(value, (int, float)):
            raise ValueError(
                f"config[{section}].{key}: expected number, got {value!r}")

    # 范围校验：比例类阈值必须在 (0, 1]
    _RATIO_FIELDS = {
        ("compact", "budget_threshold"), ("compact", "snip_threshold"),
        ("compact", "budget_tight_threshold"), ("compact", "autocompact_threshold"),
        ("compact", "warning_threshold"), ("retry", "jitter_ratio"),
    }
    if (section, key) in _RATIO_FIELDS:
        for _ in ():  # pragma: no cover
            pass
    for (sec, fld) in _RATIO_FIELDS:
        if sec == section and fld in values:
            v = values[fld]
            if not (0 < v <= 1):
                raise ValueError(
                    f"config[{section}].{fld} must be in (0, 1], got {v}")

    # 超时/上限必须为正
    positive_hint = any(
        "timeout" in k or "max" in k or "budget" in k or "chars" in k
        or "ms" in k or "seconds" in k or "lines" in k or "bytes" in k
        or "items" in k or "files" in k or "recent" in k or "budget" in k
        or "tokens" in k or "turns" in k or "retries" in k or "window" in k
        for k in values
    )
    if positive_hint:
        for key, value in values.items():
            if isinstance(value, (int, float)) and value <= 0:
                raise ValueError(
                    f"config[{section}].{key} must be positive, got {value}")


def _build_section(section: str, values: dict):
    cls = _SECTION_TYPES[section]
    _validate(section, cls, values)
    return cls(**values)


def load_settings(workdir: Path = None, environ=None) -> Settings:
    """
    加载分层配置并构建冻结 Settings。

    Args:
        workdir: 工作目录（默认 Path.cwd()），用于定位项目级覆盖
        environ: 环境变量映射（默认 os.environ），测试可注入
    """
    workdir = workdir or Path.cwd()

    merged = _read_yaml(_DEFAULTS_FILE)
    for override_path in (
        Path.home() / ".xiaoagent" / "config.yaml",
        workdir / ".xiaoagent" / "config.yaml",
    ):
        merged = _deep_merge(merged, _read_yaml(override_path))

    env_overrides = _collect_env_overrides(environ)
    for section, values in env_overrides.items():
        if section not in _SECTION_TYPES:
            raise ValueError(
                f"env override references unknown section '{section}' "
                f"(valid: {sorted(_SECTION_TYPES)})")
        merged[section] = _deep_merge(merged.get(section, {}), values)

    # 未知顶层节直接报错（帮助用户发现拼写错误）
    for section in merged:
        if section not in _SECTION_TYPES:
            raise ValueError(
                f"config: unknown section '{section}' "
                f"(valid sections: {sorted(_SECTION_TYPES)})")

    sections = {
        name: _build_section(name, merged.get(name, {}))
        for name in _SECTION_TYPES
    }
    return Settings(**sections)
