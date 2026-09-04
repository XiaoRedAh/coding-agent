"""
context/builder.py - 运行时配置装配入口

集中装配主 Agent 的运行时配置：
- system prompt 选择（context/prompt.py 构建系统提示词）
- 工具定义与 handler 的收集（tools/ 全量 + MCP 动态）

只有一条装配路径（无模式分支）。
"""

from context.prompt import build_system_prompt
from tools import get_all_definitions, get_all_handlers


class PromptBuilder:
    """构建运行时 prompt 与工具配置。"""

    @staticmethod
    def build_runtime_config(all_defs: list, all_handlers: dict) -> dict:
        """
        构建主 Agent 运行时配置。

        Returns:
            {
                "system_prompt": str | list[dict],
                "tool_defs": list,
                "tool_handlers": dict,
            }
        """
        return {
            "system_prompt": build_system_prompt(),
            "tool_defs": all_defs,
            "tool_handlers": all_handlers,
        }
