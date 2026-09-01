"""
agents/definitions.py - Agent 类型定义（S6 后为兼容层）

实际的类型定义已迁移到 YAML（agents/builtins/*.yaml + 用户自定义目录），
由 agents/registry.py 统一加载。本模块保留原有导出以兼容既有调用方：
    AGENT_DEFINITIONS / READ_ONLY_TOOLS / GENERAL_TOOLS /
    get_agent_config / get_filtered_tools

新代码请直接使用 agents.registry。
"""

# ──────────────────────────────────────────────
#  工具集名称常量（引用 tools/ 包中已注册的工具名）
# ──────────────────────────────────────────────

READ_ONLY_TOOLS = frozenset({
    "read_file", "list_files", "grep_search", "run_shell",
})

GENERAL_TOOLS = frozenset({
    "read_file", "write_file", "edit_file",
    "list_files", "grep_search", "run_shell",
    "load_skill",
    # 注意：不包含 "agent"，防止子 Agent 递归创建子 Agent
})

# ──────────────────────────────────────────────
#  注册表接入（内置 + 用户自定义统一来源）
# ──────────────────────────────────────────────

from agents.registry import default_registry  # noqa: E402

# 兼容旧形态：name -> config 映射（导入时的快照；
# 自定义 agent 生效后通过 get_agent_config 动态查询）
AGENT_DEFINITIONS = default_registry().as_dict()


def get_agent_config(agent_type: str) -> dict:
    """获取指定类型的 Agent 配置（含用户自定义类型）。"""
    return default_registry().get(agent_type)


def get_filtered_tools(allowed_tools: frozenset) -> tuple[list, dict]:
    """
    从全局工具注册表中过滤出指定的工具子集。

    使用延迟导入避免 tools/ ↔ agents/ 的循环依赖。
    返回 (tool_definitions, tool_handlers) 元组。
    """
    from tools import get_all_definitions, get_all_handlers
    all_defs = get_all_definitions()
    all_handlers = get_all_handlers()
    defs = [d for d in all_defs if d["name"] in allowed_tools]
    handlers = {k: v for k, v in all_handlers.items() if k in allowed_tools}
    return defs, handlers
