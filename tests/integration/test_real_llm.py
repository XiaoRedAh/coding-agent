"""
Layer 3 集成测试：真实 LLM 调用（需要 API Key）

运行方式：
    # 确保 .env 配置了有效的 API Key
    pytest tests/integration/ -v -s

    # 只跑快速测试
    pytest tests/integration/ -v -s -k "simple"

注意：
- 每个测试消耗 ~1K-5K token
- 全部运行约 $0.01-0.10（使用免费模型则 $0）
- 需要网络连接
- 使用 bypassPermissions 模式（无需交互确认）
"""

import os
import sys
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Load .env BEFORE checking skip conditions (try .env first, fallback to .env.example)
from dotenv import load_dotenv
_project_root = Path(__file__).parent.parent.parent
if not load_dotenv(_project_root / ".env", override=True):
    load_dotenv(_project_root / ".env.example", override=True)

def _has_real_llm():
    """Check if a real LLM is configured (not the test default)."""
    model = os.getenv("MODEL_ID", "")
    provider = os.getenv("LLM_PROVIDER", "anthropic")
    if not model or model == "test-model":
        return False
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    return bool(os.getenv("ANTHROPIC_API_KEY"))

pytestmark = pytest.mark.skipif(
    not _has_real_llm(),
    reason="No real LLM configured (set MODEL_ID + API key in .env)",
)

import time

def _call_with_retry(llm, max_retries=3, **kwargs):
    """Call LLM with retry on 429 rate limit (common with free models)."""
    for attempt in range(max_retries):
        try:
            return llm.chat(**kwargs)
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = 5 * (attempt + 1)
                print(f"\n  ⚠ Rate limited, waiting {wait}s (attempt {attempt+1}/{max_retries})...")
                time.sleep(wait)
            else:
                raise
    return llm.chat(**kwargs)  # last attempt, let it fail


@pytest.fixture(scope="module")
def llm():
    """Create a real LLM adapter from .env config."""
    os.environ.setdefault("PERMISSION_MODE", "bypassPermissions")
    from services.llm import LLMAdapter
    return LLMAdapter.from_env()


class TestLLMConnection:
    """测试 LLM 连接是否正常"""

    def test_simple_text_response(self, llm):
        """LLM 能返回文本响应"""
        resp = _call_with_retry(llm,
            system="You are a helpful assistant. Reply in one short sentence.",
            messages=[{"role": "user", "content": "Say 'hello world'"}],
            max_tokens=100,
        )
        assert resp.stop_reason == "end_turn"
        assert len(resp.content) >= 1
        assert resp.content[0].type == "text"
        assert len(resp.content[0].text) > 0
        print(f"  Response: {resp.content[0].text[:100]}")
        print(f"  Tokens: {resp.input_tokens}in / {resp.output_tokens}out")


class TestToolCalling:
    """测试 LLM 的 Tool Calling 能力"""

    def test_tool_use_triggered(self, llm):
        """LLM 能正确调用工具"""
        tools = [{
            "name": "get_weather",
            "description": "Get weather for a city",
            "input_schema": {
                "type": "object",
                "properties": {
                    "city": {"type": "string", "description": "City name"},
                },
                "required": ["city"],
            },
        }]
        resp = _call_with_retry(llm,
            system="Use the get_weather tool to answer weather questions.",
            messages=[{"role": "user", "content": "What's the weather in Tokyo?"}],
            tools=tools,
            max_tokens=200,
        )
        assert resp.stop_reason == "tool_use"
        tool_blocks = [b for b in resp.content if b.type == "tool_use"]
        assert len(tool_blocks) >= 1
        assert tool_blocks[0].name == "get_weather"
        assert "city" in tool_blocks[0].input
        print(f"  Tool call: {tool_blocks[0].name}({tool_blocks[0].input})")

    def test_multi_turn_with_tool_result(self, llm):
        """LLM 能处理工具返回结果并继续对话"""
        tools = [{
            "name": "read_file",
            "description": "Read file contents",
            "input_schema": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        }]
        # Turn 1: LLM calls tool
        resp1 = _call_with_retry(llm,
            system="Use read_file to read files. Answer based on file content.",
            messages=[{"role": "user", "content": "Read the file hello.txt"}],
            tools=tools,
            max_tokens=200,
        )
        assert resp1.stop_reason == "tool_use"

        # Turn 2: Provide tool result, LLM should respond with text
        messages = [
            {"role": "user", "content": "Read the file hello.txt"},
            {"role": "assistant", "content": resp1.content},
            {"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": resp1.content[0].id if hasattr(resp1.content[0], "id") else "t1",
                "content": "Hello World! This is a test file.",
            }]},
        ]
        resp2 = _call_with_retry(llm,
            system="Use read_file to read files. Answer based on file content.",
            messages=messages,
            tools=tools,
            max_tokens=200,
        )
        # Should respond with text (not another tool call)
        assert resp2.stop_reason == "end_turn"
        text = "".join(b.text for b in resp2.content if hasattr(b, "text"))
        assert len(text) > 0
        print(f"  Final response: {text[:100]}")


class TestAgentLoop:
    """测试完整的 Agent Loop（需要完整项目初始化）"""

    def test_simple_task(self, llm, tmp_path):
        """Agent 能完成简单的文件创建任务"""
        os.chdir(tmp_path)
        # This test requires full project init which is heavy
        # Mark as expected to need manual verification
        pytest.skip("Full agent loop test requires manual project init")
