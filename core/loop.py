"""
core/loop.py - 统一 Agent Loop（S3 重构）

主 Agent 与子 Agent 共用的唯一循环骨架：
    turn 循环 → LLM 调用 → 解析 tool_use → 逐个执行工具 → 注入 tool_result
    → 有工具继续 / 无工具退出

主/子 Agent 的差异全部通过 LoopSpec（配置）与 LoopHooks（可插拔钩子）表达：
- 主 Agent：stream=True、挂权限确认/压缩/通知/截断续写/UI 等全部钩子（见 query.py）
- 子 Agent：stream=False、仅挂工具执行与状态回调（见 agents/subagent.py）

共享的保护机制（对齐两套旧实现的行为并集）：
- max_turns 轮次上限
- 同轮内连续工具错误上限
- 跨轮连续 LLM 错误上限（错误注入 <error> 消息后继续，供 LLM 自行恢复）
- LLM 调用超时护栏（线程包装，防停滞流挂死）
- 输出截断续写（response.is_truncated → 注入 continuation）

本模块不依赖 bootstrap（纯核心），LLM 客户端与配置由外部注入。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from services.api_errors import (
    APIErrorType,
    LLMError,
    APIRetryExhaustedError,
)


# ──────────────────────────────────────────────
#  数据结构
# ──────────────────────────────────────────────

@dataclass
class LoopContext:
    """单轮上下文（传给各钩子）。"""
    turn_count: int
    max_turns: int


@dataclass
class LoopSpec:
    """循环配置（主/子 Agent 的差异以配置表达）。"""
    system_prompt: Any
    tool_defs: list
    tool_handlers: dict
    max_turns: int = 50
    max_consecutive_tool_errors: int = 5
    max_consecutive_llm_errors: int = 3
    llm_timeout: Optional[float] = None   # None 表示不做线程级超时护栏
    stream: bool = False                  # 主 Agent 流式输出


@dataclass
class LoopResult:
    """循环执行结果。"""
    stop_reason: str        # "end_turn" | "max_turns" | "llm_errors" | "tool_errors"
    final_text: str = ""
    error_count: int = 0    # 触发停止时的错误计数（llm_errors / tool_errors）
    last_response: Any = None
    tracker: Any = None
    breaker: Any = None


# ──────────────────────────────────────────────
#  钩子协议（默认全部 no-op，按需覆盖）
# ──────────────────────────────────────────────

class LoopHooks:
    """循环钩子基类。主/子 Agent 各自继承并覆盖所需方法。"""

    def pre_turn(self, ctx: LoopContext, messages: list, tracker) -> bool:
        """每轮 LLM 调用前执行（压缩/通知注入等）。返回 True 表示跳过本轮 LLM 调用。"""
        return False

    def on_llm_start(self, ctx: LoopContext) -> None:
        """LLM 调用开始（spinner / 状态提示）。"""

    def on_text(self, delta: str) -> None:
        """流式文本增量（仅 stream=True 时被调用）。"""

    def on_llm_end(self, ctx: LoopContext, response=None) -> None:
        """LLM 调用结束（含异常路径，response 为 None 表示出错）。"""

    def on_llm_exception(self, ctx: LoopContext, error: Exception) -> None:
        """LLM 调用抛出异常（用于错误日志）。"""

    def on_response(self, ctx: LoopContext, response) -> None:
        """成功响应已追加到 messages 之后（token 统计等）。"""

    def execute_tool(self, ctx: LoopContext, block) -> str:
        """执行单个 tool_use 块，返回输出字符串（不得抛异常，错误以字符串返回）。"""
        handler = None  # 默认无 handler
        return "Error: no tool handler"

    def post_tools(self, ctx: LoopContext, messages: list, tool_msg: dict) -> None:
        """工具结果消息已追加之后（token 统计 / todo reminder 等）。"""

    def maybe_compact(self, ctx: LoopContext, messages: list) -> None:
        """压缩检查点（LLM 错误后 / 截断续写后 / 工具轮结束后）。"""

    def on_truncation(self, ctx: LoopContext, response, after_tools: bool) -> None:
        """检测到输出截断，即将注入续写提示。"""

    def on_stop(self, stop_reason: str, error_count: int) -> None:
        """循环停止（保护机制触发或正常结束）。"""


# ──────────────────────────────────────────────
#  工具函数
# ──────────────────────────────────────────────

def is_error_output(output_str: str) -> bool:
    """判断工具输出是否为错误（两套旧实现嗅探规则的并集）。"""
    return (
        output_str.startswith("Error:")
        or output_str.startswith("<tool_use_error>")
        or output_str.startswith("<error>")
        or "_json_parse_error" in output_str
        or output_str.startswith("Unknown tool")
    )


def is_tool_error(output) -> bool:
    """
    工具结果错误判定：优先读 ToolResult.ok（结构化），回退字符串嗅探。

    ToolResult 是 str 子类（见 core/results.py），普通 str / 异常对象
    走 is_error_output 嗅探（兼容第三方 handler）。
    """
    ok = getattr(output, "ok", None)
    if ok is False:
        return True
    if ok is True:
        return False
    return is_error_output(str(output))


def extract_text(response) -> str:
    """从响应 content blocks 中提取全部文本（只接受 str，防御 MagicMock 等对象）。"""
    parts = []
    for b in getattr(response, "content", []) or []:
        text = getattr(b, "text", None)
        if isinstance(text, str) and text:
            parts.append(text)
    return "".join(parts)


# ──────────────────────────────────────────────
#  统一循环
# ──────────────────────────────────────────────

class AgentLoop:
    """主/子 Agent 共用的循环执行器。"""

    def __init__(self, llm, spec: LoopSpec, hooks: LoopHooks | None = None):
        self.llm = llm
        self.spec = spec
        self.hooks = hooks if hooks is not None else LoopHooks()

    # ── LLM 调用（含超时护栏） ──

    def _call_llm(self, messages: list):
        if self.spec.llm_timeout is not None:
            return self._chat_with_timeout(messages)
        return self._chat(messages)

    def _chat(self, messages: list):
        if self.spec.stream:
            return self.llm.chat(
                self.spec.system_prompt, messages, self.spec.tool_defs,
                stream=True, on_text=self.hooks.on_text,
            )
        return self.llm.chat(self.spec.system_prompt, messages, self.spec.tool_defs)

    def _chat_with_timeout(self, messages: list):
        """线程包装的 LLM 调用：超时护栏防止停滞调用挂死循环。"""
        result_holder: dict = {}
        error_holder: dict = {}

        def _target():
            try:
                result_holder["resp"] = self._chat(messages)
            except Exception as exc:  # 防御：异常回传到主线程抛出
                error_holder["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self.spec.llm_timeout)

        if thread.is_alive():
            raise LLMError(
                f"LLM call timed out after {self.spec.llm_timeout}s",
                APIErrorType.TIMEOUT,
            )
        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("resp")

    # ── 主入口 ──

    def run(self, messages: list, tracker=None, breaker=None) -> LoopResult:
        spec = self.spec
        hooks = self.hooks
        turn_count = 0
        consecutive_llm_errors = 0
        resp = None

        def _result(stop_reason, error_count=0, final_text=""):
            hooks.on_stop(stop_reason, error_count)
            return LoopResult(
                stop_reason=stop_reason,
                error_count=error_count,
                final_text=final_text or extract_text(resp),
                last_response=resp,
                tracker=tracker,
                breaker=breaker,
            )

        while True:
            turn_count += 1
            ctx = LoopContext(turn_count, spec.max_turns)

            # ── 循环保护：max_turns ──
            if turn_count > spec.max_turns:
                return _result("max_turns")

            # ── 循环保护：连续 LLM 错误（轮首兜底检查） ──
            if consecutive_llm_errors >= spec.max_consecutive_llm_errors:
                return _result("llm_errors", error_count=consecutive_llm_errors)

            # ── 每轮前置钩子（压缩 / 通知注入），可要求跳过本轮 LLM 调用 ──
            if hooks.pre_turn(ctx, messages, tracker):
                continue

            # ── LLM 调用 ──
            hooks.on_llm_start(ctx)
            try:
                resp = self._call_llm(messages)
            except (LLMError, APIRetryExhaustedError) as e:
                resp = None
                hooks.on_llm_exception(ctx, e)
                consecutive_llm_errors += 1
                if consecutive_llm_errors >= spec.max_consecutive_llm_errors:
                    return _result("llm_errors", error_count=consecutive_llm_errors)
                # 注入错误消息，供 LLM 下一轮自行恢复
                err_type = getattr(e, "error_type", None)
                err_name = err_type.value if err_type else "unknown"
                error_msg = {
                    "role": "user",
                    "content": f"<error>{err_name}: {str(e)[:200]}</error>",
                }
                messages.append(error_msg)
                if tracker:
                    tracker.track_new_message(error_msg)
                hooks.maybe_compact(ctx, messages)
                continue
            finally:
                hooks.on_llm_end(ctx, resp if resp is not None else None)

            consecutive_llm_errors = 0

            # ── 追加 assistant 消息 ──
            messages.append({"role": "assistant", "content": resp.content})
            hooks.on_response(ctx, resp)

            tool_blocks = [
                b for b in (resp.content or [])
                if getattr(b, "type", None) == "tool_use"
            ]
            truncated = bool(getattr(resp, "is_truncated", False))

            # ── 工具执行分支 ──
            if tool_blocks:
                results = []
                consecutive_tool_errors = 0
                for block in tool_blocks:
                    output = hooks.execute_tool(ctx, block)
                    failed = is_tool_error(output)
                    # ToolResult 是 str 子类，本身就是可注入的内容
                    entry = {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(output),
                    }
                    if failed:
                        # Anthropic 原生错误标志：模型将其作为一等失败信号对待
                        entry["is_error"] = True
                    results.append(entry)
                    if failed:
                        consecutive_tool_errors += 1

                if consecutive_tool_errors >= spec.max_consecutive_tool_errors:
                    return _result("tool_errors", error_count=consecutive_tool_errors)

                tool_msg = {"role": "user", "content": results}
                messages.append(tool_msg)
                hooks.post_tools(ctx, messages, tool_msg)

                if truncated:
                    self._inject_continuation(ctx, messages, tracker, resp, after_tools=True)
                hooks.maybe_compact(ctx, messages)
                continue

            # ── 无工具调用但输出被截断：注入续写提示 ──
            if truncated:
                self._inject_continuation(ctx, messages, tracker, resp, after_tools=False)
                hooks.maybe_compact(ctx, messages)
                continue

            # ── 正常结束 ──
            return _result("end_turn", final_text=extract_text(resp))

    def _inject_continuation(self, ctx, messages, tracker, resp, after_tools: bool):
        """注入截断续写提示消息。"""
        self.hooks.on_truncation(ctx, resp, after_tools)
        truncated_text = getattr(resp, "truncated_text", "") or ""
        if after_tools:
            content = (
                f"<output_truncated>Your previous text output was cut off at "
                f"{len(truncated_text)} characters due to max_tokens limit. "
                f"Please continue your response naturally from where it was interrupted, "
                f"without repeating what was already said.</output_truncated>"
            )
        else:
            content = (
                f"<output_truncated>The output above was cut off at "
                f"{len(truncated_text)} characters due to max_tokens limit. "
                f"Please continue your previous response naturally, "
                f"starting from where it left off. Do not repeat what was already "
                f"said.</output_truncated>"
            )
        continuation = {"role": "user", "content": content}
        messages.append(continuation)
        if tracker:
            tracker.track_new_message(continuation)
