"""组件测试：query.py agent_loop（Mock LLM 响应，多场景覆盖）"""
import pytest
from unittest.mock import patch, MagicMock
from context.compact import TokenTracker, CircuitBreaker


def _mock_response(stop_reason="end_turn", content=None, input_tokens=100, output_tokens=50):
    """Create a mock LLMResponse."""
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content or [MagicMock(type="text", text="Done working")]
    resp.input_tokens = input_tokens
    resp.output_tokens = output_tokens
    # is_truncated 是 bool 字段，MagicMock 默认属性为 truthy 会被误判为截断
    resp.is_truncated = False
    resp.truncated_text = ""
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
    """Patch query.state with llm.chat as the mock point."""
    mock_state = MagicMock()
    mock_state.bg.drain.return_value = []
    mock_state.agent_tasks = None
    mock_state.todo = None
    mock_state.PERMISSION_MODE = "bypassPermissions"
    mock_state.perm_rules = MagicMock()
    mock_state.mcp = None
    mock_state.memory = None
    # llm.chat is the mock point now (replaces old client.messages.create)
    mock_llm = MagicMock()
    mock_state.llm = mock_llm

    with patch("agents.session.state", mock_state), \
         patch("agents.session.build_system_prompt", return_value=[{"type": "text", "text": "sys"}]), \
         patch("agents.session.is_coordinator_mode", return_value=False):
        yield mock_state, mock_llm


class TestAgentLoopBasic:
    def test_text_response_exits(self, mock_env):
        mock_state, mock_llm = mock_env
        mock_llm.chat.return_value = _mock_response()
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "hello"}]
        agent_loop(messages)
        assert mock_llm.chat.call_count == 1

    def test_single_tool_call(self, mock_env):
        mock_state, mock_llm = mock_env
        tool = _mock_tool_block("read_file", {"file_path": "test.py"})
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "read test.py"}]
        handlers = {"read_file": lambda **kw: "file content"}
        with patch("agents.session.get_all_handlers", return_value=handlers), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        assert mock_llm.chat.call_count == 2


class TestAgentLoopPermissions:
    def test_deny_returns_denied_message(self, mock_env):
        mock_state, mock_llm = mock_env
        mock_state.PERMISSION_MODE = "default"
        tool = _mock_tool_block("run_shell", {"command": "rm -rf /"})
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "delete"}]
        with patch("agents.session.get_all_handlers", return_value={}), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "deny", "reason": "Blocked"}):
            agent_loop(messages)
        tool_msg = messages[2]
        assert any("Permission denied" in str(r.get("content", "")) for r in tool_msg["content"])

    def test_tool_error_doesnt_crash(self, mock_env):
        mock_state, mock_llm = mock_env
        tool = _mock_tool_block("read_file", {"file_path": "bad.py"})
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        def bad_handler(**kw):
            raise FileNotFoundError("not found")
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "read bad"}]
        with patch("agents.session.get_all_handlers", return_value={"read_file": bad_handler}), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        tool_msg = messages[2]
        assert any("Error" in str(r.get("content", "")) for r in tool_msg["content"])


class TestAgentLoopMultiTool:
    def test_two_tools_same_turn(self, mock_env):
        mock_state, mock_llm = mock_env
        tool1 = _mock_tool_block("read_file", {"file_path": "a.py"}, "t1")
        tool2 = _mock_tool_block("read_file", {"file_path": "b.py"}, "t2")
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool1, tool2]),
            _mock_response(),
        ]
        call_log = []
        def tracking_handler(**kw):
            call_log.append(kw["file_path"])
            return f"content of {kw['file_path']}"
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "read two files"}]
        with patch("agents.session.get_all_handlers", return_value={"read_file": tracking_handler}), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        assert call_log == ["a.py", "b.py"]

    def test_three_round_conversation(self, mock_env):
        mock_state, mock_llm = mock_env
        tools = [
            _mock_tool_block("list_files", {"pattern": "*.py"}, "t1"),
            _mock_tool_block("read_file", {"file_path": "main.py"}, "t2"),
            _mock_tool_block("grep_search", {"pattern": "TODO"}, "t3"),
        ]
        mock_llm.chat.side_effect = [
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
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "find TODOs"}]
        with patch("agents.session.get_all_handlers", return_value=handlers), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        assert mock_llm.chat.call_count == 4


