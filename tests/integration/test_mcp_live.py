"""
集成测试：services/mcp.py 的真实 MCP 服务器连接（Bug 修复后验证）

覆盖两类真实服务器：
1. 官方 MCP 服务器 @modelcontextprotocol/server-everything（需 node/npx）
   —— 真实世界的 MCP 示例，端到端验证 echo / get-sum 工具
2. 自包含 Python MCP 服务器 tests/fixtures/mcp_echo_server.py（零外部依赖）
   —— 确定性验证调用超时（hang）、stderr 管道死锁防护（flood_stderr）

运行：
    pytest tests/integration/test_mcp_live.py -v -s
"""
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.mcp import McpConnection, McpManager

_FIXTURE_SERVER = Path(__file__).parent.parent / "fixtures" / "mcp_echo_server.py"
_PYTHON = sys.executable

_NPX_AVAILABLE = shutil.which("npx") is not None

requires_npx = pytest.mark.skipif(
    not _NPX_AVAILABLE, reason="npx not available (needed for official MCP server)"
)


def _content_text(result: dict) -> str:
    """提取 MCP 工具结果里的文本内容。"""
    content = result.get("content", [])
    if isinstance(content, list):
        return "\n".join(
            c.get("text", "") for c in content if c.get("type") == "text"
        )
    return str(content)


# ──────────────────────────────────────────────
#  官方 MCP 服务器（真实世界示例）
# ──────────────────────────────────────────────

@requires_npx
class TestOfficialServerEverything:
    def test_connect_and_discover_tools(self):
        conn = McpConnection("everything", "npx", ["-y", "@modelcontextprotocol/server-everything"])
        assert conn.connect(), "failed to connect to server-everything"
        try:
            assert len(conn.tools) > 0
            names = [t["name"] for t in conn.tools]
            assert "echo" in names
            assert "get-sum" in names
        finally:
            conn.close()

    def test_echo_tool_roundtrip(self):
        conn = McpConnection("everything", "npx", ["-y", "@modelcontextprotocol/server-everything"])
        assert conn.connect()
        try:
            result = conn.call_tool("echo", {"message": "ping123"})
            assert result.get("isError") is not True
            assert "ping123" in _content_text(result)
        finally:
            conn.close()

    def test_get_sum_tool(self):
        conn = McpConnection("everything", "npx", ["-y", "@modelcontextprotocol/server-everything"])
        assert conn.connect()
        try:
            result = conn.call_tool("get-sum", {"a": 2, "b": 3})
            assert result.get("isError") is not True
            assert "5" in _content_text(result)
        finally:
            conn.close()


# ──────────────────────────────────────────────
#  自包含 Python MCP 服务器（确定性：echo/add/超时/stderr）
# ──────────────────────────────────────────────

class TestFixtureServer:
    def _connect(self):
        conn = McpConnection("fixture", _PYTHON, [str(_FIXTURE_SERVER)])
        assert conn.connect(), "fixture server failed to connect"
        return conn

    def test_echo(self):
        conn = self._connect()
        try:
            result = conn.call_tool("echo", {"message": "hello mcp"})
            assert result.get("isError") is not True
            assert _content_text(result) == "hello mcp"
        finally:
            conn.close()

    def test_add(self):
        conn = self._connect()
        try:
            result = conn.call_tool("add", {"a": 2, "b": 3})
            assert _content_text(result) == "5"
        finally:
            conn.close()

    def test_manager_end_to_end(self):
        """验证工具发现 + Anthropic 格式转换 + handler 端到端调用。"""
        conn = self._connect()
        mgr = McpManager()
        mgr.connections["fixture"] = conn
        try:
            defs = mgr.get_tool_definitions()
            names = {d["name"] for d in defs}
            assert "mcp__fixture__echo" in names
            assert "mcp__fixture__add" in names

            handlers = mgr.get_tool_handlers()
            assert handlers["mcp__fixture__add"](a=4, b=5) == "9"
            assert handlers["mcp__fixture__echo"](message="x") == "x"
        finally:
            mgr.close_all()

    def test_timeout_on_hang(self):
        """hang 工具永不响应，_send_request 带短超时应返回 None 而非永久阻塞。"""
        conn = self._connect()
        try:
            start = time.monotonic()
            result = conn._send_request(
                "tools/call", {"name": "hang", "arguments": {}}, timeout=2
            )
            elapsed = time.monotonic() - start
            assert result is None, "hanging tool should time out and return None"
            assert elapsed < 10, f"timeout not effective, took {elapsed:.1f}s"
        finally:
            conn.close()

    def test_call_tool_hang_returns_error(self, monkeypatch):
        """call_tool 对超时的工具应返回 isError 结果，而非卡死。"""
        import services.mcp as mcp_mod
        monkeypatch.setattr(mcp_mod, "MCP_TOOL_TIMEOUT", 2)
        conn = self._connect()
        try:
            start = time.monotonic()
            result = conn.call_tool("hang", {})
            elapsed = time.monotonic() - start
            assert result.get("isError") is True
            assert elapsed < 10
        finally:
            conn.close()

    def test_stderr_flood_no_deadlock(self):
        """stderr 写满管道缓冲区仍能拿到工具结果（stderr 消费线程防死锁）。"""
        conn = self._connect()
        try:
            # 10000 行 * ~19 字节 ≈ 190KB，远超 64KB 管道缓冲区；
            # 若无 stderr 消费线程，子进程写 stderr 会阻塞 → 无法返回结果
            result = conn.call_tool("flood_stderr", {"n": 10000})
            assert result.get("isError") is not True
            assert "10000" in _content_text(result)
        finally:
            conn.close()
