#!/usr/bin/env python3
"""
main.py - CLI 主入口

Coding Agent 的唯一入口，负责：
1. 初始化所有全局单例实例（写入 bootstrap/state.py）
2. 分发到 REPL 交互界面

对应 Claude Code 源码中的 main.tsx + entrypoints/init.ts。
"""

import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))

from bootstrap import state
from bootstrap.state import SKILLS_DIR
from tools.TodoTool import TodoManager
from services.tasks import TaskManager
from services.background import BackgroundManager
from services.bus import MessageBus
from agents.team import TeammateManager
from skills.loader import SkillLoader
from services.permissions import PermissionRules
from screens.repl import run_repl


def init():
    """
    初始化所有全局单例实例，写入 bootstrap.state 模块。

    初始化顺序：
    1. TodoManager - 内存待办清单
    2. SkillLoader - 技能文件加载
    3. TaskManager - 持久化任务管理
    4. BackgroundManager - 后台任务管理
    5. MessageBus - 消息总线
    6. TeammateManager - 团队管理（依赖 bus 和 task_mgr）
    """
    state.todo = TodoManager()
    state.skills = SkillLoader(SKILLS_DIR)
    state.task_mgr = TaskManager()
    state.bg = BackgroundManager()
    state.bus = MessageBus()
    state.team = TeammateManager(state.bus, state.task_mgr)
    state.perm_rules = PermissionRules()
    state.perm_rules.load_from_settings()


def main():
    """程序入口：初始化 → 启动 REPL"""
    init()
    run_repl()


if __name__ == "__main__":
    main()
