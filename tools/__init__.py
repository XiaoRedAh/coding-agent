"""
tools 包 - 工具注册与组装

聚合内置工具和 MCP 工具的定义与处理函数。
内置工具由各工具模块定义，MCP 工具由 McpManager 动态提供。
两者在工具池中并列，通过 tools 参数统一传递给 Anthropic API。

对应 Claude Code 的 assembleToolPool()：
  内置工具（排序）+ MCP 工具（排序）→ 按名去重
"""

from tools import (
    BashTool, FileReadTool, FileWriteTool, FileEditTool,
    ListFilesTool, GrepSearchTool,
    TodoTool, TaskTool, AgentTool, SkillTool,
    BackgroundTool, CommTool, CompressTool,
)
from bootstrap import state


def get_all_definitions() -> list:
    """
    收集所有工具定义（内置 + MCP）。

    内置工具排在前面（稳定缓存前缀），MCP 工具追加在后面。
    对应 cc 的分区排序策略。
    """
    # 内置工具
    defs = []
    for mod in [FileReadTool, FileWriteTool, FileEditTool,
                ListFilesTool, GrepSearchTool, BashTool]:
        defs.append(mod.DEFINITION)
    for mod in [AgentTool, SkillTool]:
        defs.append(mod.DEFINITION)
    defs.append(TodoTool.DEFINITION)
    defs.append(CompressTool.DEFINITION)
    for mod in [TaskTool, BackgroundTool, CommTool]:
        defs.extend(mod.DEFINITIONS)

    # MCP 工具（追加在后面，不打乱内置工具的顺序）
    if state.mcp:
        defs.extend(state.mcp.get_tool_definitions())

    return defs


def get_all_handlers() -> dict:
    """构建所有工具的处理函数映射表（内置 + MCP）。"""
    handlers = {
        "read_file":    lambda **kw: FileReadTool.handle(kw["file_path"], kw.get("limit")),
        "write_file":   lambda **kw: FileWriteTool.handle(kw["file_path"], kw["content"]),
        "edit_file":    lambda **kw: FileEditTool.handle(kw["file_path"], kw["old_string"], kw["new_string"]),
        "list_files":   lambda **kw: ListFilesTool.handle(kw["pattern"], kw.get("path")),
        "grep_search":  lambda **kw: GrepSearchTool.handle(kw["pattern"], kw.get("path"), kw.get("include")),
        "run_shell":    lambda **kw: BashTool.handle(kw["command"], kw.get("timeout", 120)),
        "agent":        lambda **kw: AgentTool.handle(kw["prompt"], kw.get("description", ""), kw.get("type", "general"), kw.get("run_in_background", False)),
        "load_skill":   lambda **kw: SkillTool.handle(kw["name"], kw.get("args", "")),
        "TodoWrite":    lambda **kw: state.todo.update(kw["items"]),
        "compress":     lambda **kw: CompressTool.handle(),
    }
    handlers.update(TaskTool.get_handlers())
    handlers.update(BackgroundTool.get_handlers())
    handlers.update(CommTool.get_handlers())

    # MCP 工具处理函数
    if state.mcp:
        handlers.update(state.mcp.get_tool_handlers())

    return handlers
