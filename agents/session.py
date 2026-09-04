"""
query.py - 主 Agent 循环（薄组装层）

S3/S4 重构后，本文件只负责：
1. Workflow 快捷入口分发（/workflow 命令或 SOP_MODE）
2. 组装主 Agent 的 LoopSpec 配置与 _MainLoopHooks 钩子
   （权限确认 / 上下文压缩 / 通知注入 / 截断续写 / 终端 UI）
3. 调用 engine.loop.AgentLoop 执行并返回 (tracker, breaker)

循环骨架（turn 循环 / 工具执行 / 错误恢复 / 截断续写）在 core/loop.py；
通知收集在 core/notifications.py；终端渲染在 ui/render.py。
"""

import time

from runtime import state
from runtime.state import WARNING_THRESHOLD, settings

from tools import get_all_definitions, get_all_handlers
from context.prompt import build_system_prompt  # backward-compat for tests patching query.build_system_prompt
from agents.coordinator import is_coordinator_mode
from context.builder import PromptBuilder
from services.permissions import check_permission
from engine.errors import LoopConfig
from services.tracing import trace
from ui.console import fail_sym
from context.compact import (
    TokenTracker, CircuitBreaker,
    run_compression_pipeline, check_and_compact,
)
from workflows.gateway import maybe_run_workflow

from engine.loop import AgentLoop, LoopSpec, LoopHooks
from engine.results import ToolResult
from engine.notifications import collect_bg_notifications, process_agent_notifications
from ui.render import (
    Spinner, print_permission_detail, confirm_action,
    print_tool_result, print_agent_start, print_agent_done,
)


# ──────────────────────────────────────────────
#  主 Agent 钩子（权限 / 压缩 / 通知 / UI）
# ──────────────────────────────────────────────

