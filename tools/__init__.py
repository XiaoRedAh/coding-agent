"""
tools 包 - 工具注册与组装

聚合内置工具和 MCP 工具的定义与处理函数。
AgentTool 是统一入口（SubAgent），TaskTool 负责任务管理。

对应 Claude Code 的 assembleToolPool()。
"""

from tools import (
    BashTool, FileReadTool, FileWriteTool, FileEditTool,
    ListFilesTool, GrepSearchTool,
    TodoTool, TaskTool, AgentTool, SkillTool,
)
from runtime import state


def get_all_definitions() -> list:
    """收集所有工具定义（内置 + MCP）。agent 工具的 enum 动态反映注册表。"""
    defs = []
    for mod in [FileReadTool, FileWriteTool, FileEditTool,
                ListFilesTool, GrepSearchTool, BashTool]:
        defs.append(mod.DEFINITION)
    defs.append(AgentTool.get_definition())  # 动态：含自定义 agent 类型
    defs.append(SkillTool.DEFINITION)
    defs.append(TodoTool.DEFINITION)
    defs.extend(TaskTool.DEFINITIONS)

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
        "run_shell":    lambda **kw: BashTool.handle(kw["command"], kw.get("timeout", 120), kw.get("run_in_background", False)),
        "agent":        lambda **kw: AgentTool.handle(
            kw["prompt"], kw.get("description", ""), kw.get("type", "general"),
            kw.get("run_in_background", False),
        ),
        "load_skill":   lambda **kw: SkillTool.handle(kw["name"], kw.get("args", "")),
        "TodoWrite":    lambda **kw: state.todo.update(kw["items"]),
    }
    handlers.update(TaskTool.get_handlers())

    if state.mcp:
        handlers.update(state.mcp.get_tool_handlers())
    return handlers
