#!/usr/bin/env python3
"""
main.py - 入口文件

Coding Agent 的唯一入口，负责：
1. 初始化所有全局单例实例
2. 组装工具注册表
3. 构建系统提示词
4. 运行 agent_loop（LLM 工具调用循环）
5. 提供 REPL 交互界面（支持 /compact /tasks /team /inbox 命令）
"""

import json
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中（支持 python main.py 直接运行）
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    WORKDIR, SKILLS_DIR, TOKEN_THRESHOLD,
    client, MODEL,
)
from planning.todo import TodoManager
from planning.tasks import TaskManager
from context.compression import estimate_tokens, microcompact, auto_compact
from context.skills import SkillLoader
from background.manager import BackgroundManager
from communication.bus import MessageBus
from agents.team import TeammateManager
from tools.definitions import get_tool_definitions
from tools.registry import get_tool_handlers


# === 初始化所有全局单例实例 ===
TODO = TodoManager()           # 内存待办清单
SKILLS = SkillLoader(SKILLS_DIR)  # 技能加载器
TASK_MGR = TaskManager()       # 持久化任务管理器
BG = BackgroundManager()       # 后台任务管理器
BUS = MessageBus()             # 消息总线
TEAM = TeammateManager(BUS, TASK_MGR)  # 团队管理器

# === 构建工具注册表和定义 ===
TOOL_HANDLERS = get_tool_handlers(TODO, SKILLS, TASK_MGR, BG, BUS, TEAM)
TOOLS = get_tool_definitions()

# === 系统提示词 ===
SYSTEM = (
    f"You are a coding agent at {WORKDIR}. Use tools to solve tasks.\n"
    f"Prefer task_create/task_update/task_list for multi-step work. "
    f"Use TodoWrite for short checklists.\n"
    f"Use task for subagent delegation. Use load_skill for specialized knowledge.\n"
    f"Skills: {SKILLS.descriptions()}"
)


def agent_loop(messages: list):
    """
    主代理循环：每轮执行压缩检查、后台通知、收件箱检查、LLM 调用、工具执行。

    循环持续进行直到 LLM 返回非工具调用的停止原因（即给出最终回答）。

    Args:
        messages: 对话消息列表（会被原地修改）
    """
    rounds_without_todo = 0
    while True:
        # === 压缩管道 ===
        # 微压缩：清除旧的工具结果
        microcompact(messages)
        # 自动压缩：token 超阈值时触发
        if estimate_tokens(messages) > TOKEN_THRESHOLD:
            print("[auto-compact triggered]")
            messages[:] = auto_compact(messages)

        # === 后台通知：获取已完成的后台任务结果 ===
        notifs = BG.drain()
        if notifs:
            txt = "\n".join(
                f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in notifs
            )
            messages.append({
                "role": "user",
                "content": f"<background-results>\n{txt}\n</background-results>",
            })

        # === 收件箱：检查 lead 的收件箱 ===
        inbox = BUS.read_inbox("lead")
        if inbox:
            messages.append({
                "role": "user",
                "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>",
            })

        # === LLM 调用 ===
        response = client.messages.create(
            model=MODEL,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        # 如果不是工具调用，则返回（LLM 给出了最终回答）
        if response.stop_reason != "tool_use":
            return

        # === 工具执行 ===
        results = []
        used_todo = False
        manual_compress = False
        for block in response.content:
            if block.type == "tool_use":
                if block.name == "compress":
                    manual_compress = True
                handler = TOOL_HANDLERS.get(block.name)
                try:
                    output = (
                        handler(**block.input)
                        if handler
                        else f"Unknown tool: {block.name}"
                    )
                except Exception as e:
                    output = f"Error: {e}"
                print(f"> {block.name}:")
                print(str(output)[:200])
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
                if block.name == "TodoWrite":
                    used_todo = True

        # === 待办提醒（nag reminder） ===
        rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
        if TODO.has_open_items() and rounds_without_todo >= 3:
            results.append({
                "type": "text",
                "text": "<reminder>Update your todos.</reminder>",
            })
        messages.append({"role": "user", "content": results})

        # === 手动压缩 ===
        if manual_compress:
            print("[manual compact]")
            messages[:] = auto_compact(messages)
            return


def main():
    """
    REPL 主循环：提供交互式命令行界面。

    支持的特殊命令：
    - /compact: 手动压缩对话上下文
    - /tasks: 显示所有持久化任务
    - /team: 显示所有队友状态
    - /inbox: 读取 lead 的收件箱
    - q / exit / 空行: 退出
    """
    history = []
    while True:
        try:
            query = input("\033[36mcoding-agent >> \033[0m")
        except (EOFError, KeyboardInterrupt):
            break
        if query.strip().lower() in ("q", "exit", ""):
            break
        if query.strip() == "/compact":
            if history:
                print("[manual compact via /compact]")
                history[:] = auto_compact(history)
            continue
        if query.strip() == "/tasks":
            print(TASK_MGR.list_all())
            continue
        if query.strip() == "/team":
            print(TEAM.list_all())
            continue
        if query.strip() == "/inbox":
            print(json.dumps(BUS.read_inbox("lead"), indent=2))
            continue
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()


if __name__ == "__main__":
    main()
