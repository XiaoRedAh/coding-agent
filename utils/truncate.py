"""
utils/truncate.py - 工具结果截断

统一的结果截断策略：保留头尾各一半，中间截断。
这样既能看到开头的上下文，又能看到末尾的关键输出（如编译错误、测试结果摘要）。

对应 Claude Code 的 maxResultSizeChars + 截断机制。
"""

from runtime.state import settings

# 截断阈值（config/defaults.yaml tools.max_result_chars）
MAX_RESULT_CHARS = settings.tools.max_result_chars


def truncate_result(result: str) -> str:
    """
    截断过长的工具结果，保留头尾各一半。

    Args:
        result: 原始工具结果字符串
    Returns:
        截断后的字符串（不超过 MAX_RESULT_CHARS）
    """
    if len(result) <= MAX_RESULT_CHARS:
        return result
    keep_each = (MAX_RESULT_CHARS - 60) // 2
    truncated = len(result) - keep_each * 2
    return (
        result[:keep_each]
        + f"\n\n[... truncated {truncated} chars ...]\n\n"
        + result[-keep_each:]
    )
