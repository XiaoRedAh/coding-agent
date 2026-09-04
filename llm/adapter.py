"""
services/llm.py - LLM 调用适配层

统一 Anthropic SDK 和 OpenAI SDK 的调用接口，屏蔽格式差异。
"""

import os
import time
import re
import json as _json
from dataclasses import dataclass, field
from typing import Any, Optional
from types import SimpleNamespace

from engine.errors import (
    APIErrorType,
    RetryConfig,
    JSONParseConfig,
    LoopConfig,
    classify_api_error,
    is_retryable_error,
    get_error_message,
    get_retry_delay,
    get_max_retries_for_error,
    LLMError,
    JSONParseError,
    APIRetryExhaustedError,
)


# ──────────────────────────────────────────────
#  响应数据结构
# ──────────────────────────────────────────────

@dataclass
class LLMResponse:
    """标准化的 LLM 响应，屏蔽 Anthropic/OpenAI 格式差异。"""
    content: list          # Anthropic 风格的 content blocks（只包含标准块）
    stop_reason: str       # "end_turn" 或 "tool_use"
    input_tokens: int
    output_tokens: int
    is_truncated: bool = False      # ✅ 新增：是否因 max_tokens 截断
    truncated_text: str = ""        # ✅ 新增：截断时的文本内容
    _raw: Any = field(default=None, repr=False)  # 原始响应（调试用）
    error_type: Optional[APIErrorType] = None  # 错误类型（如有）


# ──────────────────────────────────────────────
#  LLM 适配器
# ──────────────────────────────────────────────