class _MainLoopHooks(LoopHooks):
    """主 Agent 的循环钩子实现。"""

    def __init__(self, tracker, breaker, tool_handlers: dict):
        self.tracker = tracker
        self.breaker = breaker
        self.tool_handlers = tool_handlers
        self.spinner = Spinner()
        self.first_token_received = False
        self.rounds_without_todo = 0
        self.used_todo_this_turn = False
        self._llm_start_ts = 0.0     # 可观测性：LLM 延迟测量
        self._tool_start_ts = 0.0    # 可观测性：工具延迟测量

    # ── 每轮前置：压缩 + 通知注入 ──

    def pre_turn(self, ctx, messages, tracker) -> bool:
        # 压缩管道（L1-L3，零 API 成本）
        run_compression_pipeline(messages, self.tracker)

        utilization = self.tracker.get_utilization()
        if utilization >= WARNING_THRESHOLD:
            print(f"\033[33m[context at {utilization:.0%}]\033[0m")

        # 后台 Shell 通知
        bg_content = collect_bg_notifications(state)
        if bg_content:
            msg = {"role": "user", "content": bg_content}
            messages.append(msg)
            self.tracker.track_new_message(msg)

        # 异步 Agent 通知（含等待逻辑：普通模式与 Coordinator 统一语义）
        if state.agent_tasks:
            coordinator_mode = True  # 等待语义统一：有 in_flight 即等待
            content, skip_llm = process_agent_notifications(
                state, coordinator_mode, settings.loop.coordinator_wait_timeout)
            if content:
                msg = {"role": "user", "content": content}
                messages.append(msg)
                self.tracker.track_new_message(msg)
            if skip_llm:
                return True
        return False

    def has_pending_work(self, messages) -> bool:
        """等待闭环：end_turn 时仍有后台子 Agent 在飞 → 不结束回合。"""
        if not state.agent_tasks:
            return False
        return state.agent_tasks.get_in_flight() > 0

    # ── LLM 调用生命周期 ──

    def on_llm_start(self, ctx):
        self.first_token_received = False
        self.used_todo_this_turn = False
        self._llm_start_ts = time.time()
        print(f"\033[90m[turn {ctx.turn_count}] calling llm.chat (stream=True)\033[0m", flush=True)
        self.spinner.start()

    def on_text(self, delta):
        if not self.first_token_received:
            self.spinner.stop()
            self.first_token_received = True
        print(delta, end="", flush=True)

    def on_llm_end(self, ctx, response=None):
        self.spinner.stop()
        if response is not None:
            print(f"\033[90m[turn {ctx.turn_count}] llm.chat returned, "
                  f"stop_reason={response.stop_reason}, blocks={len(response.content)}\033[0m",
                  flush=True)

    def on_llm_exception(self, ctx, error):
        import traceback
        latency_ms = round((time.time() - self._llm_start_ts) * 1000, 1) if self._llm_start_ts else None
        trace("llm_error", turn=ctx.turn_count, latency_ms=latency_ms,
              error_type=str(getattr(error, "error_type", None) or type(error).__name__))
        print(f"\033[31m[Agent] LLM ERROR: type={type(error).__name__}, "
              f"error_type={getattr(error, 'error_type', None)}, msg={error}\033[0m", flush=True)
        print(f"\033[31m[Agent] Traceback: {traceback.format_exc()[-500:]}\033[0m", flush=True)
        err_type = getattr(error, 'error_type', None)
        print(f"\033[31m[Agent] LLM error "
              f"({err_type.value if err_type else 'unknown'}): {error}\033[0m")

    def on_response(self, ctx, response):
        self.tracker.update_from_response(response)
        # 可观测性：token 消耗 + LLM 延迟
        latency_ms = round((time.time() - self._llm_start_ts) * 1000, 1) if self._llm_start_ts else None
        trace("llm_response", turn=ctx.turn_count,
              tokens_in=getattr(response, "input_tokens", None),
              tokens_out=getattr(response, "output_tokens", None),
              stop_reason=getattr(response, "stop_reason", None),
              latency_ms=latency_ms)
        if getattr(response, "is_truncated", False):
            print(f"\033[90m[turn {ctx.turn_count}] DETECTED truncation, "
                  f"text_len={len(getattr(response, 'truncated_text', '') or '')}\033[0m", flush=True)

    # ── 工具执行（含权限确认） ──

    def execute_tool(self, ctx, block) -> str:
        """执行工具（外层包装：计时 + trace 埋点）。"""
        self._tool_start_ts = time.time()
        output = self._execute_tool_inner(ctx, block)
        self._trace_tool(ctx, block, output)
        return output

    def _execute_tool_inner(self, ctx, block) -> str:
        if self.first_token_received:
            print()  # 换行

        perm_mode = state.PERMISSION_MODE
        perm = check_permission(block.name, block.input, perm_mode, state.perm_rules)

        if perm["action"] == "deny":
            output = ToolResult.failure(
                f"Permission denied: {perm['reason']}", "permission_denied")
            print(f"\033[31m  {fail_sym()} {block.name}: DENIED ({perm['reason']})\033[0m")
            return output

        if perm["action"] == "confirm":
            print_permission_detail(block.name, block.input)
            if confirm_action():
                from services.permissions import _get_content_key
                key = f"{block.name}:{_get_content_key(block.name, block.input)}"
                state.perm_rules.add_session_allow(key)
                output = self._run_handler(block)
                print_tool_result(block.name, output)
            else:
                output = ToolResult.failure(
                    "User denied this action.", "permission_denied")
                print(f"\033[31m  {fail_sym()} {block.name}: USER DENIED\033[0m")
            return output

        # allow
        if block.name == "agent":
            print_agent_start(block.input)
        output = self._run_handler(block)
        if block.name == "agent":
            print_agent_done()
        else:
            print_tool_result(block.name, output)

        if block.name == "TodoWrite":
            self.used_todo_this_turn = True
        return output

    def _run_handler(self, block) -> str:
        handler = self.tool_handlers.get(block.name)
        try:
            return handler(**block.input) if handler else ToolResult.failure(
                f"Unknown tool: {block.name}", "unknown_tool")
        except Exception as e:
            return ToolResult.failure(f"Error: {e}", "exception")

    def _trace_tool(self, ctx, block, output) -> None:
        """可观测性：记录 tool_call 事件；检测并记录 memory_write / skill_load。"""
        latency_ms = round((time.time() - self._tool_start_ts) * 1000, 1)
        ok = getattr(output, "ok", None)
        if ok is None:
            ok = not str(output).startswith(("Error:", "<error>", "<tool_use_error>"))
        fields = {
            "turn": ctx.turn_count,
            "tool": block.name,
            "ok": bool(ok),
            "latency_ms": latency_ms,
            "result_chars": len(str(output)),
        }
        # 输入预览：run_shell 记命令、写/编辑记路径、其余记参数字符数
        # （崩溃/被杀后的复盘需要还原"最后一步做了什么"）
        inp = block.input if isinstance(block.input, dict) else {}
        if block.name == "run_shell":
            fields["command"] = str(inp.get("command", ""))[:200]
        elif block.name in ("write_file", "edit_file"):
            fields["path"] = str(inp.get("file_path", ""))[:200]
        trace("tool_call", **fields)
        # 记忆写入检测：第一层写入引导有效性的直接指标
        if (block.name in ("write_file", "edit_file")
                and isinstance(block.input, dict)
                and state.memory is not None):
            file_path = block.input.get("file_path", "")
            if file_path and state.memory.is_memory_path(file_path):
                trace("memory_write", turn=ctx.turn_count, tool=block.name,
                      path=str(file_path))
        # 记忆读取检测（读 MEMORY 索引或记忆文件）
        if (block.name == "read_file"
                and isinstance(block.input, dict)
                and state.memory is not None):
            file_path = block.input.get("file_path", "")
            if file_path and state.memory.is_memory_path(file_path):
                trace("memory_read", turn=ctx.turn_count, path=str(file_path))
        # 技能加载检测
        if (block.name == "load_skill" and isinstance(block.input, dict)):
            trace("skill_load", turn=ctx.turn_count,
                  skill=str(block.input.get("name", "")),
                  args=str(block.input.get("args", ""))[:100],
                  invoked_via="tool")

    # ── 工具结果后处理 ──

    def post_tools(self, ctx, messages, tool_msg):
        self.tracker.track_new_message(tool_msg)

        # Todo reminder：有未完成待办但连续多轮未更新时提醒
        # （附当前清单内容，避免 LLM 翻上下文考古）
        self.rounds_without_todo = 0 if self.used_todo_this_turn else self.rounds_without_todo + 1
        if (state.todo and state.todo.has_open_items()
                and self.rounds_without_todo >= settings.tools.todo_reminder_rounds):
            tool_msg["content"].append({
                "type": "text",
                "text": (
                    "<reminder>Update your todos.</reminder>\n"
                    f"Current todo list:\n{state.todo.render()}"
                ),
            })

    # ── 压缩检查点 ──

    def maybe_compact(self, ctx, messages):
        compacted = check_and_compact(messages, self.tracker, self.breaker)
        if compacted is not None:
            trace("compact", turn=ctx.turn_count,
                  utilization=round(self.tracker.get_utilization(), 3))
            messages[:] = compacted

    # ── 截断 ──

    def on_truncation(self, ctx, response, after_tools):
        label = "after tool results" if after_tools else ""
        print(f"\033[33m[turn {ctx.turn_count}] INJECTING truncation continuation "
              f"{label}\033[0m", flush=True)

    # ── 停止提示 ──

    def on_stop(self, stop_reason, error_count):
        if stop_reason == "max_turns":
            print(f"\033[31m[Agent] Reached max turns, stopping.\033[0m")
        elif stop_reason == "llm_errors":
            print(f"\033[31m[Agent] Consecutive error limit reached, stopping.\033[0m")
        elif stop_reason == "tool_errors":
            print(f"\033[31m[Agent] Too many consecutive tool errors, stopping.\033[0m")


