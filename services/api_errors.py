"""
services/api_errors.py - API 错误常量与分类

集中管理所有 API 错误相关的常量、枚举、异常类和分类逻辑。
所有 LLM 调用相关的错误码、重试策略、用户提示信息都在此定义。
修改错误配置只需改这一处。

错误分类体系：
- RetryableError: 可重试错误（网络临时故障、限流等）
- UnretryableError: 不可重试错误（认证失败、参数错误等）
- RecoverableError: 可恢复错误（输出截断、工具参数错误等）

对应 Claude Code 的：
- services/api/errors.ts（错误分类 + 用户消息）
- services/api/withRetry.ts（重试逻辑 + 降级策略）
"""

import os
import enum
from typing import Optional


# ──────────────────────────────────────────────
#  异常定义
# ──────────────────────────────────────────────

class LLMError(Exception):
    """LLM 调用基础异常。"""
    def __init__(self, message: str, error_type: "APIErrorType" = None):
        super().__init__(message)
        self.error_type = error_type


class JSONParseError(LLMError):
    """JSON 解析失败异常（通常由输出截断导致）。"""
    def __init__(self, message: str, raw_content: str = ""):
        super().__init__(message, APIErrorType.JSON_PARSE_ERROR)
        self.raw_content = raw_content


class APIRetryExhaustedError(LLMError):
    """API 重试次数耗尽异常。"""
    def __init__(self, message: str, error_type: "APIErrorType", attempts: int):
        super().__init__(message, error_type)
        self.attempts = attempts


# ──────────────────────────────────────────────
#  API 错误类型枚举
# ──────────────────────────────────────────────

class APIErrorType(enum.Enum):
    """API 错误类型枚举，对应 classifyAPIError() 的返回值。"""
    # 可重试错误（临时性）
    RATE_LIMIT = "rate_limit"              # 429 - 请求过于频繁
    SERVER_OVERLOAD = "server_overload"     # 529 - 服务器过载
    TIMEOUT = "api_timeout"                 # 请求超时
    CONNECTION_ERROR = "connection_error"   # 网络连接错误
    SERVER_ERROR = "server_error"           # 5xx 服务器内部错误
    REQUEST_TIMEOUT = "request_timeout"     # 408 请求超时

    # 不可重试错误（需要用户介入）
    AUTH_ERROR = "auth_error"              # 401/403 认证失败
    TOKEN_REVOKED = "token_revoked"        # OAuth token 被撤销
    INVALID_API_KEY = "invalid_api_key"    # API Key 无效
    ORG_DISABLED = "org_disabled"          # 组织被禁用
    INVALID_MODEL = "invalid_model"        # 模型不可用
    BILLING_ERROR = "billing_error"         # 余额不足

    # 可恢复错误（需要特殊处理）
    PROMPT_TOO_LONG = "prompt_too_long"    # 上下文超出限制
    MAX_OUTPUT_TOKENS = "max_output_tokens" # 输出被截断
    MEDIA_SIZE_ERROR = "media_size_error"  # 媒体文件过大
    TOOL_USE_MISMATCH = "tool_use_mismatch"  # tool_use/tool_result 不匹配

    # 其他
    UNKNOWN = "unknown"                    # 未知错误
    JSON_PARSE_ERROR = "json_parse_error"  # JSON 解析失败（流式截断）


# ──────────────────────────────────────────────
#  HTTP 状态码常量
# ──────────────────────────────────────────────

class HTTPStatus:
    """HTTP 状态码常量，避免散落的 magic numbers。"""
    OK = 200
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    FORBIDDEN = 403
    NOT_FOUND = 404
    REQUEST_TIMEOUT = 408
    RATE_LIMIT = 429
    INTERNAL_SERVER_ERROR = 500
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    GATEWAY_TIMEOUT = 504
    SERVER_OVERLOAD = 529  # 非标准，常用于服务过载


# ──────────────────────────────────────────────
#  API 错误消息（用户友好提示）
# ──────────────────────────────────────────────