class TestAgentLoopNotifications:
    def test_bg_notification_injected(self, mock_env):
        mock_state, mock_llm = mock_env
        mock_state.bg.drain.return_value = [
            {"task_id": "bg1", "status": "completed", "result": "build success"}
        ]
        mock_llm.chat.return_value = _mock_response()
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "status?"}]
        agent_loop(messages)
        assert any("background-results" in str(m.get("content", "")) for m in messages)

    def test_agent_task_notification_injected(self, mock_env):
        mock_state, mock_llm = mock_env
        mock_agent_tasks = MagicMock()
        # drain() 返回 (notifications, in_flight) 元组
        mock_agent_tasks.drain.return_value = (
            [{"task_id": "agent-abc", "agent_type": "explore", "status": "completed", "result": "Found 5 TODOs"}],
            0,
        )
        mock_agent_tasks.wait_and_drain.return_value = ([], 0)
        mock_state.agent_tasks = mock_agent_tasks
        mock_llm.chat.return_value = _mock_response()
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "check"}]
        agent_loop(messages)
        assert any("task-notification" in str(m.get("content", "")) for m in messages)


class TestAgentLoopUnknownTool:
    def test_unknown_tool_returns_error(self, mock_env):
        mock_state, mock_llm = mock_env
        tool = _mock_tool_block("nonexistent_tool", {}, "t1")
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool]),
            _mock_response(),
        ]
        from agents.session import agent_loop
        messages = [{"role": "user", "content": "do something"}]
        with patch("agents.session.get_all_handlers", return_value={}), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            agent_loop(messages)
        tool_msg = messages[2]
        assert any("Unknown tool" in str(r.get("content", "")) for r in tool_msg["content"])


