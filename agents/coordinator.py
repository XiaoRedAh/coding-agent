"""
agents/coordinator.py - Coordinator 协调者模式

Coordinator 是主 Agent 的一种运行模式，通过 COORDINATOR_MODE=1 激活。

架构：
- Coordinator 接收用户请求，自己进行任务规划和拆分
- 并行派生多个 Worker 执行子任务
- 收集 task-notification 汇总结果后响应用户

特点：
- 无依赖并行：任务必须可独立执行
- 职责清晰：Coordinator 规划，Worker 执行
- 日志完善：用户可看到所有子 agent 的启动、状态、完成情况
"""

import os

from runtime.state import WORKDIR

# ──────────────────────────────────────────────
#  模式激活
# ──────────────────────────────────────────────

def is_coordinator_mode() -> bool:
    """检查 Coordinator 模式是否激活（通过环境变量）"""
    return os.getenv("COORDINATOR_MODE", "").lower() in ("1", "true")


# ──────────────────────────────────────────────
#  Coordinator 工具白名单
# ──────────────────────────────────────────────

# Coordinator 工具集：只读调研工具 + agent 工具
# 注意：不包含 write_file/edit_file，Coordinator 不直接修改文件
COORDINATOR_ALLOWED_TOOLS = frozenset({
    "agent",         # 派生 Worker
    "read_file",     # 读取文件
    "list_files",    # 列出文件
    "grep_search",   # 搜索代码
    "run_shell",     # 运行命令
})


# ──────────────────────────────────────────────
#  工具描述（用于日志输出）
# ──────────────────────────────────────────────

COORDINATOR_TOOL_DESCRIPTIONS = {
    "agent":         "派生子 Agent",
    "read_file":     "读取文件",
    "list_files":    "列出文件",
    "grep_search":   "搜索代码",
    "run_shell":     "执行命令",
}


# ──────────────────────────────────────────────
#  Coordinator 系统提示词
# ──────────────────────────────────────────────

COORDINATOR_SYSTEM_PROMPT = f"""\
You are an Orchestrator — a project manager that decomposes complex requests \
into independent sub-tasks, delegates to Workers, and synthesizes results.

## YOUR RESPONSIBILITIES

1. **Plan**: Analyze request, decompose into independent sub-tasks
2. **Delegate**: Spawn Workers to execute sub-tasks in parallel. When multiple independent subtasks need to be launched, multiple agent tool calls must be generated within the same response to achieve parallel execution.
3. **Synthesize**: Collect results and present final output to user

## DECOMPOSITION RULES

**CRITICAL**: Sub-tasks must be truly independent:
- Each Worker works on DIFFERENT files or topics
- No Worker waits for another Worker
- Each outputs a self-contained result

**If tasks have dependencies, they CANNOT run in parallel — consider using SubAgent mode instead.**

## DELEGATION

- Use `agent(run_in_background=True)` for parallel execution
- Provide each Worker: task description, target files, expected output
- Workers run independently and concurrently

## RESULT SYNTHESIS

After Workers complete, check for these tags:
- `<in-flight-count>N</in-flight-count>`: N Workers still running, WAIT for more
- `<all-complete/>`: ALL Workers done, proceed to synthesize immediately

**IMPORTANT**: When you see `<all-complete/>`, do NOT wait — synthesize and respond immediately.

## WORKER TYPES

- **explore**: Read-only investigation
- **general**: Full capability (can execute any task, including file operations, shell commands, etc.)
- **verification**: Adversarial testing

## PARALLEL EXAMPLE

User: "Analyze this codebase: auth system, database, API, tests"

```
1. [Worker: explore] Analyze auth system
   - Files: auth/*.py
   - Output: Auth architecture summary

2. [Worker: explore] Analyze database models
   - Files: models/*.py, db/*.py
   - Output: DB schema summary

3. [Worker: explore] Analyze API endpoints
   - Files: api/*.py, routes/*.py
   - Output: API inventory

4. [Worker: explore] Analyze test coverage
   - Files: tests/*.py
   - Output: Test status report

PARALLEL: All 4 tasks — no dependencies, different files
```

## WORKING DIRECTORY: {WORKDIR}
"""


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
