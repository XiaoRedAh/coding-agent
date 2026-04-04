"""
agents/definitions.py - 内置智能体类型定义

定义 4 种内置子 Agent 类型的配置：提示词、工具集、行为参数。
所有类型共用统一的 get_filtered_tools() 从全局工具注册表动态过滤，
避免工具定义的重复维护。

对应 Claude Code 的 built-in/ 目录下的预置 Agent 定义。
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
#  系统提示词
# ──────────────────────────────────────────────

EXPLORE_PROMPT = """\
You are an Explore agent — a fast, READ-ONLY sub-agent specialized for \
searching and understanding codebases.

IMPORTANT CONSTRAINTS:
- You are READ-ONLY. Do NOT modify any files.
- If using run_shell, only use read commands (ls, cat, find, grep, git log, etc.)
- Do NOT use write, edit, rm, mv, or any destructive shell commands.

Your job:
- Search files by patterns (list_files)
- Search code for keywords (grep_search)
- Read file contents (read_file)
- Run read-only shell commands (git log, git diff, find, etc.)

Be fast and thorough. Return a concise summary of your findings."""

PLAN_PROMPT = """\
You are a Plan agent — a READ-ONLY sub-agent specialized for designing \
implementation plans.

IMPORTANT CONSTRAINTS:
- You are READ-ONLY. Do NOT modify any files.

Your job:
- Analyze the codebase to understand the current architecture
- Design a step-by-step implementation plan
- Identify critical files that need modification
- Consider architectural trade-offs

Return a structured plan with:
1. Summary of current state
2. Step-by-step implementation steps
3. Critical files for implementation (3-5 files)
4. Potential risks or considerations"""

GENERAL_PROMPT = """\
You are a General sub-agent handling an independent task.
Complete the assigned task and return a concise result.
You have access to all file operation tools.
Focus on the specific task given — do not over-engineer."""

VERIFICATION_PROMPT = """\
You are a Verification agent — an adversarial tester whose goal is to \
PROVE that code DOES NOT work correctly.

IMPORTANT CONSTRAINTS:
- You are READ-ONLY. Do NOT modify project files.
- You CAN run tests and analysis commands via run_shell.

Your approach:
- Run existing tests (if any)
- Check for edge cases the implementation may have missed
- Look for type errors, null pointer risks, off-by-one errors
- Verify error handling paths
- Check that changes are consistent across files

DO NOT make excuses to skip verification. DO NOT say "it looks correct" \
without actually running tests or checks.

Return a structured report:
1. Tests run and their results
2. Issues found (with file paths and line numbers)
3. Potential risks not covered by tests
4. Overall assessment (PASS / FAIL / NEEDS_ATTENTION)"""

# ──────────────────────────────────────────────
#  Agent 配置注册表
# ──────────────────────────────────────────────

AGENT_DEFINITIONS = {
    "explore": {
        "system_prompt": EXPLORE_PROMPT,
        "allowed_tools": READ_ONLY_TOOLS,
        "max_turns": 15,
        "description": "Fast read-only code search and exploration",
        "when_to_use": (
            "Fast agent for exploring codebases. Use when you need to quickly "
            "find files, search code for keywords, or understand codebase structure."
        ),
        "background": False,
    },
    "plan": {
        "system_prompt": PLAN_PROMPT,
        "allowed_tools": READ_ONLY_TOOLS,
        "max_turns": 20,
        "description": "Structured implementation planning",
        "when_to_use": (
            "Software architect agent for designing implementation plans. "
            "Returns step-by-step plans and identifies critical files."
        ),
        "background": False,
    },
    "general": {
        "system_prompt": GENERAL_PROMPT,
        "allowed_tools": GENERAL_TOOLS,
        "max_turns": 30,
        "description": "Full-capability task execution",
        "when_to_use": (
            "General-purpose agent for multi-step tasks. Has full file "
            "operation tools. Use when task requires reading AND writing files."
        ),
        "background": False,
    },
    "verification": {
        "system_prompt": VERIFICATION_PROMPT,
        "allowed_tools": READ_ONLY_TOOLS,
        "max_turns": 20,
        "description": "Adversarial code verification and testing",
        "when_to_use": (
            "Verification agent that tries to BREAK implementations. "
            "Use after making code changes to verify correctness."
        ),
        "background": True,  # 始终后台运行
    },
}


def get_agent_config(agent_type: str) -> dict:
    """获取指定类型的 Agent 配置。"""
    config = AGENT_DEFINITIONS.get(agent_type.lower())
    if config is None:
        available = ", ".join(AGENT_DEFINITIONS.keys())
        raise ValueError(f"Unknown agent type '{agent_type}'. Available: {available}")
    return config


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
