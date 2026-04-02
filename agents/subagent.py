"""
agents/subagent.py - 子代理模块

实现一次性子代理（subagent），在独立的上下文中执行探索或通用工作。
Explore 类型只能读取和执行命令，general-purpose 类型额外可以写入和编辑文件。
子代理最多运行 30 轮工具调用循环。
"""

from config import client, MODEL
from tools.base import run_bash, run_read, run_write, run_edit


def run_subagent(prompt: str, agent_type: str = "Explore") -> str:
    """
    启动一个子代理执行指定任务。

    子代理拥有独立的消息上下文，不影响主对话。
    根据 agent_type 决定可用工具集：
    - Explore: 只有 bash 和 read_file
    - 其他类型: 额外包含 write_file 和 edit_file

    Args:
        prompt: 子代理的任务提示词
        agent_type: 代理类型（"Explore" 或 "general-purpose"）
    Returns:
        子代理的最终文本输出摘要
    """
    # 基础工具集：命令执行和文件读取
    sub_tools = [
        {
            "name": "bash",
            "description": "Run command.",
            "input_schema": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
        {
            "name": "read_file",
            "description": "Read file.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    ]

    # 非 Explore 类型追加写入和编辑工具
    if agent_type != "Explore":
        sub_tools += [
            {
                "name": "write_file",
                "description": "Write file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Edit file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
        ]

    # 子代理的工具处理函数映射
    sub_handlers = {
        "bash": lambda **kw: run_bash(kw["command"]),
        "read_file": lambda **kw: run_read(kw["path"]),
        "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
        "edit_file": lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
    }

    sub_msgs = [{"role": "user", "content": prompt}]
    resp = None

    # 最多 30 轮工具调用循环
    for _ in range(30):
        resp = client.messages.create(
            model=MODEL, messages=sub_msgs, tools=sub_tools, max_tokens=8000
        )
        sub_msgs.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            break
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                h = sub_handlers.get(b.name, lambda **kw: "Unknown tool")
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.id,
                        "content": str(h(**b.input))[:50000],
                    }
                )
        sub_msgs.append({"role": "user", "content": results})

    if resp:
        return (
            "".join(b.text for b in resp.content if hasattr(b, "text"))
            or "(no summary)"
        )
    return "(subagent failed)"