class APIErrorMessage:
    """用户友好的 API 错误消息。"""

    PROMPT_TOO_LONG = "Prompt is too long"
    RATE_LIMIT = "Rate limit reached. Please wait before trying again."
    SERVER_OVERLOAD = "Server is overloaded. Please try again in a moment."
    TIMEOUT = "Request timed out. Check your internet connection."
    CONNECTION_ERROR = "Unable to connect to API. Check your internet connection."
    INVALID_API_KEY = "Invalid API key. Please check your configuration."
    TOKEN_REVOKED = "OAuth token revoked. Please run /login again."
    ORG_DISABLED = "Your organization has been disabled."
    CREDIT_BALANCE_LOW = "Credit balance is too low."
    SERVER_ERROR = "Server error. Please try again."
    UNKNOWN = "An unknown error occurred."

    # 可恢复错误的具体消息
    JSON_PARSE_ERROR = "Failed to parse model output. The response may have been truncated."
    MAX_OUTPUT_TRUNCATED = "Output was truncated. Consider breaking your task into smaller steps."


# ──────────────────────────────────────────────
#  重试配置常量
# ──────────────────────────────────────────────

class RetryConfig:
    """API 重试配置。所有重试相关常量集中于此。"""

    # 重试次数
    DEFAULT_MAX_RETRIES = 3          # 默认最大重试次数
    PROMPT_TOO_LONG_MAX_RETRIES = 2  # Prompt 过长错误的最大重试次数（通常需要压缩上下文）

    # 退避策略
    BASE_DELAY_MS = 1000             # 基础退避延迟（毫秒）
    MAX_DELAY_MS = 32000             # 最大退避延迟（毫秒）
    JITTER_RATIO = 0.25              # 随机 jitter 比例（base * 0.25）

    # 429 特殊处理
    RATE_LIMIT_SHORT_RETRY_MS = 20000  # 短等待（<20s）直接重试
    RATE_LIMIT_COOLDOWN_MS = 600000    # 30 分钟 cooldown

    # 529 特殊处理
    OVERLOAD_MAX_RETRIES = 3          # 服务器过载最大重试次数
    OVERLOAD_BASE_DELAY_MS = 500      # 更短的初始延迟

    # 持久会话模式（无人值守）
    PERSISTENT_MAX_BACKOFF_MS = 300000  # 5 分钟
    PERSISTENT_RESET_CAP_MS = 21600000  # 6 小时
    HEARTBEAT_INTERVAL_MS = 30000       # 30 秒


# ──────────────────────────────────────────────
#  Agent Loop 配置常量
# ──────────────────────────────────────────────

class LoopConfig:
    """Agent Loop 保护配置。防止无限循环和长时间运行。"""

    # 最大轮次限制
    DEFAULT_MAX_TURNS = 50           # 默认最大执行轮次
    SUBAGENT_MAX_TURNS = 30          # SubAgent 默认最大轮次
    COORDINATOR_MAX_TURNS = 20      # Coordinator 默认最大轮次

    # 连续错误限制
    MAX_CONSECUTIVE_TOOL_ERRORS = 5  # 连续工具错误阈值
    MAX_CONSECUTIVE_LLM_ERRORS = 3  # 连续 LLM 调用错误阈值

    # 最小输出检测
    MIN_OUTPUT_LENGTH = 5           # 最小有效输出长度（用于检测静默失败）

    # 超时配置
    LLM_RESPONSE_TIMEOUT = 300      # LLM 响应超时（秒）


# ──────────────────────────────────────────────
#  JSON 截断恢复配置
# ──────────────────────────────────────────────

class JSONParseConfig:
    """JSON 解析失败恢复配置。"""

    MAX_REPAIR_ATTEMPTS = 3         # 最大修复尝试次数
    TRUNCATED_JSON_INDICATORS = [
        '{"',           # 对象开始但未完成
        '["',           # 数组开始但未完成
        ', "',          # 逗号分隔但未完成
    ]
    TRAILING_TRUNCATION_PATTERNS = [
        r'\{\s*$',      # 以 { 结尾
        r'\[\s*$',      # 以 [ 结尾
        r',\s*$',       # 以逗号结尾
        r'"\s*$',       # 以未闭合的引号结尾
    ]


