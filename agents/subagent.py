"""
agents/subagent.py - SubAgent 模式（同步 + 异步）

支持两种执行方式：
1. 同步（run_subagent）— 阻塞主 Agent 直到完成
2. 异步（run_subagent_async）— 后台线程执行，通过 AgentTaskQueue 通知主 Agent

异步结果通过独立的 AgentTaskQueue 传递（不依赖 BackgroundManager），
主 Agent 在 query.py 中通过 state.agent_tasks.drain() 接收。

对应 Claude Code 的 runAgent + registerAsyncAgent + LocalAgentTask。

失败处理：
- LLM 调用使用 api_errors.py 的重试配置
- 工具执行异常被捕获并作为错误结果返回
- JSON 解析失败由 llm.py 层处理，SubAgent 无感知
- max_turns 硬限制防止无限循环
"""

import threading
import uuid
import time

from bootstrap import state
from agents.definitions import get_agent_config, get_filtered_tools
from utils.truncate import truncate_result
from services.api_errors import (
    LoopConfig,
    RetryConfig,
    is_retryable_error,
    classify_api_error,
    get_error_message,
    get_retry_delay,
    LLMError,
    APIRetryExhaustedError,
)


def _run_agent_loop(
    system_prompt: str,
    messages: list,
    tool_defs: list,
    tool_handlers: dict,
    max_turns: int,
) -> str:
    """
    子 Agent 的通用循环：LLM 调用 → 工具执行 → 返回最终文本。

    失败处理：
    - LLM 调用失败时最多重试 2 次（指数退避）
    - 工具执行异常被捕获，返回错误消息
    - 达到 max_turns 时强制退出
    - JSON 解析错误由 llm.py 层修复，不传播到此处
    """
    resp = None
    consecutive_llm_errors = 0

    for turn in range(max_turns):
        # ── LLM 调用（带重试）──
        last_error = None
        retry_count = 0

        while retry_count <= RetryConfig.DEFAULT_MAX_RETRIES:
            try:
                resp = state.llm.chat(system_prompt, messages, tool_defs)
                break  # 成功，跳出重试循环
            except (LLMError, APIRetryExhaustedError) as e:
                last_error = e
                error_type = getattr(e, "error_type", None)

                if error_type and not is_retryable_error(error_type):
                    # 不可重试错误，直接记录并退出当前轮
                    print(f"  [sub] LLM error (unretryable): {e}")
                    consecutive_llm_errors += 1
                    break

                if retry_count >= RetryConfig.DEFAULT_MAX_RETRIES:
                    # 重试耗尽
                    print(f"  [sub] LLM error (retries exhausted): {e}")
                    consecutive_llm_errors += 1
                    break

                retry_count += 1
                error_type = getattr(e, "error_type", None) or classify_api_error(e)
                delay_ms = get_retry_delay(retry_count, error_type)
                print(f"  [sub] LLM error, retry {retry_count}/{RetryConfig.DEFAULT_MAX_RETRIES} in {delay_ms/1000:.1f}s...")
                time.sleep(delay_ms / 1000)
            except Exception as e:
                # 非 LLM 错误（如网络异常）
                last_error = e
                print(f"  [sub] Unexpected error: {e}")
                consecutive_llm_errors += 1
                break

        # 重试后仍然失败
        if resp is None:
            if consecutive_llm_errors >= LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS:
                return f"(SubAgent stopped after {consecutive_llm_errors} consecutive LLM errors)"
            # 注入错误消息，继续尝试下一轮
            error_text = str(last_error)[:200] if last_error else "Unknown error"
            messages.append({
                "role": "user",
                "content": f"<error>LLM call failed: {error_text}</error>"
            })
            continue

        # 成功响应，重置错误计数
        consecutive_llm_errors = 0
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason != "tool_use":
            break

        # ── 工具执行 ──
        results = []
        consecutive_tool_errors = 0

        for block in resp.content:
            if block.type == "tool_use":
                handler = tool_handlers.get(block.name)
                try:
                    # 检查是否有 JSON 解析错误（由 llm.py 注入）
                    block_input = block.input
                    if isinstance(block_input, dict) and "_json_parse_error" in block_input:
                        output = f"Error: JSON parse failed - {block_input['_json_parse_error']}"
                        consecutive_tool_errors += 1
                    elif handler:
                        output = str(handler(**block_input))
                    else:
                        output = f"Unknown tool: {block.name}"
                        consecutive_tool_errors += 1
                except Exception as e:
                    output = f"Error: {e}"
                    consecutive_tool_errors += 1

                output_str = str(output)
                print(f"  [sub] {block.name}: {output_str[:120]}")

                # 检查输出中是否有错误标记
                if output_str.startswith("Error:") or output_str.startswith("<tool_use_error>"):
                    consecutive_tool_errors += 1

                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": truncate_result(output),
                })

                # 连续工具错误过多，提前退出
                if consecutive_tool_errors >= LoopConfig.MAX_CONSECUTIVE_TOOL_ERRORS:
                    print(f"  [sub] Too many tool errors ({consecutive_tool_errors}), stopping.")
                    return f"(SubAgent stopped: {consecutive_tool_errors} tool errors in one turn)"

        messages.append({"role": "user", "content": results})

    if resp:
        text_parts = []
        for b in resp.content:
            if hasattr(b, "text") and b.text:
                text_parts.append(b.text)
            elif hasattr(b, "type") and b.type == "text":
                text_parts.append(str(b.text) if b.text else "")
        return "".join(text_parts) or "(no output)"
    return "(subagent failed)"


def run_subagent(prompt: str, agent_type: str = "general") -> str:
    """同步子代理：阻塞主 Agent 直到完成。"""
    config = get_agent_config(agent_type)
    tool_defs, tool_handlers = get_filtered_tools(config["allowed_tools"])
    messages = [{"role": "user", "content": prompt}]

    print(f"  [subagent:{agent_type}] starting (sync)...")
    result = _run_agent_loop(
        config["system_prompt"], messages, tool_defs, tool_handlers,
        config["max_turns"],
    )
    print(f"  [subagent:{agent_type}] done.")
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
    """
    task_id = f"agent-{uuid.uuid4().hex[:8]}"

    def _run():
        try:
            result = run_subagent(prompt, agent_type)
            state.agent_tasks.submit(task_id, agent_type, "completed", result[:2000])
        except Exception as e:
            state.agent_tasks.submit(task_id, agent_type, "error", str(e))

    threading.Thread(target=_run, daemon=True).start()
    label = description or agent_type
    print(f"  [subagent:{agent_type}] started in background (id: {task_id})")
    return f"Background agent '{label}' started (id: {task_id}). You'll be notified when done."
