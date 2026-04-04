"""
tools 包 - 工具注册与组装

聚合所有工具模块的 JSON Schema 定义和处理函数映射。
核心工具（6 个）: read_file, write_file, edit_file, list_files, grep_search, run_shell
扩展工具（2 个）: agent, load_skill
其他工具: TodoWrite, task_*, background_*, 通信工具, compress

子 Agent 通过 agents/definitions.py 的 get_filtered_tools() 按工具名过滤本包的注册表，
实现工具定义和处理函数的零重复复用。
"""

from tools import (
    BashTool, FileReadTool, FileWriteTool, FileEditTool,
    ListFilesTool, GrepSearchTool,
    TodoTool, TaskTool, AgentTool, SkillTool,
    BackgroundTool, CommTool, CompressTool,
)
from bootstrap import state


def get_all_definitions() -> list:
    """收集所有工具的 JSON Schema 定义。"""
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
    return defs


def get_all_handlers() -> dict:
    """构建所有工具的处理函数映射表。"""
    handlers = {
        "read_file":    lambda **kw: FileReadTool.handle(kw["file_path"], kw.get("limit")),
        "write_file":   lambda **kw: FileWriteTool.handle(kw["file_path"], kw["content"]),
        "edit_file":    lambda **kw: FileEditTool.handle(kw["file_path"], kw["old_string"], kw["new_string"]),
        "list_files":   lambda **kw: ListFilesTool.handle(kw["pattern"], kw.get("path")),
        "grep_search":  lambda **kw: GrepSearchTool.handle(kw["pattern"], kw.get("path"), kw.get("include")),
        "run_shell":    lambda **kw: BashTool.handle(kw["command"], kw.get("timeout", 120)),
        "agent":        lambda **kw: AgentTool.handle(kw["prompt"], kw.get("description", ""), kw.get("type", "general"), kw.get("run_in_background", False)),
        "load_skill":   lambda **kw: SkillTool.handle(kw["name"]),
        "TodoWrite":    lambda **kw: state.todo.update(kw["items"]),
        "compress":     lambda **kw: CompressTool.handle(),
    }
    handlers.update(TaskTool.get_handlers())
    handlers.update(BackgroundTool.get_handlers())
    handlers.update(CommTool.get_handlers())
    return handlers
