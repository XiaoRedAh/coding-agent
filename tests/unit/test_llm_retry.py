"""单元测试：services/llm.py（重试机制）"""
import pytest
from unittest.mock import MagicMock, patch
from services.llm import LLMAdapter, LLMResponse, LLMError, APIRetryExhaustedError
from services.api_errors import APIErrorType, RetryConfig


class MockAPIError(Exception):
    """模拟 API 错误。"""
    def __init__(self, message, status=None, headers=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.headers = headers or {}


class TestLLMAdapterRetry:
    """测试 LLM 适配器的重试机制。"""

    @pytest.fixture
    def adapter(self):
        return LLMAdapter(provider="openai", client=MagicMock(), model="test-model")

    def test_successful_call_no_retry(self, adapter):
        """成功调用不应该触发重试。"""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Done"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 20

        adapter.client.chat.completions.create.return_value = mock_resp

        result = adapter.chat("sys", [{"role": "user", "content": "hi"}])
        assert result.content[0].text == "Done"
        assert adapter.client.chat.completions.create.call_count == 1

    def test_rate_limit_retry(self, adapter):
        """429 错误应该触发重试。"""
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Done after retry"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 20

        # 前两次调用失败，第 3 次成功
        rate_limit_err = MockAPIError("Rate limit", status=429)
        adapter.client.chat.completions.create.side_effect = [
            rate_limit_err,
            rate_limit_err,
            mock_resp,
        ]

        with patch("time.sleep") as mock_sleep:
            result = adapter.chat("sys", [{"role": "user", "content": "hi"}], max_tokens=100)

        # 应该重试 2 次后成功
        assert adapter.client.chat.completions.create.call_count == 3
        assert result.content[0].text == "Done after retry"
        # 应该 sleep 两次（指数退避）
        assert mock_sleep.call_count == 2

    def test_non_retryable_error_raises_immediately(self, adapter):
        """不可重试错误应该立即抛出。"""
        auth_err = MockAPIError("Invalid API key", status=401)

        adapter.client.chat.completions.create.side_effect = [auth_err]

        with pytest.raises(LLMError) as exc_info:
            adapter.chat("sys", [{"role": "user", "content": "hi"}])

        # "Invalid API key" with 401 status → INVALID_API_KEY
        assert exc_info.value.error_type == APIErrorType.INVALID_API_KEY
        assert adapter.client.chat.completions.create.call_count == 1

    def test_max_retries_exhausted(self, adapter):
        """超过最大重试次数应该抛出 APIRetryExhaustedError。"""
        rate_limit_err = MockAPIError("Rate limit", status=429)

        # 所有调用都失败
        adapter.client.chat.completions.create.side_effect = [rate_limit_err] * 10

        with patch("time.sleep"):
            with pytest.raises(APIRetryExhaustedError) as exc_info:
                adapter.chat("sys", [{"role": "user", "content": "hi"}], max_tokens=100)

        # 应该重试了 DEFAULT_MAX_RETRIES 次
        assert exc_info.value.attempts == RetryConfig.DEFAULT_MAX_RETRIES
        assert exc_info.value.error_type == APIErrorType.RATE_LIMIT

    def test_timeout_error_is_retryable(self, adapter):
        """超时错误应该可重试。"""
        timeout_err = MockAPIError("Request timeout")

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Done"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 20

        adapter.client.chat.completions.create.side_effect = [timeout_err, mock_resp]

        with patch("time.sleep"):
            result = adapter.chat("sys", [{"role": "user", "content": "hi"}])

        assert adapter.client.chat.completions.create.call_count == 2

    def test_connection_error_is_retryable(self, adapter):
        """连接错误应该可重试。"""
        conn_err = MockAPIError("Connection error")

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "Done"
        mock_resp.choices[0].message.tool_calls = None
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.usage.prompt_tokens = 100
        mock_resp.usage.completion_tokens = 20

        adapter.client.chat.completions.create.side_effect = [conn_err, mock_resp]

        with patch("time.sleep"):
            result = adapter.chat("sys", [{"role": "user", "content": "hi"}])

        assert adapter.client.chat.completions.create.call_count == 2
