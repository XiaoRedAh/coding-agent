"""
agents/subagent.py - SubAgent 模式（同步 + 异步）

S3 重构后，本文件是 core/loop.py 统一循环之上的薄封装：
- _run_agent_loop：组装子 Agent 的 LoopSpec（无权限/无压缩/无 UI，仅状态回调）
  并把 LoopResult 映射为旧的字符串返回约定
- run_subagent / run_subagent_async：对外入口（签名不变）

行为说明（对比旧实现）：
- 移除了子循环内的第二层 API 重试 —— services/llm.py 的 chat() 已内置
  完整重试（分类/退避/jitter），双层重试是历史冗余
- LLM 超时护栏保留（线程包装，超时值 LoopConfig.LLM_RESPONSE_TIMEOUT）
- 输出截断续写为统一循环的共享能力（旧子循环忽略截断）

对应 Claude Code 的 runAgent + registerAsyncAgent + LocalAgentTask。
"""

import threading
import time  # noqa: F401  (保留：外部测试可能 patch agents.subagent.time.sleep)
import uuid

from bootstrap import state
from agents.definitions import get_agent_config, get_filtered_tools
from utils.truncate import truncate_result
from services.api_errors import (
    LoopConfig,
    RetryConfig,  # noqa: F401  (保留：外部测试可能 patch agents.subagent.RetryConfig)
)
from core.loop import AgentLoop, LoopSpec, LoopHooks
from core.results import ToolResult


class _SubAgentHooks(LoopHooks):
    """子 Agent 的循环钩子：仅工具执行与状态回调。"""

    def __init__(self, tool_handlers: dict, status_callback=None):
        self.tool_handlers = tool_handlers
        self.status_callback = status_callback

    def _status(self, msg: str):
        if self.status_callback:
            self.status_callback(msg)

    def on_llm_start(self, ctx):
        self._status(f"turn {ctx.turn_count}/{ctx.max_turns}: waiting llm")

    def execute_tool(self, ctx, block) -> str:
        self._status(f"turn {ctx.turn_count}/{ctx.max_turns}: tool {block.name}")
        handler = self.tool_handlers.get(block.name)
        block_input = block.input

        # llm.py 层注入的 JSON 解析错误标记
        if isinstance(block_input, dict) and "_json_parse_error" in block_input:
            return ToolResult.failure(
                f"Error: JSON parse failed - {block_input['_json_parse_error']}",
                "json_parse_error")
        if not handler:
            return ToolResult.failure(f"Unknown tool: {block.name}", "unknown_tool")
        try:
            return truncate_result(str(handler(**block_input)))
        except Exception as e:
            return ToolResult.failure(f"Error: {e}", "exception")


def _run_agent_loop(
    system_prompt: str,
    messages: list,
    tool_defs: list,
    tool_handlers: dict,
    max_turns: int,
    agent_type: str = "general",
    status_callback=None,
) -> str:
    """
    子 Agent 的通用循环：LLM 调用 → 工具执行 → 返回最终文本。

    （统一循环的薄封装，返回字符串约定与旧实现完全一致）
    """
    hooks = _SubAgentHooks(tool_handlers, status_callback)
    spec = LoopSpec(
        system_prompt=system_prompt,
        tool_defs=tool_defs,
        tool_handlers=tool_handlers,
        max_turns=max_turns,
        max_consecutive_tool_errors=LoopConfig.MAX_CONSECUTIVE_TOOL_ERRORS,
        max_consecutive_llm_errors=LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS,
        llm_timeout=LoopConfig.LLM_RESPONSE_TIMEOUT,
        stream=False,
    )

    loop = AgentLoop(state.llm, spec, hooks)
    result = loop.run(messages)

    # ── 映射为旧的字符串返回约定 ──
    if result.stop_reason == "tool_errors":
        return f"(SubAgent stopped: {result.error_count} tool errors in one turn)"
    if result.stop_reason == "llm_errors":
        return f"(SubAgent stopped after {result.error_count} consecutive LLM errors)"
    if result.last_response is None:
        return "(subagent failed)"

    if status_callback:
        status_callback("done")
    return result.final_text or "(no output)"


def run_subagent(
    prompt: str,
    agent_type: str = "general",
    description: str = "",
    status_callback=None,
) -> str:
    """同步子代理：阻塞主 Agent 直到完成。"""
    config = get_agent_config(agent_type)
    tool_defs, tool_handlers = get_filtered_tools(config["allowed_tools"])
    messages = [{"role": "user", "content": prompt}]

    result = _run_agent_loop(
        config["system_prompt"], messages, tool_defs, tool_handlers,
        config["max_turns"],
        agent_type,
        status_callback=status_callback,
    )
    return result


def run_subagent_async(
    prompt: str,
    agent_type: str = "general",
    description: str = "",
) -> str:
    """
    异步子代理：后台线程执行，通过 AgentTaskQueue 传递结果。

    结果不再依赖 BackgroundManager，而是通过独立的 state.agent_tasks 队列。
    主 Agent 在 query.py 中通过 agent_tasks.drain() 接收 <task-notification>。

    日志格式：
      [Coordinator] 启动 Worker: {description} (id: {task_id})
      [Worker:{agent_type}] 任务进行中...
      [Worker:{agent_type}] 完成 (id: {task_id})
    """
    task_id = f"agent-{uuid.uuid4().hex[:8]}"
    label = description or agent_type

    # 打印启动日志（供用户交互端查看）
    print(f"  \033[36m[Coordinator]\033[0m 启动 Worker: \033[1m{label}\033[0m (type: {agent_type}, id: {task_id})")

    # 通知队列 +1（用于追踪进行中的任务数）
    state.agent_tasks.increment()

    def _run():
        try:
            print(f"  \033[33m[Worker:{agent_type}]\033[0m 任务进行中... (id: {task_id})")
            result = run_subagent(prompt, agent_type)
            state.agent_tasks.submit(task_id, agent_type, "completed", result[:2000])
            print(f"  \033[32m[Worker:{agent_type}]\033[0m 完成 (id: {task_id})")
        except Exception as e:
            state.agent_tasks.submit(task_id, agent_type, "error", str(e))
            print(f"  \033[31m[Worker:{agent_type}]\033[0m 失败: {e} (id: {task_id})")

    threading.Thread(target=_run, daemon=True).start()
    return f"Worker '{label}' started in background (id: {task_id}). You'll be notified when done."
