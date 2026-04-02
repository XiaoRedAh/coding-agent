"""
agents 包 - 代理管理

包含子代理（subagent）和团队队友（teammate）的管理功能：
- subagent: 一次性子代理，执行隔离的探索或工作任务
- team: 持久化自主队友，支持工作/空闲/关闭生命周期
"""

from .subagent import run_subagent
from .team import TeammateManager

__all__ = ["run_subagent", "TeammateManager"]