# ──────────────────────────────────────────────
#  错误分类与消息生成
# ──────────────────────────────────────────────

def classify_api_error(error: Exception) -> APIErrorType:
    """
    根据异常类型分类 API 错误。

    Args:
        error: 捕获的异常对象
    Returns:
        APIErrorType 枚举值
    """
    error_msg = str(error).lower()
    error_type = type(error).__name__

    # 检查 status 属性（APIError 等 SDK 异常）
    status = getattr(error, "status", None)
    headers = getattr(error, "headers", None)

    if status is not None:
        try:
            status = int(status) if not isinstance(status, int) else status
        except (ValueError, TypeError):
            status = None

        if status == HTTPStatus.RATE_LIMIT:
            return APIErrorType.RATE_LIMIT

        if status == HTTPStatus.SERVER_OVERLOAD:
            return APIErrorType.SERVER_OVERLOAD

        if status == HTTPStatus.REQUEST_TIMEOUT:
            return APIErrorType.REQUEST_TIMEOUT

        if status == HTTPStatus.UNAUTHORIZED or status == HTTPStatus.FORBIDDEN:
            if "oauth" in error_msg or "token" in error_msg:
                return APIErrorType.TOKEN_REVOKED
            if "api-key" in error_msg or "invalid" in error_msg:
                return APIErrorType.INVALID_API_KEY
            return APIErrorType.AUTH_ERROR

        if status == HTTPStatus.NOT_FOUND:
            return APIErrorType.INVALID_MODEL

        if status >= 500:
            return APIErrorType.SERVER_ERROR

        if status == HTTPStatus.BAD_REQUEST:
            if "prompt is too long" in error_msg or "context" in error_msg:
                return APIErrorType.PROMPT_TOO_LONG
            if "max_tokens" in error_msg or "output" in error_msg:
                return APIErrorType.MAX_OUTPUT_TOKENS
            if "media" in error_msg or "image" in error_msg or "pdf" in error_msg:
                return APIErrorType.MEDIA_SIZE_ERROR
            if "tool_use" in error_msg or "tool_result" in error_msg:
                return APIErrorType.TOOL_USE_MISMATCH

    # 基于错误消息的分类（无 status 字段时）
    if "oauth" in error_msg or ("token" in error_msg and "revoked" in error_msg):
        return APIErrorType.TOKEN_REVOKED

    if "timeout" in error_msg:
        return APIErrorType.TIMEOUT

    if "connection" in error_msg or "connect" in error_msg:
        return APIErrorType.CONNECTION_ERROR

    if "json" in error_msg and ("decode" in error_msg or "parse" in error_msg):
        return APIErrorType.JSON_PARSE_ERROR

    if "rate limit" in error_msg or "429" in error_msg:
        return APIErrorType.RATE_LIMIT

    if "overload" in error_msg or "529" in error_msg:
        return APIErrorType.SERVER_OVERLOAD

    if "balance" in error_msg or "credit" in error_msg:
        return APIErrorType.BILLING_ERROR

    return APIErrorType.UNKNOWN


def is_retryable_error(error_type: APIErrorType) -> bool:
    """
    判断某种错误类型是否可重试。

    Args:
        error_type: APIErrorType 枚举值
    Returns:
        True if the error should trigger a retry
    """
    retryable_types = {
        APIErrorType.RATE_LIMIT,
        APIErrorType.SERVER_OVERLOAD,
        APIErrorType.TIMEOUT,
        APIErrorType.CONNECTION_ERROR,
        APIErrorType.SERVER_ERROR,
        APIErrorType.REQUEST_TIMEOUT,
    }
    return error_type in retryable_types


