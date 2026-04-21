"""
services/prompt_builder.py - 统一系统提示词与工具装配入口

集中管理 normal/coordinator 模式下的：
- system prompt 选择
- 工具白名单过滤
"""

from context import build_system_prompt
from agents.coordinator import is_coordinator_mode, get_coordinator_config


class PromptBuilder:
    """构建运行时 prompt 与工具配置。"""

    @staticmethod
    def build_runtime_config(all_defs: list, all_handlers: dict) -> dict:
        """
        基于当前模式构建运行时配置。

        Returns:
            {
                "system_prompt": str | list[dict],
                "tool_defs": list,
                "tool_handlers": dict,
                "coordinator_mode": bool,
            }
        """
        coordinator_mode = is_coordinator_mode()

        if coordinator_mode:
            coord_config = get_coordinator_config()
            allowed = coord_config["allowed_tools"]
            return {
                "system_prompt": coord_config["system_prompt"],
                "tool_defs": [d for d in all_defs if d["name"] in allowed],
                "tool_handlers": {k: v for k, v in all_handlers.items() if k in allowed},
                "coordinator_mode": True,
            }

        return {
            "system_prompt": build_system_prompt(),
            "tool_defs": all_defs,
            "tool_handlers": all_handlers,
            "coordinator_mode": False,
        }
