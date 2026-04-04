"""
screens/repl.py - REPL 交互界面

提供交互式命令行界面，支持用户输入、特殊命令处理和输出渲染。
对应 Claude Code 源码中的 screens/REPL.tsx。
"""

import json

from bootstrap import state
from services.compact import auto_compact
from query import agent_loop


def run_repl():
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
            print(state.task_mgr.list_all())
            continue
        if query.strip() == "/team":
            print(state.team.list_all())
            continue
        if query.strip() == "/inbox":
            print(json.dumps(state.bus.read_inbox("lead"), indent=2))
            continue
        history.append({"role": "user", "content": query})
        agent_loop(history)
        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
