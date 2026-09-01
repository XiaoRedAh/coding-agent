"""
core/results.py - 结构化工具结果（S5）

替代"用字符串前缀嗅探错误"的脆弱约定（B5 问题）：
    ToolResult(ok, content, error)

设计约束：
- 循环层（core/loop.py）的错误判定优先读 tool_result 元数据，
  未提供时回退到字符串嗅探（is_error_output），渐进迁移
- 工具的 handle() 返回值保持 str（对 LLM 的 tool_result content），
  ToolResult 供框架内部使用
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolResult:
    """结构化工具执行结果。"""
    ok: bool
    content: str          # 供 LLM 的文本内容（错误时通常为用户可读的错误说明）
    error: str | None = None  # 错误类别标识（如 "not_found" / "permission_denied"）

    def to_str(self) -> str:
        """转为注入 tool_result 的字符串。"""
        return self.content

    @staticmethod
    def success(content: str) -> "ToolResult":
        return ToolResult(ok=True, content=content)

    @staticmethod
    def failure(content: str, error: str = "tool_error") -> "ToolResult":
        return ToolResult(ok=False, content=content, error=error)
