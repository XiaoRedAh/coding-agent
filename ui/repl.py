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
from services.tracing import get_tracer

# REPL 内置斜杠命令（不与技能名冲突时优先按技能处理）
_BUILT_IN_SLASH = {"compact", "stats", "tasks", "skills", "edit"}


def _print_skills():
    """列出全部已注册技能（/skills 命令）。"""
    skills = getattr(state, "skills", None)
    if not skills or not skills.skills:
        print("(no skills installed)")
        return
    print("Installed skills (invoke with /<name> [args]):")
    for name, skill in skills.skills.items():
        desc = skill["meta"].get("description", "-")
        if len(desc) > 80:
            desc = desc[:77] + "..."
        print(f"  /{name}: {desc}")


def _read_multiline() -> str | None:
    """
    读取多行用户输入。

    规则：
    - 单行直接回车 → 提交（最常见场景，保持快速）
    - 输入中包含换行（粘贴多行） → 继续读取直到空行
    - /edit 命令 → 打开系统编辑器

    Returns:
        输入文本；空串表示"空提交"（调用方应重新提示）；
        None 表示 EOF / Ctrl+C（调用方应退出 REPL）。
    """
    try:
        first_line = input("\033[36mcoding-agent >> \033[0m")
    except (EOFError, KeyboardInterrupt):
        return None

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

    model = str(getattr(state, "MODEL", "") or "")
    print(f"\033[36m╭─ XiaoAgent\033[0m \033[90m({model})\033[0m")
    print("\033[36m╰─\033[0m \033[90m/skills list skills · /<skill> invoke · "
          "/stats session stats · /edit editor · /exit or /quit to quit\033[0m")

    # 逐轮增量转录：任何结束方式（q / 崩溃 / 关窗口 / Ctrl+C）都不丢对话
    transcript = _IncrementalTranscript()

    while True:
        query = _read_multiline()
        if query is None:  # EOF / Ctrl+C
            break
        if not query.strip():  # 空提交 → 重新提示，不退出
            continue
        # 退出指令：全词命令，单字母 q 误触率高（想打 quick/quiet 会丢会话）
        if query.strip().lower() in ("/exit", "/quit", "exit", "quit"):
            break

        # 特殊命令
        stripped = query.strip()
        if stripped == "/compact":
            if history:
                print("[manual compact via /compact]")
                history[:] = auto_compact(history, tracker)
                breaker.record_success()
            continue
        if stripped == "/stats":
            print(get_tracer().format_summary())
            if state.todo and state.todo.items:
                print(f"  Todos ({len(state.todo.items)} items):\n{state.todo.render()}")
            continue
        if stripped == "/tasks":
            print(state.task_mgr.list_all())
            continue
        if stripped == "/skills":
            _print_skills()
            continue
        if stripped == "/edit":
            query = _open_editor()
            if not query:
                continue
            print(f"\033[90m  (submitted {len(query)} chars)\033[0m")

        # 斜杠技能触发：/技能名 或 /技能名 参数...
        # （用户侧直达，不依赖 LLM 自主调用 load_skill）
        if stripped.startswith("/") and state.skills:
            parts = stripped[1:].split(None, 1)
            skill_name = parts[0]
            if skill_name in state.skills.skills:
                skill_args = parts[1] if len(parts) > 1 else ""
                content = state.skills.load(skill_name, skill_args)
                if content.startswith("Error:"):
                    print(f"\033[31m{content}\033[0m")
                    continue
                # 可观测性：斜杠触发与 load_skill 工具触发同事件类型，
                # invoked_via 区分来源（slash / tool）
                get_tracer().event(
                    "skill_load", turn=0, skill=skill_name,
                    args=skill_args[:100], invoked_via="slash",
                    content_chars=len(content))
                print(f"\033[90m[skill] {skill_name} loaded, executing...\033[0m")
                query = content
            elif skill_name in _BUILT_IN_SLASH:
                pass  # 内置命令已在上方处理，这里不会到达（防御）
            # 未知斜杠命令：不拦截，作为普通输入交给 LLM（避免误伤 /xxx 写法）

        msg = {"role": "user", "content": query}
        history.append(msg)
        tracker.track_new_message(msg)
        # 全局兜底：任何漏网异常（workflow 配置错误、未预见的 bug 等）
        # 只终结本次请求，会话历史保留，不崩溃 REPL
        saved_len = len(history)
        try:
            tracker, breaker = agent_loop(history, tracker, breaker)
        except KeyboardInterrupt:
            print("\n\033[33m[Interrupted] You can continue the conversation.\033[0m")
        except Exception as e:
            print(f"\n\033[31m[Agent error] {type(e).__name__}: {e}\033[0m")
            print("\033[33m[Session preserved. You can continue the conversation.\033[0m")
        finally:
            # 逐轮增量转录：本轮新增消息（含异常中断的部分）立即落盘
            transcript.append_new(history[saved_len - 1:])

        # 空转唤醒兜底：主循环结束后仍有滞留的后台任务通知时提示用户
        # （正常路径已被 wait_for_pending 闭环；此处覆盖中断/异常导致的提前退出）
        if state.agent_tasks and state.agent_tasks.get_in_flight() > 0:
            print("\033[33m[note] Background sub-agents are still running. "
                  "Their results will be delivered on your next message.\033[0m")
        print()

    # 增量转录已逐轮落盘；此处提示路径（空会话无文件）
    if transcript.path:
        print(f"\033[90m[transcript saved] {transcript.path}\033[0m")


class _IncrementalTranscript:
    """逐轮增量对话转录。

    每轮对话结束后把新增消息追加到 transcripts/conversation-*.jsonl，
    任何结束方式（/exit / 崩溃 / 直接关窗口 / Ctrl+C）都不丢已发生的对话。
    首次写入时创建文件；写失败静默（不影响主流程）。
    """

    def __init__(self):
        self._path = None
        self._written = 0

    @property
    def path(self):
        return self._path

    def append_new(self, messages: list) -> None:
        if not messages:
            return
        try:
            import json
            from datetime import datetime
            from runtime.state import TRANSCRIPT_DIR
            if self._path is None:
                TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
                self._path = TRANSCRIPT_DIR / (
                    f"conversation-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl")
            with open(self._path, "a", encoding="utf-8") as f:
                for msg in messages:
                    f.write(json.dumps(msg, default=str, ensure_ascii=False) + "\n")
                    self._written += 1
        except OSError:
            pass  # 转录失败不影响主流程