class TestAgentLoopProtection:
    """测试 Agent Loop 保护机制（maxTurns + 错误计数）。"""

    def test_max_turns_limit(self, mock_env):
        """达到 max_turns 上限后应该停止。"""
        mock_state, mock_llm = mock_env

        # 创建一个无限循环场景：每次都返回 tool_use
        tool = _mock_tool_block("read_file", {"file_path": "a.py"}, "t1")
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool]),
        ] * 100  # 足够多，触发 maxTurns

        from agents.session import agent_loop
        messages = [{"role": "user", "content": "loop"}]
        handlers = {"read_file": lambda **kw: "content"}
        with patch("agents.session.get_all_handlers", return_value=handlers), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            tracker, breaker = agent_loop(messages, max_turns=10)

        # 应该最多调用 max_turns 次（10次后停止）
        assert mock_llm.chat.call_count <= 10 + 1  # +1 因为第一轮不检查

    def test_custom_max_turns(self, mock_env):
        """可以指定自定义 max_turns。"""
        mock_state, mock_llm = mock_env
        tool = _mock_tool_block("read_file", {"file_path": "a.py"}, "t1")
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool]),
        ] * 100

        from agents.session import agent_loop
        messages = [{"role": "user", "content": "loop"}]
        handlers = {"read_file": lambda **kw: "content"}
        with patch("agents.session.get_all_handlers", return_value=handlers), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            tracker, breaker = agent_loop(messages, max_turns=3)

        assert mock_llm.chat.call_count <= 4  # 3轮 + 1

    def test_consecutive_llm_error_stops(self, mock_env):
        """连续 LLM 错误达到阈值后应该停止。"""
        mock_state, mock_llm = mock_env

        from llm.adapter import LLMError
        from engine.errors import APIErrorType

        # 模拟连续的 LLM 错误
        mock_llm.chat.side_effect = [
            LLMError("API error", APIErrorType.RATE_LIMIT),
            LLMError("API error", APIErrorType.RATE_LIMIT),
            LLMError("API error", APIErrorType.RATE_LIMIT),
        ]

        from agents.session import agent_loop
        messages = [{"role": "user", "content": "test"}]
        with patch("agents.session.build_system_prompt", return_value=[{"type": "text", "text": "sys"}]):
            tracker, breaker = agent_loop(messages, max_turns=10)

        # 连续 3 个 LLM 错误后停止
        assert mock_llm.chat.call_count == 3

    def test_llm_error_injected_as_message(self, mock_env):
        """LLM 错误应该被注入为用户消息，让 LLM 知道发生了什么。"""
        mock_state, mock_llm = mock_env

        from llm.adapter import LLMError
        from engine.errors import APIErrorType

        call_count = [0]

        def side_effect_func(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise LLMError("API error", APIErrorType.RATE_LIMIT)
            return _mock_response()  # 第二次成功

        mock_llm.chat.side_effect = side_effect_func

        from agents.session import agent_loop
        messages = [{"role": "user", "content": "test"}]
        with patch("agents.session.build_system_prompt", return_value=[{"type": "text", "text": "sys"}]):
            tracker, breaker = agent_loop(messages)

        # 第二次调用成功，消息中应该包含错误注入
        assert call_count[0] == 2
        # 应该有错误消息被注入
        error_msgs = [m for m in messages if isinstance(m.get("content"), str) and "<error>" in m["content"]]
        assert len(error_msgs) >= 1

    def test_consecutive_tool_errors_within_turn(self, mock_env):
        """同一轮内多个工具错误达到阈值后应该停止。"""
        mock_state, mock_llm = mock_env

        # 同一轮内返回多个工具，都报错
        tool1 = _mock_tool_block("read_file", {"file_path": "bad1.py"}, "t1")
        tool2 = _mock_tool_block("read_file", {"file_path": "bad2.py"}, "t2")
        tool3 = _mock_tool_block("read_file", {"file_path": "bad3.py"}, "t3")
        tool4 = _mock_tool_block("read_file", {"file_path": "bad4.py"}, "t4")
        tool5 = _mock_tool_block("read_file", {"file_path": "bad5.py"}, "t5")
        tool6 = _mock_tool_block("read_file", {"file_path": "bad6.py"}, "t6")
        # 一次返回 6 个工具
        mock_llm.chat.side_effect = [
            _mock_response("tool_use", [tool1, tool2, tool3, tool4, tool5, tool6]),
        ]

        def bad_handler(**kw):
            raise FileNotFoundError("not found")

        from agents.session import agent_loop
        messages = [{"role": "user", "content": "loop"}]
        with patch("agents.session.get_all_handlers", return_value={"read_file": bad_handler}), \
             patch("agents.session.get_all_definitions", return_value=[]), \
             patch("agents.session.check_permission", return_value={"action": "allow", "reason": "ok"}):
            tracker, breaker = agent_loop(messages, max_turns=10)

        # 同一轮内 6 个工具都报错 >= MAX_CONSECUTIVE_TOOL_ERRORS(5)，应该停止
        # 实际 call_count = 1（只有一轮）
        assert mock_llm.chat.call_count == 1


class TestAgentLoopRecovery:
    """测试 Agent Loop 恢复机制。"""

    def test_error_counter_resets_on_success(self, mock_env):
        """成功响应后错误计数器应该重置。"""
        mock_state, mock_llm = mock_env

        from llm.adapter import LLMError
        from engine.errors import APIErrorType

        # 错误 1 次 → 成功 1 次 → 成功 2 次 → 退出
        mock_llm.chat.side_effect = [
            LLMError("API error", APIErrorType.RATE_LIMIT),  # 错误1，注入消息，继续
            _mock_response(),                                  # 成功1，重置计数，返回
        ]

        from agents.session import agent_loop
        messages = [{"role": "user", "content": "test"}]
        with patch("agents.session.build_system_prompt", return_value=[{"type": "text", "text": "sys"}]):
            tracker, breaker = agent_loop(messages, max_turns=10)

        # 错误后成功一次即退出
        assert mock_llm.chat.call_count == 2
