"""
screens/repl.py - REPL 交互界面

提供交互式命令行界面，支持：
- 多行输入（空行结束，或 /edit 打开编辑器）
- 流式输出 + 等待动画
- SubAgent 状态展示
- 权限确认（含操作详情）
"""

import sys
import os
import tempfile
import subprocess

# readline 让 input() 支持退格键、方向键、输入历史（↑↓）
try:
    import readline  # noqa: F401 — 导入即生效，不需要显式调用
except ImportError:
    pass  # Windows 上可能没有 readline，但 pyreadline3 可以替代

from runtime import state
from context.compact import TokenTracker, CircuitBreaker, auto_compact
from agents.session import agent_loop
from agents.coordinator import is_coordinator_mode


def _read_multiline() -> str:
    """
    读取多行用户输入。

    规则：
    - 单行直接回车 → 提交（最常见场景，保持快速）
    - 输入中包含换行（粘贴多行） → 继续读取直到空行
    - /edit 命令 → 打开系统编辑器
    """
    try:
        first_line = input("\033[36mcoding-agent >> \033[0m")
    except (EOFError, KeyboardInterrupt):
        return ""

    # 单行直接返回
    if not sys.stdin.isatty():
        return first_line

    # 检查是否有更多数据（粘贴多行时 stdin 有缓冲）
    import select
    if hasattr(select, "select"):
        try:
            readable, _, _ = select.select([sys.stdin], [], [], 0.05)
            if readable:
                # 有更多数据 → 多行模式
                lines = [first_line]
                print("\033[90m  (multi-line mode: empty line to submit)\033[0m")
                while True:
                    try:
                        line = input("\033[90m  ... \033[0m")
                    except (EOFError, KeyboardInterrupt):
                        break
                    if line.strip() == "":
                        break
                    lines.append(line)
                return "\n".join(lines)
        except (OSError, ValueError):
            pass

    return first_line


def _open_editor() -> str:
    """打开系统编辑器（$EDITOR 或 nano/vi）编辑多行输入。"""
    editor = os.environ.get("EDITOR", "nano")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write("# Enter your prompt below (save and close to submit)\n\n")
        tmpfile = f.name
    try:
        subprocess.run([editor, tmpfile])
        with open(tmpfile, "r", encoding="utf-8") as f:
            content = f.read()
        # 移除注释行
        lines = [l for l in content.splitlines() if not l.startswith("#")]
        return "\n".join(lines).strip()
    except Exception as e:
        print(f"  Editor error: {e}")
        return ""
    finally:
        try:
            os.unlink(tmpfile)
        except OSError:
            pass


def run_repl():
    """REPL 主循环。"""
    history = []
    tracker = TokenTracker()
    breaker = CircuitBreaker()

    if is_coordinator_mode():
        print("[Coordinator mode] Use agent tool to delegate work.")

    print("\033[90mTips: /edit for multi-line editor | /compact to compress | q to quit\033[0m")

    while True:
        query = _read_multiline()
        if not query or query.strip().lower() in ("q", "exit"):
            break

        # 特殊命令
        stripped = query.strip()
        if stripped == "/compact":
            if history:
                print("[manual compact via /compact]")
                history[:] = auto_compact(history, tracker)
                breaker.record_success()
            continue
        if stripped == "/tasks":
            print(state.task_mgr.list_all())
            continue
        if stripped == "/edit":
            query = _open_editor()
            if not query:
                continue
            print(f"\033[90m  (submitted {len(query)} chars)\033[0m")

        msg = {"role": "user", "content": query}
        history.append(msg)
        tracker.track_new_message(msg)
        tracker, breaker = agent_loop(history, tracker, breaker)
        print()
