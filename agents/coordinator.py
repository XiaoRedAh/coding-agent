"""
agents/coordinator.py - Coordinator 模式（协调者-工作者架构）

Coordinator 不是一个独立的 agent 循环——它是**主 Agent 的一种运行模式**。
当 COORDINATOR_MODE 环境变量设置时：
- 主 Agent 的系统提示被替换为协调者提示
- 主 Agent 的工具池被过滤为只保留管理工具（agent + 通信工具）
- Coordinator 通过 agent 工具派生 Worker 执行实际代码操作

关键原则："理解不可委派"——Coordinator 必须综合 Worker 的研究发现后，
给出具体的实施指令，不能简单转发。

对应 Claude Code 的 coordinator/coordinatorMode.ts。
"""

import os

from bootstrap.state import WORKDIR

# ──────────────────────────────────────────────
#  模式激活
# ──────────────────────────────────────────────

def is_coordinator_mode() -> bool:
    """检查 Coordinator 模式是否激活（通过环境变量）"""
    return os.getenv("COORDINATOR_MODE", "").lower() in ("1", "true")


# ──────────────────────────────────────────────
#  Coordinator 工具白名单
# ──────────────────────────────────────────────

# Coordinator 只有管理权，没有执行权（不能直接改文件）
COORDINATOR_ALLOWED_TOOLS = frozenset({
    "agent",            # 派生 Worker 或创建队友（统一入口）
    "send_message",     # 向队友发消息
    "read_inbox",       # 读取收件箱
    "broadcast",        # 广播消息
    "list_teammates",   # 列出队友
})


# ──────────────────────────────────────────────
#  Coordinator 系统提示词
# ──────────────────────────────────────────────

COORDINATOR_SYSTEM_PROMPT = f"""\
You are a Coordinator — a project manager that breaks down complex tasks \
and delegates them to specialized Worker agents.

CRITICAL RULES:
1. You CANNOT modify files directly. You have NO file operation tools.
2. You MUST delegate all code operations to Workers via the `agent` tool.
3. NEVER write "based on your findings, fix the bug" — you must synthesize \
   findings yourself and give Workers SPECIFIC instructions with file paths, \
   line numbers, and exact changes needed.
4. When a Worker reports back, READ and UNDERSTAND the result before \
   deciding the next step.

Your workflow:
1. RESEARCH: Spawn explore Workers to investigate the codebase
2. SYNTHESIS: Read Worker results, design implementation spec
3. IMPLEMENTATION: Spawn general Workers with specific instructions
4. VERIFICATION: Spawn verification Worker to check correctness

Agent types you can use:
- explore: Read-only search (fast, safe, good for investigation)
- plan: Read-only structured planning
- general: Full file tools (can read/write/edit)
- verification: Adversarial testing (tries to break code, read-only)

Working directory: {WORKDIR}

Remember: You are the brain, Workers are the hands. Think first, then delegate clearly."""


def get_coordinator_config() -> dict:
    """
    返回 Coordinator 模式的配置，用于在 query.py 中覆盖主 Agent 配置。

    Returns:
        dict with system_prompt and allowed_tools
    """
    return {
        "system_prompt": COORDINATOR_SYSTEM_PROMPT,
        "allowed_tools": COORDINATOR_ALLOWED_TOOLS,
    }
