"""
agents 包 - 多 Agent 系统

编排模式：
1. Simple SubAgent — 同步执行的独立子代理
2. Async SubAgent — 异步执行，通过 AgentTaskQueue 通知
3. Team — 持久化队友（通过 AgentTool name 参数创建）
4. Coordinator — 主 Agent 模式切换

所有 Agent 创建统一通过 AgentTool 入口。
"""

from .definitions import get_agent_config, get_filtered_tools, AGENT_DEFINITIONS
from .subagent import run_subagent, run_subagent_async
from .coordinator import is_coordinator_mode, get_coordinator_config
from .task_queue import AgentTaskQueue
from .team import TeammateManager

__all__ = [
    "get_agent_config", "get_filtered_tools", "AGENT_DEFINITIONS",
    "run_subagent", "run_subagent_async",
    "is_coordinator_mode", "get_coordinator_config",
    "AgentTaskQueue",
    "TeammateManager",
]
