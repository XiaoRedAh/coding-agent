"""
tools/AgentTool.py - 子代理派生工具

派生独立子代理执行隔离的探索或工作任务。
支持 Explore（只读）和 general-purpose（可读写）两种类型。
"""

DEFINITION = {
    "name": "task",
    "description": "Spawn a subagent for isolated exploration or work.",
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "agent_type": {
                "type": "string",
                "enum": ["Explore", "general-purpose"],
            },
        },
        "required": ["prompt"],
    },
}


def handle(prompt: str, agent_type: str = "Explore") -> str:
    """派生子代理执行任务"""
    from agents.subagent import run_subagent
    return run_subagent(prompt, agent_type)
