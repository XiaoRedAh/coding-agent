"""单元测试：services/mcp.py（MCP 工具命名、管理器逻辑，不涉及真实进程/LLM）"""
import pytest
from services.mcp import (
    _normalize_name, build_mcp_tool_name, parse_mcp_tool_name,
    McpConnection, McpManager,
)


class TestNormalizeName:
    def test_simple(self):
        assert _normalize_name("github") == "github"

    def test_special_chars(self):
        assert _normalize_name("my-server.v2") == "my_server_v2"

    def test_strip_underscores(self):
        assert _normalize_name("__test__") == "test"

    def test_spaces(self):
        assert _normalize_name("my server") == "my_server"


class TestBuildMcpToolName:
    def test_basic(self):
        assert build_mcp_tool_name("github", "create_issue") == "mcp__github__create_issue"

    def test_normalize(self):
        assert build_mcp_tool_name("my-server", "get.data") == "mcp__my_server__get_data"


class TestParseMcpToolName:
    def test_valid(self):
        result = parse_mcp_tool_name("mcp__github__create_issue")
        assert result == ("github", "create_issue")

    def test_not_mcp(self):
        assert parse_mcp_tool_name("read_file") is None

    def test_malformed(self):
        assert parse_mcp_tool_name("mcp__nounderscore") is None


class TestMcpConnection:
    def test_init(self):
        conn = McpConnection("test", "echo", ["hello"])
        assert conn.name == "test"
        assert conn.command == "echo"
        assert conn.tools == []
        assert conn.instructions is None

    def test_close_no_process(self):
        conn = McpConnection("test", "echo")
        conn.close()  # Should not raise


class TestMcpManager:
    def test_init(self):
        mgr = McpManager()
        assert mgr.connections == {}
        assert mgr.server_count == 0
        assert mgr.tool_count == 0

    def test_get_tool_definitions_empty(self):
        mgr = McpManager()
        assert mgr.get_tool_definitions() == []

    def test_get_tool_handlers_empty(self):
        mgr = McpManager()
        assert mgr.get_tool_handlers() == {}

    def test_get_instructions_empty(self):
        mgr = McpManager()
        assert mgr.get_instructions() == ""

    def test_get_instructions_with_connected(self):
        mgr = McpManager()
        conn = McpConnection("test-server", "echo")
        conn.instructions = "Use these tools for testing."
        conn.tools = [{"name": "test_tool", "description": "A test", "inputSchema": {}}]
        mgr.connections["test-server"] = conn
        instr = mgr.get_instructions()
        assert "MCP Server Instructions" in instr
        assert "test-server" in instr
        assert "Use these tools for testing." in instr

    def test_get_tool_definitions_with_tools(self):
        mgr = McpManager()
        conn = McpConnection("github", "npx")
        conn.tools = [
            {"name": "create_issue", "description": "Create a GitHub issue", "inputSchema": {"type": "object"}},
            {"name": "list_repos", "description": "List repositories"},
        ]
        mgr.connections["github"] = conn
        defs = mgr.get_tool_definitions()
        assert len(defs) == 2
        assert defs[0]["name"] == "mcp__github__create_issue"
        assert "[MCP: github]" in defs[0]["description"]
        assert defs[1]["name"] == "mcp__github__list_repos"

    def test_get_tool_handlers_callable(self):
        mgr = McpManager()
        conn = McpConnection("test", "echo")
        conn.tools = [{"name": "hello", "description": "Say hello"}]
        mgr.connections["test"] = conn
        handlers = mgr.get_tool_handlers()
        assert "mcp__test__hello" in handlers
        assert callable(handlers["mcp__test__hello"])

    def test_description_truncation(self):
        mgr = McpManager()
        conn = McpConnection("srv", "cmd")
        conn.tools = [{"name": "t", "description": "x" * 3000}]
        mgr.connections["srv"] = conn
        defs = mgr.get_tool_definitions()
        assert len(defs[0]["description"]) <= 2100  # [MCP: srv] prefix + 2048

    def test_close_all(self):
        mgr = McpManager()
        conn = McpConnection("test", "echo")
        mgr.connections["test"] = conn
        mgr.close_all()
        assert mgr.connections == {}

    def test_load_no_config(self, tmp_workdir):
        """No config file → no connections."""
        mgr = McpManager()
        mgr.load_and_connect()
        assert mgr.server_count == 0


class TestMcpToolResultWrap:
    """S5 迁移：MCP 工具失败应返回 ToolResult.failure（原 'MCP Error:' 前缀嗅探不到）。"""

    def _manager_with_fake_conn(self, call_result):
        from types import SimpleNamespace
        mgr = McpManager()
        conn = SimpleNamespace(
            tools=[{"name": "query", "description": "Run a query"}],
            call_tool=lambda name, args: call_result,
            instructions=None,
        )
        mgr.connections["db"] = conn
        return mgr

    def test_success_returns_text(self):
        mgr = self._manager_with_fake_conn({
            "isError": False,
            "content": [{"type": "text", "text": "3 rows"}],
        })
        out = mgr.get_tool_handlers()["mcp__db__query"](sql="SELECT 1")
        assert out == "3 rows"
        assert not hasattr(out, "ok") or out.ok is True

    def test_error_returns_tool_result(self):
        mgr = self._manager_with_fake_conn({
            "isError": True,
            "content": [{"type": "text", "text": "syntax error near FROM"}],
        })
        out = mgr.get_tool_handlers()["mcp__db__query"](sql="BAD")
        from core.results import ToolResult
        from core.loop import is_tool_error
        assert isinstance(out, ToolResult)
        assert is_tool_error(out)              # 关键：旧字符串嗅探判不出，现在能判出
        assert out.error == "mcp_error"
        assert "syntax error near FROM" in out  # 报错详情对 LLM 可见

    def test_error_unknown_content(self):
        mgr = self._manager_with_fake_conn({"isError": True, "content": []})
        out = mgr.get_tool_handlers()["mcp__db__query"]()
        from core.loop import is_tool_error
        assert is_tool_error(out)
        assert "Unknown error" in out
