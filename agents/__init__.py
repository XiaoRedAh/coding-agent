"""
agents 包 - 多 Agent 系统

三种编排模式：
1. Simple SubAgent — 同步执行的独立子代理（agents/subagent.py）
2. Coordinator — 主 Agent 模式切换为协调者（agents/coordinator.py）
3. Swarm Team — 持久化自主队友，对等通信（agents/team.py）

四种内置 Agent 类型：
- explore: 只读搜索专家
- plan: 结构化规划
- general: 通用执行
- verification: 对抗性验证
"""

from .definitions import get_agent_config, get_filtered_tools, AGENT_DEFINITIONS
from .subagent import run_subagent, run_subagent_async
from .coordinator import is_coordinator_mode, get_coordinator_config
from .team import TeammateManager

__all__ = [
    "get_agent_config", "get_filtered_tools", "AGENT_DEFINITIONS",
    "run_subagent",
    "is_coordinator_mode", "get_coordinator_config",
    "TeammateManager",
]
