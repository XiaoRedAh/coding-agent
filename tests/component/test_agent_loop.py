"""组件测试：query.py agent_loop（Mock LLM 响应，多场景覆盖）"""
import pytest
from unittest.mock import patch, MagicMock
from services.compact import TokenTracker, CircuitBreaker


def _mock_response(stop_reason="end_turn", content=None, input_tokens=100, output_tokens=50):
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content or [MagicMock(type="text", text="Done")]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


def _mock_tool_block(name, input_dict, tool_id="t1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.id = tool_id
    block.input = input_dict
    return block


@pytest.fixture
def mock_env():
    """Patch query.state as a proper MagicMock module (not a function)."""
    mock_state = MagicMock()
    mock_state.bg.drain.return_value = []
    mock_state.bus.read_inbox.return_value = []
    mock_state.agent_tasks = None
    mock_state.todo = None
    mock_state.PERMISSION_MODE = "bypassPermissions"
    mock_state.perm_rules = MagicMock()
    mock_state.mcp = None
    mock_state.memory = None

    with patch("query.state", mock_state), \
         patch("query.client") as mock_client, \
         patch("query.build_system_prompt", return_value=[{"type": "text", "text": "sys"}]), \
         patch("query.is_coordinator_mode", return_value=False):
        yield mock_state, mock_client


class TestAgentLoopBasic:
    def test_text_response_exits(self, mock_env):
        mock_state, mock_client = mock_env
        mock_client.messages.create.return_value = _mock_response()
        from query import agent_loop
        messages = [{"role": "user", "content": "hello"}]
        agent_loop(messages)
        assert mock_client.messages.create.call_count == 1

    def test_single_tool_call(self, mock_env):
        mock_state, mock_client = mock_env
        tool = _mock_tool_block("read_file", {"file_path": "test.py"})
        mock_client.messages.create.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        from query import agent_loop
        messages = [{"role": "user", "content": "read test.py"}]
        handlers = {"read_file": lambda **kw: "file content"}
        with patch("query.get_all_handlers", return_value=handlers), \
             patch("query.get_all_definitions", return_value=[]), \
             patch("query.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        assert mock_client.messages.create.call_count == 2


class TestAgentLoopPermissions:
    def test_deny_returns_denied_message(self, mock_env):
        mock_state, mock_client = mock_env
        mock_state.PERMISSION_MODE = "default"
        tool = _mock_tool_block("run_shell", {"command": "rm -rf /"})
        mock_client.messages.create.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        from query import agent_loop
        messages = [{"role": "user", "content": "delete"}]
        with patch("query.get_all_handlers", return_value={}), \
             patch("query.get_all_definitions", return_value=[]), \
             patch("query.check_permission", return_value={"action": "deny", "reason": "Blocked"}):
            agent_loop(messages)
        tool_msg = messages[2]
        assert any("Permission denied" in str(r.get("content", "")) for r in tool_msg["content"])

    def test_tool_error_doesnt_crash(self, mock_env):
        mock_state, mock_client = mock_env
        tool = _mock_tool_block("read_file", {"file_path": "bad.py"})
        mock_client.messages.create.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        def bad_handler(**kw):
            raise FileNotFoundError("not found")
        from query import agent_loop
        messages = [{"role": "user", "content": "read bad"}]
        with patch("query.get_all_handlers", return_value={"read_file": bad_handler}), \
             patch("query.get_all_definitions", return_value=[]), \
             patch("query.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        tool_msg = messages[2]
        assert any("Error" in str(r.get("content", "")) for r in tool_msg["content"])


class TestAgentLoopMultiTool:
    def test_two_tools_same_turn(self, mock_env):
        mock_state, mock_client = mock_env
        tool1 = _mock_tool_block("read_file", {"file_path": "a.py"}, "t1")
        tool2 = _mock_tool_block("read_file", {"file_path": "b.py"}, "t2")
        mock_client.messages.create.side_effect = [
            _mock_response("tool_use", [tool1, tool2]),
            _mock_response(),
        ]
        call_log = []
        def tracking_handler(**kw):
            call_log.append(kw["file_path"])
            return f"content of {kw['file_path']}"
        from query import agent_loop
        messages = [{"role": "user", "content": "read two files"}]
        with patch("query.get_all_handlers", return_value={"read_file": tracking_handler}), \
             patch("query.get_all_definitions", return_value=[]), \
             patch("query.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        assert call_log == ["a.py", "b.py"]

    def test_three_round_conversation(self, mock_env):
        mock_state, mock_client = mock_env
        tools = [
            _mock_tool_block("list_files", {"pattern": "*.py"}, "t1"),
            _mock_tool_block("read_file", {"file_path": "main.py"}, "t2"),
            _mock_tool_block("grep_search", {"pattern": "TODO"}, "t3"),
        ]
        mock_client.messages.create.side_effect = [
            _mock_response("tool_use", [tools[0]]),
            _mock_response("tool_use", [tools[1]]),
            _mock_response("tool_use", [tools[2]]),
            _mock_response(),
        ]
        handlers = {
            "list_files": lambda **kw: "main.py",
            "read_file": lambda **kw: "# TODO",
            "grep_search": lambda **kw: "main.py:1:# TODO",
        }
        from query import agent_loop
        messages = [{"role": "user", "content": "find TODOs"}]
        with patch("query.get_all_handlers", return_value=handlers), \
             patch("query.get_all_definitions", return_value=[]), \
             patch("query.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        assert mock_client.messages.create.call_count == 4
        assert len(messages) == 8  # user + (asst+tool)*3 + asst_final


class TestAgentLoopNotifications:
    def test_bg_notification_injected(self, mock_env):
        mock_state, mock_client = mock_env
        mock_state.bg.drain.return_value = [
            {"task_id": "bg1", "status": "completed", "result": "build success"}
        ]
        mock_client.messages.create.return_value = _mock_response()
        from query import agent_loop
        messages = [{"role": "user", "content": "status?"}]
        agent_loop(messages)
        assert any("background-results" in str(m.get("content", "")) for m in messages)

    def test_agent_task_notification_injected(self, mock_env):
        mock_state, mock_client = mock_env
        mock_agent_tasks = MagicMock()
        mock_agent_tasks.drain.return_value = [
            {"task_id": "agent-abc", "agent_type": "explore", "status": "completed", "result": "Found 5 TODOs"}
        ]
        mock_state.agent_tasks = mock_agent_tasks
        mock_client.messages.create.return_value = _mock_response()
        from query import agent_loop
        messages = [{"role": "user", "content": "check"}]
        agent_loop(messages)
        assert any("task-notification" in str(m.get("content", "")) for m in messages)

    def test_inbox_message_injected(self, mock_env):
        mock_state, mock_client = mock_env
        mock_state.bus.read_inbox.return_value = [
            {"type": "message", "from": "researcher", "content": "Found bug"}
        ]
        mock_client.messages.create.return_value = _mock_response()
        from query import agent_loop
        messages = [{"role": "user", "content": "check inbox"}]
        agent_loop(messages)
        assert any("inbox" in str(m.get("content", "")) for m in messages)


class TestAgentLoopUnknownTool:
    def test_unknown_tool_returns_error(self, mock_env):
        mock_state, mock_client = mock_env
        tool = _mock_tool_block("nonexistent_tool", {}, "t1")
        mock_client.messages.create.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        from query import agent_loop
        messages = [{"role": "user", "content": "do something"}]
        with patch("query.get_all_handlers", return_value={}), \
             patch("query.get_all_definitions", return_value=[]), \
             patch("query.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        tool_msg = messages[2]
        assert any("Unknown tool" in str(r.get("content", "")) for r in tool_msg["content"])