class LLMAdapter:
    """统一的 LLM 调用接口。"""

    def __init__(self, provider: str, client: Any, model: str):
        self.provider = provider
        self.client = client
        self.model = model

    @staticmethod
    def from_env() -> "LLMAdapter":
        """从环境变量自动创建适配器。"""
        from runtime.state import settings
        provider = os.getenv("LLM_PROVIDER", settings.llm.provider).lower()
        model = os.environ["MODEL_ID"]
        # 客户端级超时护栏：防止停滞的连接/流无限挂起主循环。
        # 对流式调用，该超时作用于相邻 chunk 的间隔（读超时），而非总时长。
        timeout_s = settings.llm.timeout_seconds

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.getenv("OPENAI_API_KEY"),
                timeout=timeout_s,
            )
        else:
            from anthropic import Anthropic
            client = Anthropic(
                base_url=os.getenv("ANTHROPIC_BASE_URL"),
                timeout=timeout_s,
            )

        return LLMAdapter(provider, client, model)

    def chat(
        self,
        system: Any,
        messages: list,
        tools: list = None,
        max_tokens: int = 8000,
        stream: bool = False,
        on_text: callable = None,
    ) -> LLMResponse:
        """统一的 LLM 调用（带自动重试）。"""
        last_error: Optional[Exception] = None
        max_retries = RetryConfig.DEFAULT_MAX_RETRIES

        for attempt in range(1, max_retries + 2):
            try:
                if stream:
                    if self.provider == "openai":
                        return self._stream_openai(system, messages, tools, max_tokens, on_text)
                    return self._stream_anthropic(system, messages, tools, max_tokens, on_text)
                if self.provider == "openai":
                    return self._call_openai(system, messages, tools, max_tokens)
                return self._call_anthropic(system, messages, tools, max_tokens)

            except Exception as e:
                import traceback
                last_error = e
                error_type = classify_api_error(e)
                # 终端只留一行；完整 traceback 进 trace（可观测性），不污染流式输出
                print(f"\033[31m[llm.chat] EXCEPTION in attempt {attempt}: type={type(e).__name__}, error_type={error_type}, msg={e}\033[0m", flush=True)
                try:
                    from services.tracing import trace
                    trace("llm_traceback", attempt=attempt,
                          error_type=str(error_type),
                          traceback=traceback.format_exc()[-2000:])
                except Exception:
                    pass

                if not is_retryable_error(error_type):
                    raise LLMError(get_error_message(error_type), error_type) from e

                error_max_retries = get_max_retries_for_error(error_type)
                effective_max = min(max_retries, error_max_retries)
                if attempt >= effective_max + 1:
                    msg = f"{get_error_message(error_type)} (after {attempt - 1} retries)"
                    raise APIRetryExhaustedError(msg, error_type, attempt - 1) from e

                retry_after = self._extract_retry_after(e)
                delay_ms = get_retry_delay(attempt, error_type, retry_after)
                delay_s = delay_ms / 1000

                print(f"\033[33m[API error: {error_type.value}, retry {attempt}/{effective_max} in {delay_s:.1f}s]\033[0m")
                time.sleep(delay_s)

        if last_error:
            raise LLMError(str(last_error), classify_api_error(last_error)) from last_error
        raise LLMError("Unknown error", APIErrorType.UNKNOWN)

    def _extract_retry_after(self, error: Exception) -> Optional[int]:
        """从错误中提取 Retry-After 头（毫秒）。"""
        headers = getattr(error, "headers", None)
        if headers is None:
            return None
        if isinstance(headers, dict):
            ra = headers.get("retry-after") or headers.get("Retry-After")
        else:
            ra = getattr(headers, "get", lambda x: None)("retry-after")
        if ra:
            try:
                return int(ra) * 1000
            except (ValueError, TypeError):
                pass
        return None

    # ──────────────────────────────────────────────
    #  Anthropic Provider
    # ──────────────────────────────────────────────

    def _call_anthropic(self, system, messages, tools, max_tokens) -> LLMResponse:
        kwargs = dict(
            model=self.model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools

        resp = self.client.messages.create(**kwargs)
        return LLMResponse(
            content=resp.content,
            stop_reason=resp.stop_reason,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            _raw=resp,
        )

    def _stream_anthropic(self, system, messages, tools, max_tokens, on_text) -> LLMResponse:
        """Anthropic 流式调用：逐字输出文本，完成后返回完整响应。"""
        kwargs = dict(model=self.model, system=system, messages=messages, max_tokens=max_tokens)
        if tools:
            kwargs["tools"] = tools

        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if on_text and hasattr(event, "type"):
                    if event.type == "content_block_delta" and hasattr(event.delta, "text"):
                        on_text(event.delta.text)
            resp = stream.get_final_message()

        return LLMResponse(
            content=resp.content,
            stop_reason=resp.stop_reason,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            _raw=resp,
        )

    # ──────────────────────────────────────────────
    #  OpenAI Provider
    # ──────────────────────────────────────────────

    def _call_openai(self, system, messages, tools, max_tokens) -> LLMResponse:
        # 1. 转换 system prompt
        sys_text = self._flatten_system(system)
        oai_messages = [{"role": "system", "content": sys_text}]

        # 2. 转换 messages
        for msg in messages:
            converted = self._convert_message(msg)
            if isinstance(converted, list):
                oai_messages.extend(converted)
            else:
                oai_messages.append(converted)

        # 3. 转换工具定义
        oai_tools = [self._convert_tool_def(t) for t in tools] if tools else None

        # 4. 调用 API
        kwargs = dict(
            model=self.model,
            messages=oai_messages,
            max_tokens=max_tokens,
        )
        if oai_tools:
            kwargs["tools"] = oai_tools

        resp = self.client.chat.completions.create(**kwargs)
        if resp is None:
            raise LLMError("OpenAI API returned empty response", APIErrorType.CONNECTION_ERROR)

        choices = getattr(resp, "choices", None)
        if not choices:
            raise LLMError("OpenAI API returned no choices", APIErrorType.SERVER_ERROR)

        choice = choices[0]

        # 5. 标准化响应（只包含标准块）
        content = self._convert_oai_response_with_parse_recovery(choice)

        # ✅ 检测截断，提取到独立字段
        is_truncated = (choice.finish_reason == "length")
        truncated_text = ""
        if is_truncated:
            for block in content:
                if block.type == "text":
                    truncated_text += block.text

        stop = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

        return LLMResponse(
            content=content,  # ✅ 不包含 output_truncated 块
            stop_reason=stop,
            input_tokens=getattr(resp.usage, "prompt_tokens", 0),
            output_tokens=getattr(resp.usage, "completion_tokens", 0),
            is_truncated=is_truncated,      # ✅ 独立标志
            truncated_text=truncated_text,  # ✅ 文本内容
            _raw=resp,
        )

    def _stream_openai(self, system, messages, tools, max_tokens, on_text) -> LLMResponse:
        """OpenAI 流式调用：逐字输出文本，收集完整响应。"""
        sys_text = self._flatten_system(system)
        oai_messages = [{"role": "system", "content": sys_text}]
        for msg in messages:
            converted = self._convert_message(msg)
            if isinstance(converted, list):
                oai_messages.extend(converted)
            else:
                oai_messages.append(converted)

        oai_tools = [self._convert_tool_def(t) for t in tools] if tools else None
        kwargs = dict(model=self.model, messages=oai_messages, max_tokens=max_tokens, stream=True)
        # 流式 usage 统计：OpenAI 兼容 API 需显式请求，否则 usage chunk 不下发
        #（tokens 统计/成本估算/上下文利用率会全部失真为 0）
        kwargs["stream_options"] = {"include_usage": True}
        if oai_tools:
            kwargs["tools"] = oai_tools

        # 收集流式数据
        collected_text = []
        collected_tool_calls = {}
        finish_reason = None
        input_tokens = 0
        output_tokens = 0

        stream = self.client.chat.completions.create(**kwargs)
        for chunk in stream:
            # usage chunk：choices 为空列表（OpenAI 兼容流式约定）
            # 注意：DeepSeek 等 API 发的是 choices=[] 而非缺失 choices，
            # 所以必须先查 usage 再判 choices，否则 tokens 统计恒为 0
            if hasattr(chunk, "usage") and chunk.usage:
                input_tokens = getattr(chunk.usage, "prompt_tokens", 0) or input_tokens
                output_tokens = getattr(chunk.usage, "completion_tokens", 0) or output_tokens
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            if delta and delta.content:
                collected_text.append(delta.content)
                if on_text:
                    on_text(delta.content)

            if delta and delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "id": tc_delta.id or "",
                            "name": getattr(tc_delta.function, "name", "") or "",
                            "arguments": "",
                        }
                    else:
                        if tc_delta.id:
                            collected_tool_calls[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            collected_tool_calls[idx]["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        collected_tool_calls[idx]["arguments"] += tc_delta.function.arguments

        # 组装最终 content blocks（含 JSON 修复）
        blocks = []
        full_text = "".join(collected_text)
        if full_text:
            blocks.append(SimpleNamespace(type="text", text=full_text))

        for idx in sorted(collected_tool_calls.keys()):
            tc = collected_tool_calls[idx]
            parsed_args, parse_error = self._safe_parse_json(tc["arguments"])

            if parse_error:
                repaired_args, repair_success = self._repair_truncated_json(tc["arguments"])
                if repair_success:
                    blocks.append(SimpleNamespace(
                        type="tool_use",
                        id=tc["id"],
                        name=tc["name"],
                        input=repaired_args,
                    ))
                else:
                    blocks.append(SimpleNamespace(
                        type="tool_use",
                        id=tc["id"],
                        name=tc["name"],
                        input={"_json_parse_error": parse_error, "_raw_args": tc["arguments"][:200]},
                    ))
            else:
                blocks.append(SimpleNamespace(
                    type="tool_use",
                    id=tc["id"],
                    name=tc["name"],
                    input=parsed_args,
                ))

        if not blocks:
            blocks.append(SimpleNamespace(type="text", text=""))

        # ✅ 检测截断，提取到独立字段
        is_truncated = (finish_reason == "length")
        truncated_text = "".join(collected_text) if is_truncated else ""

        if is_truncated:
            print(f"\033[33m[_stream_openai] finish_reason=length detected, text_len={len(truncated_text)}\033[0m", flush=True)

        stop = "tool_use" if finish_reason == "tool_calls" else "end_turn"
        return LLMResponse(
            content=blocks,  # ✅ 不包含 output_truncated 块
            stop_reason=stop,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            is_truncated=is_truncated,      # ✅ 独立标志
            truncated_text=truncated_text,  # ✅ 文本内容
        )

    def _safe_parse_json(self, raw: str) -> tuple:
        """安全解析 JSON，返回 (parsed_dict, error_or_none)。"""
        try:
            return _json.loads(raw), None
        except (_json.JSONDecodeError, TypeError, ValueError) as e:
            return {}, f"JSON decode failed: {str(e)[:80]}"

    def _repair_truncated_json(self, raw: str) -> tuple:
        """尝试修复被截断的 JSON 字符串。"""
        if not raw or not raw.strip():
            return {}, False

        if raw.strip().startswith("{"):
            result, ok = self._extract_last_complete_object(raw)
            if ok:
                return result, True

        if raw.strip().startswith("["):
            result, ok = self._extract_last_complete_array(raw)
            if ok:
                return result, True

        result, ok = self._extract_last_complete_pair(raw)
        if ok:
            return result, True

        return {}, False

    def _extract_last_complete_object(self, raw: str) -> tuple:
        """从截断的原始字符串中提取最后一个完整的 JSON 对象。"""
        depth = 0
        last_complete_pos = -1

        for i, ch in enumerate(raw):
            if ch == "{":
                if depth == 0:
                    last_complete_pos = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and i > last_complete_pos:
                    last_complete_pos = i + 1

        if depth == 0 and last_complete_pos > 0:
            candidate = raw[:last_complete_pos]
            try:
                result = _json.loads(candidate)
                return result, True
            except _json.JSONDecodeError:
                pass

        if depth > 0:
            candidate = raw
            closes_needed = "}" * depth
            for attempt in range(JSONParseConfig.MAX_REPAIR_ATTEMPTS):
                try:
                    result = _json.loads(candidate + closes_needed)
                    return result, True
                except _json.JSONDecodeError:
                    candidate = candidate.rstrip().rstrip(",").rstrip()
                    closes_needed = '"' + closes_needed
                except Exception:
                    break

        return {}, False

    def _extract_last_complete_array(self, raw: str) -> tuple:
        """从截断的原始字符串中提取最后一个完整的 JSON 数组。"""
        depth = 0
        last_complete_pos = -1

        for i, ch in enumerate(raw):
            if ch == "[":
                if depth == 0:
                    last_complete_pos = i
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0 and i > last_complete_pos:
                    last_complete_pos = i + 1

        if depth == 0 and last_complete_pos > 0:
            candidate = raw[:last_complete_pos]
            try:
                result = _json.loads(candidate)
                return result, True
            except _json.JSONDecodeError:
                pass

        return {}, False

    def _extract_last_complete_pair(self, raw: str) -> tuple:
        """尝试提取最后一个完整的 key-value 对。"""
        pattern = r'("[^"\\]*(?:\\.[^"\\]*)*"\s*:\s*(?:"[^"\\]*(?:\\.[^"\\]*)*"|[\d.]+|true|false|null|\[[^\]]*\]|\{[^{}]*\}))'

        matches = list(re.finditer(pattern, raw))
        if matches:
            last_match = matches[-1]
            try:
                prefix = raw[:last_match.start()]
                suffix = raw[last_match.end():]

                if suffix.strip() in ("", ",", " ,"):
                    return _json.loads("{" + last_match.group() + "}"), True
            except Exception:
                pass

        key_pattern = r'"([^"\\]*(?:\\.[^"\\]*)*)"\s*:\s*'
        key_matches = list(re.finditer(key_pattern, raw))
        if key_matches:
            last_km = key_matches[-1]
            after_key = raw[last_km.end():]
            simple_value_match = re.match(r'(-?[\d.]+)\s*[,}]', after_key)
            if simple_value_match:
                key = last_km.group(1)
                value = simple_value_match.group(1)
                try:
                    if "." in value:
                        num_val = float(value)
                    else:
                        num_val = int(value)
                    return {key: num_val}, True
                except ValueError:
                    pass

        return {}, False

    # ──────────────────────────────────────────────
    #  响应转换工具
    # ──────────────────────────────────────────────

    @staticmethod
    def _flatten_system(system) -> str:
        """将 system prompt 转为纯字符串。"""
        if isinstance(system, str):
            return system
        if isinstance(system, list):
            return "\n\n".join(
                b["text"] if isinstance(b, dict) else str(b)
                for b in system
            )
        return str(system)

    @staticmethod
    def _convert_tool_def(tool: dict) -> dict:
        """Anthropic 工具定义 → OpenAI 工具定义。"""
        return {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }

    @staticmethod
    def _convert_message(msg: dict) -> dict:
        """转换单条消息（处理 Anthropic 的 tool_result 格式）。"""
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if isinstance(content, str):
            return {"role": role, "content": content}

        if role == "assistant":
            parts = []
            tool_calls = []
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type"):
                        if block.type == "text":
                            parts.append(block.text)
                        elif block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": _json.dumps(block.input),
                                },
                            })
                        # ✅ 忽略其他非标准块（如 output_truncated）
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
            text = "\n".join(parts)
            # 兜底防御：assistant 消息 content 与 tool_calls 双空会被
            # OpenAI/DeepSeek 以 400 拒绝（content or tool_calls must be set）。
            # 有 tool_calls 时 content=None 合法；双空则用空串占位，避免请求失败。
            result = {
                "role": "assistant",
                "content": text or (None if tool_calls else ""),
            }
            if tool_calls:
                result["tool_calls"] = tool_calls
            return result

        if role == "user" and isinstance(content, list):
            tool_msgs = []
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": str(block.get("content", "")),
                    })
                elif isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            if tool_msgs:
                return tool_msgs
            if text_parts:
                return {"role": "user", "content": "\n".join(text_parts)}
            return {"role": "user", "content": str(content)}

        return {"role": role, "content": str(content)}

    def _convert_oai_response_with_parse_recovery(self, choice) -> list:
        """OpenAI 响应 → Anthropic 风格（含 JSON 截断修复）。"""
        blocks = []
        msg = choice.message

        if msg.content:
            blocks.append(SimpleNamespace(type="text", text=msg.content))

        if msg.tool_calls:
            for tc in msg.tool_calls:
                raw_args = tc.function.arguments or "{}"
                parsed_args, parse_error = self._safe_parse_json(raw_args)

                if parse_error:
                    repaired_args, ok = self._repair_truncated_json(raw_args)
                    if ok:
                        blocks.append(SimpleNamespace(
                            type="tool_use",
                            id=tc.id,
                            name=tc.function.name,
                            input=repaired_args,
                        ))
                    else:
                        blocks.append(SimpleNamespace(
                            type="tool_use",
                            id=tc.id,
                            name=tc.function.name,
                            input={"_json_parse_error": parse_error, "_raw_args": raw_args[:200]},
                        ))
                else:
                    blocks.append(SimpleNamespace(
                        type="tool_use",
                        id=tc.id,
                        name=tc.function.name,
                        input=parsed_args,
                    ))

        return blocks if blocks else [SimpleNamespace(type="text", text="")]

