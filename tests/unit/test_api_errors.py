"""单元测试：services/api_errors.py（错误常量、分类、重试配置）"""
import pytest
from engine.errors import (
    APIErrorType,
    HTTPStatus,
    APIErrorMessage,
    RetryConfig,
    LoopConfig,
    JSONParseConfig,
    classify_api_error,
    is_retryable_error,
    get_error_message,
    get_retry_delay,
    get_max_retries_for_error,
)


class TestAPIErrorType:
    """测试错误类型枚举的完整性。"""
    def test_all_error_types_covered(self):
        """确保所有 HTTP 错误都有对应的 ErrorType。"""
        # 检查 HTTPStatus 和 APIErrorType 的覆盖关系
        # 这不是一个 exhaustive test，但覆盖了主要场景
        assert APIErrorType.RATE_LIMIT.value == "rate_limit"
        assert APIErrorType.SERVER_OVERLOAD.value == "server_overload"
        assert APIErrorType.AUTH_ERROR.value == "auth_error"
        assert APIErrorType.PROMPT_TOO_LONG.value == "prompt_too_long"
        assert APIErrorType.MAX_OUTPUT_TOKENS.value == "max_output_tokens"
        assert APIErrorType.JSON_PARSE_ERROR.value == "json_parse_error"


class TestHTTPStatus:
    """测试 HTTP 状态码常量。"""
    def test_status_codes(self):
        assert HTTPStatus.RATE_LIMIT == 429
        assert HTTPStatus.SERVER_OVERLOAD == 529
        assert HTTPStatus.UNAUTHORIZED == 401
        assert HTTPStatus.FORBIDDEN == 403
        assert HTTPStatus.BAD_REQUEST == 400
        assert HTTPStatus.NOT_FOUND == 404


class TestRetryConfig:
    """测试重试配置常量。"""
    def test_defaults(self):
        assert RetryConfig.DEFAULT_MAX_RETRIES == 3
        assert RetryConfig.BASE_DELAY_MS == 1000
        assert RetryConfig.MAX_DELAY_MS == 32000
        assert RetryConfig.JITTER_RATIO == 0.25
        assert RetryConfig.OVERLOAD_BASE_DELAY_MS == 500


class TestLoopConfig:
    """测试 Agent Loop 保护配置。"""
    def test_turn_limits(self):
        assert LoopConfig.DEFAULT_MAX_TURNS == 50
        assert LoopConfig.SUBAGENT_MAX_TURNS == 80

    def test_error_thresholds(self):
        assert LoopConfig.MAX_CONSECUTIVE_TOOL_ERRORS == 5
        assert LoopConfig.MAX_CONSECUTIVE_LLM_ERRORS == 3


class TestClassifyApiError:
    """测试 API 错误分类。"""

    def test_429_rate_limit(self):
        err = Exception("429 Rate limit exceeded")
        assert classify_api_error(err) == APIErrorType.RATE_LIMIT

    def test_529_server_overload(self):
        err = Exception("529 Server overloaded")
        assert classify_api_error(err) == APIErrorType.SERVER_OVERLOAD

    def test_timeout(self):
        err = Exception("Request timeout")
        assert classify_api_error(err) == APIErrorType.TIMEOUT

    def test_connection_error(self):
        err = Exception("Connection error")
        assert classify_api_error(err) == APIErrorType.CONNECTION_ERROR

    def test_json_parse_error(self):
        err = Exception("JSON decode error: Expecting value")
        assert classify_api_error(err) == APIErrorType.JSON_PARSE_ERROR

    def test_billing_error(self):
        err = Exception("Credit balance too low")
        assert classify_api_error(err) == APIErrorType.BILLING_ERROR

    def test_error_with_status_429(self):
        class MockError(Exception):
            status = 429
        err = MockError("rate limit")
        assert classify_api_error(err) == APIErrorType.RATE_LIMIT

    def test_error_with_status_401(self):
        class MockError(Exception):
            status = 401
        err = MockError("unauthorized")
        assert classify_api_error(err) == APIErrorType.AUTH_ERROR

    def test_error_with_status_400_prompt(self):
        class MockError(Exception):
            status = 400
            message = "prompt is too long"
        err = MockError("prompt is too long")
        assert classify_api_error(err) == APIErrorType.PROMPT_TOO_LONG

    def test_error_with_status_400_max_tokens(self):
        class MockError(Exception):
            status = 400
            message = "max_tokens exceeded"
        err = MockError("max_tokens exceeded")
        assert classify_api_error(err) == APIErrorType.MAX_OUTPUT_TOKENS

    def test_error_with_status_500(self):
        class MockError(Exception):
            status = 500
        err = MockError("internal error")
        assert classify_api_error(err) == APIErrorType.SERVER_ERROR

    def test_token_revoked(self):
        err = Exception("OAuth token has been revoked")
        assert classify_api_error(err) == APIErrorType.TOKEN_REVOKED


