"""
core/results.py - 结构化工具结果（S5 引入，本轮迁移完成）

替代"用字符串前缀嗅探错误"的脆弱约定（重构计划 B5 问题）。

设计要点：ToolResult 继承 str。
- 它本身就是工具输出的内容字符串（LLM 看到的就是这个文本，
  错误的具体报错信息包含在内）
- 额外携带结构化元数据供框架使用：
  - ok:      成功/失败（循环层错误计数的判定依据，替代前缀嗅探）
  - error:   错误类别（"not_found" / "timeout" / "command_failed" /
             "path_escape" / "invalid_input" / "permission_denied" /
             "unknown_tool" / "json_parse_error" / "mcp_error" / "io_error"...）
- str 子类保证零破坏迁移：既有代码的 startswith/切片/json 序列化
  全部照常工作

分层说明：
- ToolResult 是框架内部约定（Python 工具 handler → 循环层），
  LLM 不直接看到该对象
- LLM 的可见通道有两条：content 文本（含报错详情）+ 循环层注入的
  tool_result 块 is_error 标志（Anthropic 原生支持，见 core/loop.py）
"""

from __future__ import annotations


class ToolResult(str):
    """结构化工具结果（str 子类：内容即本体，元数据为附加属性）。"""

    ok: bool
    error: str | None

    def __new__(cls, content: str, ok: bool = True, error: str | None = None):
        if not isinstance(content, str):
            content = str(content)
        s = super().__new__(cls, content)
        s.ok = ok
        s.error = error
        return s

    # ── 工厂方法 ──

    @staticmethod
    def success(content: str) -> "ToolResult":
        return ToolResult(content, ok=True, error=None)

    @staticmethod
    def failure(content: str, error: str = "tool_error") -> "ToolResult":
        return ToolResult(content, ok=False, error=error)

    # ── 兼容 ──

    def to_str(self) -> str:
        """内容本体（str 子类即自身，保留旧接口）。"""
        return self

    def __repr__(self) -> str:
        if self.ok:
            return f"ToolResult.success({str.__repr__(self)})"
        return f"ToolResult.failure({str.__repr__(self)}, error={self.error!r})"
