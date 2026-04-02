"""
background 包 - 后台任务管理

提供后台命令执行功能，支持异步运行 shell 命令并通过通知队列获取结果。
"""

from .manager import BackgroundManager

__all__ = ["BackgroundManager"]