class TestIsRetryableError:
    """测试错误可重试性判断。"""
    def test_retryable_types(self):
        assert is_retryable_error(APIErrorType.RATE_LIMIT) is True
        assert is_retryable_error(APIErrorType.SERVER_OVERLOAD) is True
        assert is_retryable_error(APIErrorType.TIMEOUT) is True
        assert is_retryable_error(APIErrorType.CONNECTION_ERROR) is True
        assert is_retryable_error(APIErrorType.SERVER_ERROR) is True

    def test_unretryable_types(self):
        assert is_retryable_error(APIErrorType.AUTH_ERROR) is False
        assert is_retryable_error(APIErrorType.INVALID_API_KEY) is False
        assert is_retryable_error(APIErrorType.PROMPT_TOO_LONG) is False
        assert is_retryable_error(APIErrorType.JSON_PARSE_ERROR) is False
        assert is_retryable_error(APIErrorType.UNKNOWN) is False


class TestGetErrorMessage:
    """测试用户友好的错误消息。"""
    def test_rate_limit_message(self):
        msg = get_error_message(APIErrorType.RATE_LIMIT)
        assert "rate limit" in msg.lower() or "wait" in msg.lower()

    def test_timeout_message(self):
        msg = get_error_message(APIErrorType.TIMEOUT)
        assert "timeout" in msg.lower() or "connection" in msg.lower()

    def test_unknown_message(self):
        msg = get_error_message(APIErrorType.UNKNOWN)
        assert len(msg) > 0


class TestGetRetryDelay:
    """测试重试延迟计算。"""
    def test_exponential_backoff(self):
        delay1 = get_retry_delay(1, APIErrorType.RATE_LIMIT)
        delay2 = get_retry_delay(2, APIErrorType.RATE_LIMIT)
        delay3 = get_retry_delay(3, APIErrorType.RATE_LIMIT)
        # 指数增长
        assert delay2 > delay1
        assert delay3 > delay2

    def test_max_delay_cap(self):
        # 即使 attempt 很大，也应该被 MAX_DELAY_MS 限制
        delay = get_retry_delay(100, APIErrorType.RATE_LIMIT)
        assert delay <= RetryConfig.MAX_DELAY_MS

    def test_retry_after_header(self):
        # 有 Retry-After 头时，应该直接使用它
        delay = get_retry_delay(1, APIErrorType.RATE_LIMIT, retry_after_ms=5000)
        assert delay == 5000

    def test_overload_uses_shorter_base(self):
        delay_normal = get_retry_delay(1, APIErrorType.RATE_LIMIT)
        delay_overload = get_retry_delay(1, APIErrorType.SERVER_OVERLOAD)
        # Overload 使用更短的 base delay
        assert delay_overload <= delay_normal


class TestGetMaxRetriesForError:
    """测试不同错误类型的最大重试次数。"""
    def test_prompt_too_long_uses_different_limit(self):
        ptl_max = get_max_retries_for_error(APIErrorType.PROMPT_TOO_LONG)
        normal_max = get_max_retries_for_error(APIErrorType.RATE_LIMIT)
        # Prompt too long 使用不同的限制
        assert ptl_max == RetryConfig.PROMPT_TOO_LONG_MAX_RETRIES
        assert normal_max == RetryConfig.DEFAULT_MAX_RETRIES

    def test_server_overload_max_retries(self):
        max_retries = get_max_retries_for_error(APIErrorType.SERVER_OVERLOAD)
        assert max_retries == RetryConfig.OVERLOAD_MAX_RETRIES
