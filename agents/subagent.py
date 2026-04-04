"""
agents/subagent.py - 子代理模块

实现一次性子代理（subagent），在独立的上下文中执行探索或通用工作。
Explore 类型只能读取和执行命令，general-purpose 类型额外可以写入和编辑文件。
子代理最多运行 30 轮工具调用循环。
"""

from bootstrap.state import client, MODEL
from tools.BashTool import handle as run_shell
from tools.FileReadTool import handle as run_read
from tools.FileWriteTool import handle as run_write
from tools.FileEditTool import handle as run_edit
from utils.truncate import truncate_result


def run_subagent(prompt: str, agent_type: str = "Explore") -> str:
    """
    启动一个子代理执行指定任务。

    子代理拥有独立的消息上下文，不影响主对话。
    根据 agent_type 决定可用工具集：
    - Explore: 只有 run_shell 和 read_file
    - 其他类型: 额外包含 write_file 和 edit_file
    """
    sub_tools = [
        {
            "name": "run_shell",
            "description": "Run shell command.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file with line numbers.",
            "input_schema": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    ]

    if agent_type != "Explore":
        sub_tools += [
            {
                "name": "write_file",
                "description": "Write file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["file_path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Edit file (exact string replacement).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string"},
                        "old_string": {"type": "string"},
                        "new_string": {"type": "string"},
                    },
                    "required": ["file_path", "old_string", "new_string"],
                },
            },
        ]

    sub_handlers = {
        "run_shell":  lambda **kw: run_shell(kw["command"]),
        "read_file":  lambda **kw: run_read(kw["file_path"]),
        "write_file": lambda **kw: run_write(kw["file_path"], kw["content"]),
        "edit_file":  lambda **kw: run_edit(kw["file_path"], kw["old_string"], kw["new_string"]),
    }

    sub_msgs = [{"role": "user", "content": prompt}]
    resp = None

    for _ in range(30):
        resp = client.messages.create(
            model=MODEL, messages=sub_msgs, tools=sub_tools, max_tokens=8000,
        )
        sub_msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                h = sub_handlers.get(b.name, lambda **kw: "Unknown tool")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": b.id,
                    "content": truncate_result(str(h(**b.input))),
                })
        sub_msgs.append({"role": "user", "content": results})

    if resp:
        return (
            "".join(b.text for b in resp.content if hasattr(b, "text"))
            or "(no summary)"
        )
    return "(subagent failed)"
