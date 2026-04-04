"""
tools/BackgroundTool.py - 后台任务工具

在后台线程中异步执行命令，支持状态查询。
"""

from bootstrap import state

DEFINITIONS = [
    {
        "name": "background_run",
        "description": "Run command in background thread.",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "check_background",
        "description": "Check background task status.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
        },
    },
]


def get_handlers() -> dict:
    """返回后台任务工具的处理函数映射"""
    return {
        "background_run":   lambda **kw: state.bg.run(kw["command"], kw.get("timeout", 120)),
        "check_background": lambda **kw: state.bg.check(kw.get("task_id")),
    }
