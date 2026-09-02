"""Custom role/agent registry loader for workflow mode.

This module is intentionally isolated from built-in AGENT_DEFINITIONS.
It allows users to add custom role runtime metadata without mutating built-ins.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime import state as st

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


def load_custom_role_configs() -> dict[str, dict]:
    """加载用户自定义角色配置。

    目录：.xiaoagent/workflows/roles
    支持：json / yaml / yml
    返回：{role_name: role_config}
    """
    role_dir = st.PROJECT_DIR / "workflows" / "roles"
    if not role_dir.exists():
        return {}

    result: dict[str, dict] = {}

    # 先加载 JSON
    for file_path in role_dir.glob("*.json"):
        data = json.loads(file_path.read_text(encoding="utf-8"))
        if "name" in data:
            result[data["name"]] = data

    if yaml is not None:
        # 再加载 YAML，同名角色会覆盖前面的结果
        for file_path in list(role_dir.glob("*.yaml")) + list(role_dir.glob("*.yml")):
            data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "name" in data:
                result[data["name"]] = data

    return result
