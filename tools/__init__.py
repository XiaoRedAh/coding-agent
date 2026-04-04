"""
tools 包 - 工具注册与组装

聚合所有工具模块的 JSON Schema 定义和处理函数映射。
核心工具（6 个）: read_file, write_file, edit_file, list_files, grep_search, run_shell
扩展工具（2 个）: task (agent), load_skill (skill)
其他工具: TodoWrite, task_*, background_*, 通信工具, compress

每个工具模块独立定义自己的 schema 和 handler，本模块统一收集。
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
    收集所有工具的 JSON Schema 定义。

    Returns:
        工具定义列表，供 Anthropic API 的 tools 参数使用
    """
    defs = []
    # 6 个核心工具
    for mod in [FileReadTool, FileWriteTool, FileEditTool,
                ListFilesTool, GrepSearchTool, BashTool]:
        defs.append(mod.DEFINITION)
    # 2 个扩展工具
    for mod in [AgentTool, SkillTool]:
        defs.append(mod.DEFINITION)
    # 其他工具
    defs.append(TodoTool.DEFINITION)
    defs.append(CompressTool.DEFINITION)
    for mod in [TaskTool, BackgroundTool, CommTool]:
        defs.extend(mod.DEFINITIONS)
    return defs


def get_all_handlers() -> dict:
    """
    构建所有工具的处理函数映射表。

    Returns:
        字典，key 为工具名称，value 为对应的处理函数
    """
    handlers = {
        # 6 个核心工具
        "read_file":    lambda **kw: FileReadTool.handle(kw["file_path"], kw.get("limit")),
        "write_file":   lambda **kw: FileWriteTool.handle(kw["file_path"], kw["content"]),
        "edit_file":    lambda **kw: FileEditTool.handle(kw["file_path"], kw["old_string"], kw["new_string"]),
        "list_files":   lambda **kw: ListFilesTool.handle(kw["pattern"], kw.get("path")),
        "grep_search":  lambda **kw: GrepSearchTool.handle(kw["pattern"], kw.get("path"), kw.get("include")),
        "run_shell":    lambda **kw: BashTool.handle(kw["command"], kw.get("timeout", 120)),
        # 2 个扩展工具
        "task":         lambda **kw: AgentTool.handle(kw["prompt"], kw.get("agent_type", "Explore")),
        "load_skill":   lambda **kw: SkillTool.handle(kw["name"]),
        # 其他工具
        "TodoWrite":    lambda **kw: state.todo.update(kw["items"]),
        "compress":     lambda **kw: CompressTool.handle(),
    }
    handlers.update(TaskTool.get_handlers())
    handlers.update(BackgroundTool.get_handlers())
    handlers.update(CommTool.get_handlers())
    return handlers
