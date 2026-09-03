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

from runtime import state
from runtime.state import SKILLS_DIR, PROJECT_DIR, WORKDIR
from tools.TodoTool import TodoManager
from services.tasks import TaskManager
from services.background import BackgroundManager
from skills.loader import SkillLoader
from services.permissions import PermissionRules
from services.mcp import McpManager
from services.memory import MemoryManager
from llm.adapter import LLMAdapter
from agents.task_queue import AgentTaskQueue
from ui.console import setup_console
from ui.repl import run_repl


def init():
    """
    初始化所有全局单例实例，写入 runtime.state 模块。

    初始化顺序：
    1. LLM 适配器 - 语言模型客户端
    2. TodoManager - 内存待办清单
    3. SkillLoader - 技能文件加载
    4. TaskManager - 持久化任务管理
    5. BackgroundManager - 后台任务管理
    6. PermissionRules - 权限规则
    7. McpManager - MCP 服务器管理
    8. MemoryManager - 记忆管理
    9. AgentTaskQueue - Agent 任务队列
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
    state.perm_rules = PermissionRules()
    state.perm_rules.load_from_settings()
    state.mcp = McpManager()
    state.mcp.load_and_connect()
    state.memory = MemoryManager()
    state.agent_tasks = AgentTaskQueue()


def main():
    """程序入口：初始化 → 启动 REPL → 清理"""
    setup_console()  # Windows conhost 启用 VT 颜色处理（否则 ANSI 码显示为方块）
    init()
    try:
        run_repl()
    finally:
        # 优雅关闭 MCP 连接
        if state.mcp:
            state.mcp.close_all()


if __name__ == "__main__":
    main()
