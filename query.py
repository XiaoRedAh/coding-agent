"""
query.py - 核心查询循环

管理单次查询的完整生命周期状态机：
    压缩管道(L1-L3) → 通知 → LLM 调用（流式+等待动画）→ 权限检查 → 工具执行
"""

import json
import sys
import threading
import time

from bootstrap import state
from bootstrap.state import WARNING_THRESHOLD
from services.compact import (
    TokenTracker, CircuitBreaker,
    run_compression_pipeline, check_and_compact,
)
from tools import get_all_definitions, get_all_handlers
from context import build_system_prompt
from agents.coordinator import is_coordinator_mode, get_coordinator_config
from services.permissions import check_permission
from services.api_errors import LoopConfig, LLMError, APIRetryExhaustedError


# ──────────────────────────────────────────────
#  等待动画（LLM 响应前的加载指示）
# ──────────────────────────────────────────────

class _Spinner:
    """简单的终端加载动画，在后台线程中运行。"""
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
        while self._active:
            frame = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r\033[90m{frame} thinking...\033[0m")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1


_spinner = _Spinner()


# ──────────────────────────────────────────────
#  权限确认（展示操作详情）
# ──────────────────────────────────────────────

def _format_permission_detail(tool_name: str, tool_input: dict) -> str:
    """生成权限确认时的操作详情描述。"""
    if tool_name == "run_shell":
        cmd = tool_input.get("command", "")
        bg = tool_input.get("run_in_background", False)
        suffix = " (background)" if bg else ""
        return f"  \033[93m⚠ Shell command{suffix}:\033[0m {cmd}"
    if tool_name == "write_file":
        path = tool_input.get("file_path", "")
        size = len(tool_input.get("content", ""))
        return f"  \033[93m⚠ Write file:\033[0m {path} ({size} bytes)"
    if tool_name == "edit_file":
        path = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")[:50]
        return f"  \033[93m⚠ Edit file:\033[0m {path} (replace: \"{old}...\")"
    if tool_name == "agent":
        atype = tool_input.get("type", "general")
        desc = tool_input.get("description", "")
        name = tool_input.get("name", "")
        if name:
            return f"  \033[93m⚠ Create teammate:\033[0m {name} (type={atype})"
        return f"  \033[93m⚠ Launch sub-agent:\033[0m [{atype}] {desc}"
    return f"  \033[93m⚠ {tool_name}:\033[0m {json.dumps(tool_input, ensure_ascii=False)[:120]}"


# ──────────────────────────────────────────────
#  Agent Loop
# ──────────────────────────────────────────────

def agent_loop(
    messages: list,
    tracker: TokenTracker = None,
    breaker: CircuitBreaker = None,
    max_turns: int = None,
):
    """主代理循环（流式输出 + 等待动画 + 权限详情 + 循环保护）。"""
    if tracker is None:
        tracker = TokenTracker()
    if breaker is None:
        breaker = CircuitBreaker()
    if max_turns is None:
        max_turns = LoopConfig.DEFAULT_MAX_TURNS

    all_defs = get_all_definitions()
    all_handlers = get_all_handlers()

    if is_coordinator_mode():
        coord_config = get_coordinator_config()
        system_prompt = coord_config["system_prompt"]
        allowed = coord_config["allowed_tools"]
        tool_defs = [d for d in all_defs if d["name"] in allowed]
        tool_handlers = {k: v for k, v in all_handlers.items() if k in allowed}
    else:
        system_prompt = build_system_prompt()
        tool_defs = all_defs
        tool_handlers = all_handlers

    rounds_without_todo = 0
    turn_count = 0
    consecutive_llm_errors = 0
    
    while True:
        turn_count += 1

        # ── 循环保护：maxTurns 限制 ──
        if turn_count > max_turns:
            print(f"\033[31m[Agent] Reached max turns ({max_turns}), stopping.\033[0m")
            return tracker, breaker

        # ── 循环保护：连续 LLM 错误计数 ──
        if consecutive_llm_errors >= LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS:
            print(f"\033[31m[Agent] Consecutive error limit reached, stopping.\033[0m")
            return tracker, breaker

        run_compression_pipeline(messages, tracker)

        utilization = tracker.get_utilization()
        if utilization >= WARNING_THRESHOLD:
            print(f"\033[33m[context at {utilization:.0%}]\033[0m")

        # 后台 Shell 通知
        bg_notifs = state.bg.drain()
        if bg_notifs:
            txt = "\n".join(f"[bg:{n['task_id']}] {n['status']}: {n['result']}" for n in bg_notifs)
            msg = {"role": "user", "content": f"<background-results>\n{txt}\n</background-results>"}
            messages.append(msg)
            tracker.track_new_message(msg)

        # 异步 Agent 通知
        if state.agent_tasks:
            agent_notifs = state.agent_tasks.drain()
            if agent_notifs:
                parts = []
                for n in agent_notifs:
                    print(f"\033[35m  ✓ Agent [{n['agent_type']}] {n['status']}\033[0m")
                    parts.append(
                        f"<task-notification>\n"
                        f"  <task-id>{n['task_id']}</task-id>\n"
                        f"  <type>{n['agent_type']}</type>\n"
                        f"  <status>{n['status']}</status>\n"
                        f"  <result>{n['result']}</result>\n"
                        f"</task-notification>"
                    )
                msg = {"role": "user", "content": "\n".join(parts)}
                messages.append(msg)
                tracker.track_new_message(msg)

        # 收件箱
        inbox = state.bus.read_inbox("lead")
        if inbox:
            msg = {"role": "user", "content": f"<inbox>{json.dumps(inbox, indent=2)}</inbox>"}
            messages.append(msg)
            tracker.track_new_message(msg)

        # === LLM 调用（流式 + spinner） ===
        first_token_received = False

        def _on_text(delta):
            nonlocal first_token_received
            if not first_token_received:
                _spinner.stop()
                first_token_received = True
            print(delta, end="", flush=True)

        _spinner.start()
        try:
            print(f"\033[90m[turn {turn_count}] calling llm.chat (stream=True)\033[0m", flush=True)
            response = state.llm.chat(
                system_prompt, messages, tool_defs,
                stream=True, on_text=_on_text,
            )
            print(f"\033[90m[turn {turn_count}] llm.chat returned, stop_reason={response.stop_reason}, blocks={len(response.content)}\033[0m", flush=True)
        except (LLMError, APIRetryExhaustedError) as e:
            _spinner.stop()
            import traceback
            print(f"\033[31m[Agent] LLM ERROR: type={type(e).__name__}, error_type={getattr(e, 'error_type', None)}, msg={e}\033[0m", flush=True)
            print(f"\033[31m[Agent] Traceback: {traceback.format_exc()[-500:]}\033[0m", flush=True)
            consecutive_llm_errors += 1
            print(f"\033[31m[Agent] LLM error ({e.error_type.value if hasattr(e, 'error_type') and e.error_type else 'unknown'}): {e}\033[0m")
            if consecutive_llm_errors >= LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS:
                print(f"\033[31m[Agent] Consecutive error limit reached, stopping.\033[0m")
                return tracker, breaker
            error_msg = {
                "role": "user",
                "content": f"<error>{e.error_type.value if hasattr(e, 'error_type') and e.error_type else 'unknown'}: {str(e)[:200]}</error>"
            }
            messages.append(error_msg)
            tracker.track_new_message(error_msg)
            compacted = check_and_compact(messages, tracker, breaker)
            if compacted is not None:
                messages[:] = compacted
            continue
        except Exception as e:
            _spinner.stop()
            import traceback
            print(f"\033[31m[Agent] UNEXPECTED ERROR: type={type(e).__name__}, msg={e}\033[0m", flush=True)
            print(f"\033[31m[Agent] Unexpected Traceback: {traceback.format_exc()}\033[0m", flush=True)
            raise
        finally:
            _spinner.stop()

        # ✅ 检测输出截断（使用独立字段）
        if response.is_truncated:
            print(f"\033[90m[turn {turn_count}] DETECTED truncation, text_len={len(response.truncated_text)}\033[0m", flush=True)
        else:
            print(f"\033[90m[turn {turn_count}] no truncation detected, stop_reason={response.stop_reason}\033[0m", flush=True)

        # ✅ 先添加 assistant 消息（只包含标准块）
        messages.append({"role": "assistant", "content": response.content})
        tracker.update_from_response(response)

        # ✅ 检查是否有工具调用
        tool_blocks = [b for b in response.content if b.type == "tool_use"]
        
        # ✅ 优先处理工具调用
        if tool_blocks:
            if first_token_received:
                print()  # 换行
            
            # === 工具执行（含权限检查） ===
            results = []
            used_todo = False
            consecutive_tool_errors = 0
            perm_mode = state.PERMISSION_MODE
            
            for block in tool_blocks:
                perm = check_permission(block.name, block.input, perm_mode, state.perm_rules)

                if perm["action"] == "deny":
                    output = f"Permission denied: {perm['reason']}"
                    print(f"\033[31m  ✗ {block.name}: DENIED ({perm['reason']})\033[0m")
                elif perm["action"] == "confirm":
                    print(_format_permission_detail(block.name, block.input))
                    try:
                        answer = input("  Allow? (y/n): ").strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    if answer.startswith("y"):
                        from services.permissions import _get_content_key
                        key = f"{block.name}:{_get_content_key(block.name, block.input)}"
                        state.perm_rules.add_session_allow(key)
                        handler = tool_handlers.get(block.name)
                        try:
                            output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                        except Exception as e:
                            output = f"Error: {e}"
                        print(f"\033[32m  > {block.name}\033[0m")
                        print(f"    {str(output)[:200]}")
                    else:
                        output = "User denied this action."
                        print(f"\033[31m  ✗ {block.name}: USER DENIED\033[0m")
                else:  # allow
                    if block.name == "agent":
                        atype = block.input.get("type", "general")
                        desc = block.input.get("description", "")
                        name = block.input.get("name", "")
                        if name:
                            print(f"\033[35m  ┌─ Teammate [{atype}]: {name}\033[0m")
                        else:
                            bg = block.input.get("run_in_background", False)
                            mode = "async" if bg else "sync"
                            print(f"\033[35m  ┌─ SubAgent [{atype}] ({mode}): {desc}\033[0m")

                    handler = tool_handlers.get(block.name)
                    try:
                        output = handler(**block.input) if handler else f"Unknown tool: {block.name}"
                    except Exception as e:
                        output = f"Error: {e}"

                    if block.name == "agent":
                        print(f"\033[35m  └─ done\033[0m")
                    else:
                        print(f"\033[32m  > {block.name}\033[0m")
                        print(f"    {str(output)[:200]}")

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
                if block.name == "TodoWrite":
                    used_todo = True

                # ── 工具错误跟踪 ──
                output_str = str(output)
                is_error = (
                    output_str.startswith("Error:") or
                    output_str.startswith("<tool_use_error>") or
                    output_str.startswith("<error>") or
                    ("_json_parse_error" in output_str)
                )
                if is_error:
                    consecutive_tool_errors += 1

            # ── 循环保护：连续工具错误检查 ──
            if consecutive_tool_errors >= LoopConfig.MAX_CONSECUTIVE_TOOL_ERRORS:
                print(f"\033[31m[Agent] Too many consecutive tool errors ({consecutive_tool_errors}), stopping.\033[0m")
                return tracker, breaker

            rounds_without_todo = 0 if used_todo else rounds_without_todo + 1
            if state.todo and state.todo.has_open_items() and rounds_without_todo >= 3:
                results.append({"type": "text", "text": "<reminder>Update your todos.</reminder>"})

            # ✅ 添加工具结果消息
            tool_msg = {"role": "user", "content": results}
            messages.append(tool_msg)
            tracker.track_new_message(tool_msg)

            # ✅ 如果同时被截断，在工具结果后追加延续提示
            if response.is_truncated:
                print(f"\033[33m[turn {turn_count}] INJECTING truncation continuation after tool results\033[0m", flush=True)
                continuation_msg = {
                    "role": "user",
                    "content": (
                        f"<output_truncated>Your previous text output was cut off at {len(response.truncated_text)} characters "
                        f"due to max_tokens limit. Please continue your response naturally from where it was interrupted, "
                        f"without repeating what was already said.</output_truncated>"
                    ),
                }
                messages.append(continuation_msg)
                tracker.track_new_message(continuation_msg)

            # 压缩检查
            compacted = check_and_compact(messages, tracker, breaker)
            if compacted is not None:
                messages[:] = compacted

            # ✅ 重置 LLM 错误计数（成功执行）
            consecutive_llm_errors = 0
            
            # 继续下一轮
            continue

        # ✅ 没有工具调用，检查是否仅因截断
        elif response.is_truncated:
            if first_token_received:
                print()
            
            # 输出被截断，注入继续生成的消息
            print(f"\033[33m[turn {turn_count}] INJECTING truncation continuation\033[0m", flush=True)
            continuation_msg = {
                "role": "user",
                "content": (
                    f"<output_truncated>The output above was cut off at {len(response.truncated_text)} characters "
                    f"due to max_tokens limit. Please continue your previous response naturally, "
                    f"starting from where it left off. Do not repeat what was already said.</output_truncated>"
                ),
            }
            messages.append(continuation_msg)
            tracker.track_new_message(continuation_msg)
            
            compacted = check_and_compact(messages, tracker, breaker)
            if compacted is not None:
                messages[:] = compacted
            
            print(f"\033[33m[turn {turn_count}] CONTINUING after truncation, messages count now={len(messages)}\033[0m", flush=True)
            
            # ✅ 重置 LLM 错误计数
            consecutive_llm_errors = 0
            continue

        # ✅ 正常结束（没有工具调用，没有截断）
        else:
            if first_token_received:
                print()
            
            # ✅ 重置 LLM 错误计数
            consecutive_llm_errors = 0
            return tracker, breaker