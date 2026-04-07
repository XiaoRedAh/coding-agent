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
from bootstrap.state import SKILLS_DIR, PROJECT_DIR, WORKDIR
from tools.TodoTool import TodoManager
from services.tasks import TaskManager
from services.background import BackgroundManager
from services.bus import MessageBus
from agents.team import TeammateManager
from skills.loader import SkillLoader
from services.permissions import PermissionRules
from services.mcp import McpManager
from services.memory import MemoryManager
from services.llm import LLMAdapter
from agents.task_queue import AgentTaskQueue
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
    # LLM 适配器（支持 Anthropic 和 OpenAI 格式）
    state.llm = LLMAdapter.from_env()
    print(f"[LLM] provider={state.llm.provider}, model={state.llm.model}")

    state.todo = TodoManager()
    # 多层技能来源（对齐 cc 的优先级：项目级 > 配置级 > 用户级）
    user_skills_dir = Path.home() / ".xiaoagent" / "skills"
    state.skills = SkillLoader(SKILLS_DIR, PROJECT_DIR / "skills", user_skills_dir)
    state.task_mgr = TaskManager()
    state.bg = BackgroundManager()
    state.bus = MessageBus()
    state.team = TeammateManager(state.bus, state.task_mgr)
    state.perm_rules = PermissionRules()
    state.perm_rules.load_from_settings()
    state.mcp = McpManager()
    state.mcp.load_and_connect()
    state.memory = MemoryManager()
    state.agent_tasks = AgentTaskQueue()


def main():
    """程序入口：初始化 → 启动 REPL → 清理"""
    init()
    try:
        run_repl()
    finally:
        # 优雅关闭 MCP 连接
        if state.mcp:
            state.mcp.close_all()


if __name__ == "__main__":
    main()