# ──────────────────────────────────────────────
#  Agent Loop（对外 API 保持不变）
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

    # Workflow 快捷入口：/workflow ... 或 SOP_MODE=1
    handled, workflow_reply = maybe_run_workflow(messages)
    if handled:
        if workflow_reply:
            print(workflow_reply)
            assistant_msg = {"role": "assistant", "content": workflow_reply}
            messages.append(assistant_msg)
            tracker.track_new_message(assistant_msg)
        return tracker, breaker

    all_defs = get_all_definitions()
    all_handlers = get_all_handlers()
    runtime_config = PromptBuilder.build_runtime_config(all_defs, all_handlers)

    hooks = _MainLoopHooks(tracker, breaker, runtime_config["tool_handlers"])
    spec = LoopSpec(
        system_prompt=runtime_config["system_prompt"],
        tool_defs=runtime_config["tool_defs"],
        tool_handlers=runtime_config["tool_handlers"],
        max_turns=max_turns,
        max_consecutive_tool_errors=LoopConfig.MAX_CONSECUTIVE_TOOL_ERRORS,
        max_consecutive_llm_errors=LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS,
        llm_timeout=settings.llm.timeout_seconds,
        stream=True,
        wait_for_pending=True,   # 等待闭环：后台任务未完成不结束回合
    )

    loop = AgentLoop(state.llm, spec, hooks)
    result = loop.run(messages, tracker=tracker, breaker=breaker)
    return result.tracker, result.breaker
