"""
agents/registry.py - 统一 Agent 注册表（S6）

内置 Agent 类型与用户自定义 Agent 同构：都是 YAML 文件。
往 `.xiaoagent/agents/` 丢一个 yaml 即注册新的子 Agent 类型。

加载来源（优先级从低到高，同名后者覆盖前者）：
1. agents/builtins/*.yaml        内置类型（随项目分发）
2. ~/.xiaoagent/agents/*.yaml    用户全局
3. {workdir}/.xiaoagent/agents/*.yaml  项目级

YAML 格式（与内置定义完全一致）：
    name: my-agent              # 可省略（默认取文件名）
    description: 一句话描述
    when_to_use: 何时使用
    system_prompt: |
      完整的系统提示词
    allowed_tools: [read_file, list_files, grep_search]
    max_turns: 15
    background: false           # true 则始终后台运行

校验：缺失必填字段 / 类型不对 / 未知字段都会抛 ValueError（带文件定位）。
"""

from __future__ import annotations

import json
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

BUILTIN_AGENTS_DIR = Path(__file__).parent / "builtins"

# 必填字段及其类型
_REQUIRED_FIELDS = {
    "system_prompt": str,
    "allowed_tools": list,
    "max_turns": int,
}
# 全部合法字段
_VALID_FIELDS = {
    "name", "description", "when_to_use",
    "system_prompt", "allowed_tools", "max_turns", "background",
}


class AgentRegistry:
    """Agent 类型注册表（内置 + 用户自定义，统一 YAML 定义）。"""

    def __init__(self, builtin_dir=None, user_dir=None, project_dir=None,
                 extra_dirs=None):
        """
        Args:
            builtin_dir: 内置定义目录（默认 agents/builtins/）
            user_dir: 用户全局目录（默认 ~/.xiaoagent/agents/）
            project_dir: 项目级目录（默认 {workdir}/.xiaoagent/agents/）
            extra_dirs: 额外目录（测试注入用），优先级最高
        """
        sources = [
            builtin_dir or BUILTIN_AGENTS_DIR,
            user_dir or (Path.home() / ".xiaoagent" / "agents"),
            project_dir,
            *(extra_dirs or []),
        ]
        self._agents: dict[str, dict] = {}
        for source in sources:
            if source is not None:
                self._load_dir(Path(source))

    # ── 加载 ──

    def _load_dir(self, directory: Path):
        if not directory.exists():
            return
        for file_path in sorted(
            list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))
            + list(directory.glob("*.json"))
        ):
            config = self._parse_file(file_path)
            self._agents[config["name"]] = config

    def _parse_file(self, file_path: Path) -> dict:
        try:
            if file_path.suffix == ".json":
                data = json.loads(file_path.read_text(encoding="utf-8"))
            else:
                if yaml is None:
                    raise ValueError("PyYAML not installed, cannot load .yaml agent files")
                data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except (yaml.YAMLError if yaml else Exception) as e:
            raise ValueError(f"Invalid agent definition file {file_path}: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(
                f"Agent definition {file_path} must be a mapping, "
                f"got {type(data).__name__}")

        # name 默认取文件名主干
        data.setdefault("name", file_path.stem)

        # 未知字段检查（捕获拼写错误）
        unknown = set(data) - _VALID_FIELDS
        if unknown:
            raise ValueError(
                f"Agent definition {file_path}: unknown fields {sorted(unknown)} "
                f"(valid: {sorted(_VALID_FIELDS)})")

        # 必填字段与类型检查
        for field, expected in _REQUIRED_FIELDS.items():
            if field not in data:
                raise ValueError(f"Agent definition {file_path}: missing required field '{field}'")
            value = data[field]
            if expected is int and (not isinstance(value, int) or isinstance(value, bool)):
                raise ValueError(f"Agent definition {file_path}: '{field}' must be int")
            if expected is str and not isinstance(value, str):
                raise ValueError(f"Agent definition {file_path}: '{field}' must be str")
            if expected is list and not isinstance(value, list):
                raise ValueError(f"Agent definition {file_path}: '{field}' must be a list")
        if data["max_turns"] <= 0:
            raise ValueError(f"Agent definition {file_path}: 'max_turns' must be positive")

        # 规范化为既有配置结构
        return {
            "name": data["name"],
            "description": data.get("description", ""),
            "when_to_use": data.get("when_to_use", ""),
            "system_prompt": data["system_prompt"],
            "allowed_tools": frozenset(data["allowed_tools"]),
            "max_turns": data["max_turns"],
            "background": bool(data.get("background", False)),
        }

    # ── 查询 ──

    def get(self, agent_type: str) -> dict:
        """获取指定类型的配置（大小写不敏感），未知类型抛 ValueError。"""
        config = self._agents.get(agent_type.lower())
        if config is None:
            available = ", ".join(sorted(self._agents))
            raise ValueError(
                f"Unknown agent type '{agent_type}'. Available: {available}")
        return config

    def names(self) -> list[str]:
        """全部已注册的 agent 类型名。"""
        return sorted(self._agents)

    def as_dict(self) -> dict[str, dict]:
        """name -> config 的浅拷贝映射（兼容旧 AGENT_DEFINITIONS 形态）。"""
        return dict(self._agents)


# ──────────────────────────────────────────────
#  默认注册表（模块级单例，可重建）
# ──────────────────────────────────────────────

_default_registry: AgentRegistry | None = None

# 哨兵：区分"未传参（用默认）"与"显式 None（跳过该来源）"
_UNSET = object()


def _build_default_registry(project_dir=None) -> AgentRegistry:
    """按懒加载默认值构建注册表（内置 + 用户级 + 项目级）。"""
    if project_dir is None:
        from runtime import state as _state
        project_dir = _state.PROJECT_DIR / "agents"
    return AgentRegistry(project_dir=project_dir)


def default_registry() -> AgentRegistry:
    """获取默认注册表（懒构建：内置 + 用户级 + 项目级）。"""
    global _default_registry
    if _default_registry is None:
        _default_registry = _build_default_registry()
    return _default_registry


def rebuild_default(builtin_dir=_UNSET, user_dir=_UNSET, project_dir=_UNSET,
                    extra_dirs=_UNSET) -> AgentRegistry:
    """
    重建默认注册表。

    - 无参调用：按懒加载默认值重建（读取当前 state.PROJECT_DIR，配置变化后刷新用）
    - 传参调用：显式指定来源（None 表示跳过该来源，测试隔离用）
    """
    global _default_registry
    args = (builtin_dir, user_dir, project_dir, extra_dirs)
    if all(a is _UNSET for a in args):
        _default_registry = _build_default_registry()
    else:
        kwargs = {}
        if builtin_dir is not _UNSET:
            kwargs["builtin_dir"] = builtin_dir
        if user_dir is not _UNSET:
            kwargs["user_dir"] = user_dir
        if project_dir is not _UNSET:
            kwargs["project_dir"] = project_dir
        if extra_dirs is not _UNSET:
            kwargs["extra_dirs"] = extra_dirs
        _default_registry = AgentRegistry(**kwargs)
    return _default_registry
