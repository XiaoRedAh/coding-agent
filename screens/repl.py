"""
screens/repl.py - REPL 交互界面

提供交互式命令行界面，支持用户输入、特殊命令处理和输出渲染。
维护 TokenTracker 和 CircuitBreaker 跨多次 agent_loop 调用的状态。

对应 Claude Code 源码中的 screens/REPL.tsx。
"""

import json

from bootstrap import state
from services.compact import TokenTracker, CircuitBreaker, auto_compact
from query import agent_loop
from agents.coordinator import is_coordinator_mode


def run_repl():
    """
    REPL 主循环。

    支持命令：/compact, /tasks, /team, /inbox, q/exit
    """
    history = []
    tracker = TokenTracker()
    breaker = CircuitBreaker()

    if is_coordinator_mode():
        print("[Coordinator mode] You are the coordinator. Use agent tool to delegate work.")

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
                history[:] = auto_compact(history, tracker)
                breaker.record_success()
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

        msg = {"role": "user", "content": query}
        history.append(msg)
        tracker.track_new_message(msg)
        tracker, breaker = agent_loop(history, tracker, breaker)

        response_content = history[-1]["content"]
        if isinstance(response_content, list):
            for block in response_content:
                if hasattr(block, "text"):
                    print(block.text)
        print()