def get_error_message(error_type: APIErrorType) -> str:
    """
    获取用户友好的错误消息。

    Args:
        error_type: APIErrorType 枚举值
    Returns:
        可显示给用户的错误消息
    """
    message_map = {
        APIErrorType.RATE_LIMIT: APIErrorMessage.RATE_LIMIT,
        APIErrorType.SERVER_OVERLOAD: APIErrorMessage.SERVER_OVERLOAD,
        APIErrorType.TIMEOUT: APIErrorMessage.TIMEOUT,
        APIErrorType.CONNECTION_ERROR: APIErrorMessage.CONNECTION_ERROR,
        APIErrorType.INVALID_API_KEY: APIErrorMessage.INVALID_API_KEY,
        APIErrorType.TOKEN_REVOKED: APIErrorMessage.TOKEN_REVOKED,
        APIErrorType.ORG_DISABLED: APIErrorMessage.ORG_DISABLED,
        APIErrorType.BILLING_ERROR: APIErrorMessage.CREDIT_BALANCE_LOW,
        APIErrorType.SERVER_ERROR: APIErrorMessage.SERVER_ERROR,
        APIErrorType.PROMPT_TOO_LONG: APIErrorMessage.PROMPT_TOO_LONG,
        APIErrorType.MAX_OUTPUT_TOKENS: APIErrorMessage.MAX_OUTPUT_TRUNCATED,
        APIErrorType.MEDIA_SIZE_ERROR: "Media file is too large.",
        APIErrorType.TOOL_USE_MISMATCH: "Tool use sequence error.",
        APIErrorType.JSON_PARSE_ERROR: APIErrorMessage.JSON_PARSE_ERROR,
        APIErrorType.UNKNOWN: APIErrorMessage.UNKNOWN,
        APIErrorType.AUTH_ERROR: APIErrorMessage.INVALID_API_KEY,
        APIErrorType.INVALID_MODEL: "Selected model is not available.",
        APIErrorType.REQUEST_TIMEOUT: APIErrorMessage.TIMEOUT,
    }
    return message_map.get(error_type, APIErrorMessage.UNKNOWN)


def get_retry_delay(
    attempt: int,
    error_type: APIErrorType,
    retry_after_ms: Optional[int] = None,
) -> int:
    """
    计算重试延迟时间（毫秒），使用指数退避 + jitter。

    Args:
        attempt: 当前重试次数（从 1 开始）
        error_type: 错误类型
        retry_after_ms: API 返回的 Retry-After 头（毫秒），如有
    Returns:
        延迟时间（毫秒）
    """
    # 优先使用 API 返回的 Retry-After
    if retry_after_ms is not None:
        # 如果 Retry-After 超过最大延迟，限制它
        if retry_after_ms > RetryConfig.MAX_DELAY_MS:
            return RetryConfig.MAX_DELAY_MS
        return retry_after_ms

    # 根据错误类型选择基础延迟
    if error_type == APIErrorType.SERVER_OVERLOAD:
        base = RetryConfig.OVERLOAD_BASE_DELAY_MS
    else:
        base = RetryConfig.BASE_DELAY_MS

    # 指数退避：base * 2^(attempt-1)
    delay_ms = base * (2 ** (attempt - 1))

    # 限制最大延迟（在加 jitter 之前）
    delay_ms = min(delay_ms, RetryConfig.MAX_DELAY_MS)

    # 添加随机 jitter: base * 0.25 * random（jitter 也受最大延迟限制）
    import random
    jitter = int(delay_ms * RetryConfig.JITTER_RATIO * random.random())
    delay_ms = min(delay_ms + jitter, RetryConfig.MAX_DELAY_MS)

    return delay_ms


def get_max_retries_for_error(error_type: APIErrorType) -> int:
    """
    获取特定错误类型的最大重试次数。

    Args:
        error_type: APIErrorType 枚举值
    Returns:
        最大重试次数
    """
    if error_type == APIErrorType.PROMPT_TOO_LONG:
        return RetryConfig.PROMPT_TOO_LONG_MAX_RETRIES
    if error_type == APIErrorType.SERVER_OVERLOAD:
        return RetryConfig.OVERLOAD_MAX_RETRIES
    return RetryConfig.DEFAULT_MAX_RETRIES
