"""
ui/render.py - 终端渲染（S4 从 query.py 拆出）

全部终端 UI 逻辑集中于此：等待动画（spinner）、工具结果打印、
权限确认交互、Agent 启动横幅。核心循环（core/loop.py）不直接
print 任何内容，而是通过钩子回调到这里。
"""

from __future__ import annotations

import json
import sys
import threading
import time


# ──────────────────────────────────────────────
#  等待动画（LLM 响应前的加载指示）
# ──────────────────────────────────────────────

class Spinner:
    """终端加载动画，在后台线程中运行。显示已等待秒数，便于区分"慢"与"卡死"。"""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        self._active = False
        self._thread = None

    def start(self):
        self._active = True
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._active = False
        if self._thread:
            self._thread.join(timeout=1)
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()

    def _spin(self):
        i = 0
        start = time.time()
        while self._active:
            frame = self.FRAMES[i % len(self.FRAMES)]
            elapsed = int(time.time() - start)
            sys.stdout.write(f"\r\033[90m{frame} thinking... ({elapsed}s)\033[0m")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1


# ──────────────────────────────────────────────
#  权限确认
# ──────────────────────────────────────────────

def print_permission_detail(tool_name: str, tool_input: dict) -> None:
    """打印权限确认时的操作详情。"""
    if tool_name == "run_shell":
        cmd = tool_input.get("command", "")
        bg = tool_input.get("run_in_background", False)
        suffix = " (background)" if bg else ""
        print(f"  \033[93m⚠ Shell command{suffix}:\033[0m {cmd}")
    elif tool_name == "write_file":
        path = tool_input.get("file_path", "")
        size = len(tool_input.get("content", ""))
        print(f"  \033[93m⚠ Write file:\033[0m {path} ({size} bytes)")
    elif tool_name == "edit_file":
        path = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")[:50]
        print(f"  \033[93m⚠ Edit file:\033[0m {path} (replace: \"{old}...\")")
    elif tool_name == "agent":
        atype = tool_input.get("type", "general")
        desc = tool_input.get("description", "")
        name = tool_input.get("name", "")
        if name:
            print(f"  \033[93m⚠ Create teammate:\033[0m {name} (type={atype})")
        else:
            print(f"  \033[93m⚠ Launch sub-agent:\033[0m [{atype}] {desc}")
    else:
        print(f"  \033[93m⚠ {tool_name}:\033[0m {json.dumps(tool_input, ensure_ascii=False)[:120]}")


def confirm_action() -> bool:
    """交互式确认，返回用户是否允许。"""
    try:
        answer = input("  Allow? (y/n): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer.startswith("y")


# ──────────────────────────────────────────────
#  工具与 Agent 执行的展示
# ──────────────────────────────────────────────

def print_tool_result(tool_name: str, output) -> None:
    """打印工具执行结果摘要。"""
    print(f"\033[32m  > {tool_name}\033[0m")
    print(f"    {str(output)[:200]}")


def print_agent_start(tool_input: dict) -> None:
    """打印 SubAgent / Teammate 启动横幅。"""
    atype = tool_input.get("type", "general")
    desc = tool_input.get("description", "")
    name = tool_input.get("name", "")
    if name:
        print(f"\033[35m  ┌─ Teammate [{atype}]: {name}\033[0m")
    else:
        bg = tool_input.get("run_in_background", False)
        mode = "async" if bg else "sync"
        print(f"\033[35m  ┌─ SubAgent [{atype}] ({mode}): {desc}\033[0m")


def print_agent_done() -> None:
    """打印 Agent 完成标记。"""
    print(f"\033[35m  └─ done\033[0m")
