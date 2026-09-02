"""
agents/coordinator.py - Coordinator 协调者模式（薄适配层）

Coordinator 是主 Agent 的一种运行模式（规划-执行分离）：
- Coordinator 接收用户请求，自己进行任务规划和拆分
- 并行派生多个 Worker 执行子任务
- 收集 task-notification 汇总结果后响应用户

编排收敛（原硬编码 → 配置化）：
- 系统提示词：prompts/coordinator.md（经 PromptLoader 三级覆盖，
  ~/.xiaoagent/prompts 或 .xiaoagent/prompts 可整体替换）
- 工具白名单：config（defaults.yaml coordinator.allowed_tools）
- 激活方式：COORDINATOR_MODE=1 环境变量 或 config coordinator.enabled
  （环境变量优先，兼容既有用法）
"""

import os

from prompts.loader import load_prompt
from runtime import state
from runtime.state import settings


# ──────────────────────────────────────────────
#  模式激活（环境变量优先，其次配置）
# ──────────────────────────────────────────────

def is_coordinator_mode() -> bool:
    """检查 Coordinator 模式是否激活。

    优先级：环境变量 COORDINATOR_MODE=1/true > 配置 coordinator.enabled。
    环境变量未设置时回落到配置项。
    """
    env = os.getenv("COORDINATOR_MODE", "")
    if env:
        return env.lower() in ("1", "true")
    return settings.coordinator.enabled


# ──────────────────────────────────────────────
#  工具白名单（来自配置，保留模块属性兼容既有引用）
# ──────────────────────────────────────────────

# Coordinator 工具集：只读调研工具 + agent 工具
# 注意：默认不含 write_file/edit_file，Coordinator 不直接修改文件
COORDINATOR_ALLOWED_TOOLS = frozenset(settings.coordinator.allowed_tools)


# ──────────────────────────────────────────────
#  配置组装
# ──────────────────────────────────────────────

def get_coordinator_system_prompt() -> str:
    """加载 Coordinator 系统提示词（prompts/coordinator.md，三级覆盖）。"""
    return load_prompt("coordinator.md").replace("{{workdir}}", str(state.WORKDIR))


def get_coordinator_config() -> dict:
    """
    返回 Coordinator 模式的配置，用于在 session.py 中覆盖主 Agent 配置。

    Returns:
        dict with system_prompt and allowed_tools
    """
    return {
        "system_prompt": get_coordinator_system_prompt(),
        "allowed_tools": frozenset(settings.coordinator.allowed_tools),
    }
