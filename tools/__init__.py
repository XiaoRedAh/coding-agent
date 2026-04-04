"""
tools 包 - 工具注册与组装

聚合所有工具模块的 JSON Schema 定义和处理函数映射。
每个工具模块（如 BashTool、FileReadTool 等）独立定义自己的 schema 和 handler，
本模块负责统一收集并对外提供 get_all_definitions() 和 get_all_handlers()。
"""

from tools import (
    BashTool, FileReadTool, FileWriteTool, FileEditTool,
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
    # 单定义工具（DEFINITION）
    for mod in [BashTool, FileReadTool, FileWriteTool, FileEditTool,
                AgentTool, SkillTool, CompressTool]:
        defs.append(mod.DEFINITION)
    # 单定义工具（TodoTool 的 DEFINITION）
    defs.append(TodoTool.DEFINITION)
    # 多定义工具（DEFINITIONS）
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
        # 单 handler 工具
        "bash":       lambda **kw: BashTool.handle(kw["command"]),
        "read_file":  lambda **kw: FileReadTool.handle(kw["path"], kw.get("limit")),
        "write_file": lambda **kw: FileWriteTool.handle(kw["path"], kw["content"]),
        "edit_file":  lambda **kw: FileEditTool.handle(kw["path"], kw["old_text"], kw["new_text"]),
        "TodoWrite":  lambda **kw: state.todo.update(kw["items"]),
        "task":       lambda **kw: AgentTool.handle(kw["prompt"], kw.get("agent_type", "Explore")),
        "load_skill": lambda **kw: SkillTool.handle(kw["name"]),
        "compress":   lambda **kw: CompressTool.handle(),
    }
    # 多 handler 工具
    handlers.update(TaskTool.get_handlers())
    handlers.update(BackgroundTool.get_handlers())
    handlers.update(CommTool.get_handlers())
    return handlers
