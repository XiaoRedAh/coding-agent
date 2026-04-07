"""
services/llm.py - LLM 调用适配层

统一 Anthropic SDK 和 OpenAI SDK 的调用接口，屏蔽格式差异。
query.py / subagent.py / compact.py / team.py 统一调用 llm.chat()，
不需要关心底层使用的是哪种 API 格式。

支持的 Provider：
- anthropic（默认）：Anthropic SDK → Claude 模型 / Anthropic 兼容代理
- openai：OpenAI SDK → GPT / DeepSeek / Qwen / 任何 OpenAI 兼容 API（如 OpenRouter）
"""

import os
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """标准化的 LLM 响应，屏蔽 Anthropic/OpenAI 格式差异。"""
    content: list          # Anthropic 风格的 content blocks
    stop_reason: str       # "end_turn" 或 "tool_use"
    input_tokens: int
    output_tokens: int
    _raw: Any = field(default=None, repr=False)  # 原始响应（调试用）


class LLMAdapter:
    """
    统一的 LLM 调用接口。

    用法：
        llm = LLMAdapter.from_env()
        resp = llm.chat(system_prompt, messages, tools, max_tokens)
        # resp.content / resp.stop_reason / resp.input_tokens 格式统一
    """

    def __init__(self, provider: str, client: Any, model: str):
        self.provider = provider
        self.client = client
        self.model = model

    @staticmethod
    def from_env() -> "LLMAdapter":
        """从环境变量自动创建适配器。"""
        provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
        model = os.environ["MODEL_ID"]

        if provider == "openai":
            from openai import OpenAI
            client = OpenAI(
                base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.getenv("OPENAI_API_KEY"),
            )
        else:
            from anthropic import Anthropic
            client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))

        return LLMAdapter(provider, client, model)

    def chat(
        self,
        system: Any,
        messages: list,
        tools: list = None,
        max_tokens: int = 8000,
    ) -> LLMResponse:
        """
        统一的 LLM 调用。

        Args:
            system: System prompt（str 或 list[dict] 均可）
            messages: 对话消息列表
            tools: 工具定义列表（Anthropic 格式）
            max_tokens: 最大输出 token
        Returns:
            LLMResponse（统一格式）
        """
        if self.provider == "openai":
            return self._call_openai(system, messages, tools, max_tokens)
        return self._call_anthropic(system, messages, tools, max_tokens)

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

    # ──────────────────────────────────────────────
    #  OpenAI Provider
    # ──────────────────────────────────────────────

    def _call_openai(self, system, messages, tools, max_tokens) -> LLMResponse:
        # 1. 转换 system prompt → messages[0]
        sys_text = self._flatten_system(system)
        oai_messages = [{"role": "system", "content": sys_text}]

        # 2. 转换 messages（处理 tool_result blocks）
        for msg in messages:
            converted = self._convert_message(msg)
            # _convert_message 对 tool_result 返回 list[dict]（多条 tool role 消息）
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
        choice = resp.choices[0]

        # 5. 标准化响应（转为 Anthropic 风格）
        content = self._convert_oai_response(choice)
        stop = "tool_use" if choice.finish_reason == "tool_calls" else "end_turn"

        return LLMResponse(
            content=content,
            stop_reason=stop,
            input_tokens=getattr(resp.usage, "prompt_tokens", 0),
            output_tokens=getattr(resp.usage, "completion_tokens", 0),
            _raw=resp,
        )

    @staticmethod
    def _flatten_system(system) -> str:
        """将 system prompt 转为纯字符串（Anthropic 的 list[dict] → str）。"""
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

        # 纯文本消息
        if isinstance(content, str):
            return {"role": role, "content": content}

        # assistant 消息（可能包含 tool_use blocks，来自 Anthropic 格式的响应对象）
        if role == "assistant":
            parts = []
            tool_calls = []
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "type"):
                        # Anthropic SDK 对象
                        if block.type == "text":
                            parts.append(block.text)
                        elif block.type == "tool_use":
                            import json
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": json.dumps(block.input),
                                },
                            })
                    elif isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
            result = {"role": "assistant", "content": "\n".join(parts) or None}
            if tool_calls:
                result["tool_calls"] = tool_calls
            return result

        # user 消息（可能包含 tool_result blocks）
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
            # OpenAI 格式：tool results 是独立的 "tool" role 消息
            # 但为了简化，合并为一条 user 消息
            if tool_msgs:
                return tool_msgs  # 返回列表，调用方需要 extend
            if text_parts:
                return {"role": "user", "content": "\n".join(text_parts)}
            return {"role": "user", "content": str(content)}

        return {"role": role, "content": str(content)}

    @staticmethod
    def _convert_oai_response(choice) -> list:
        """OpenAI 响应 → Anthropic 风格的 content blocks。"""
        from types import SimpleNamespace
        import json

        blocks = []
        msg = choice.message

        # 文本内容
        if msg.content:
            blocks.append(SimpleNamespace(type="text", text=msg.content))

        # 工具调用
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {}
                blocks.append(SimpleNamespace(
                    type="tool_use",
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        return blocks if blocks else [SimpleNamespace(type="text", text="")]
