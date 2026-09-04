"""
context.py - 上下文构建（含 Prompt Cache 支持）

基于 Markdown 模板组装系统提示词，拆分为静态/动态两块以支持 Prompt Cache。

Prompt Cache 机制：
- 静态区（身份/规则/工具指引/风格）→ 跨请求不变 → 标记 cache_control
- 动态区（环境信息/Git/CLAUDE.md/Skills/MCP/Memory）→ 每次可能不同 → 不缓存

对应 Claude Code 的：
- constants/prompts.ts → getSystemPrompt() + SYSTEM_PROMPT_DYNAMIC_BOUNDARY
- utils/api.ts → splitSysPromptPrefix() + buildSystemPromptBlocks()
"""

import os
import subprocess
from datetime import date

from prompts.loader import default_loader as _default_prompt_loader
from runtime import state
from runtime.state import settings

# 静态/动态分界标记（模板中 "# Environment" 之前是静态区）
_DYNAMIC_MARKER = "# Environment"


def load_claude_md() -> str:
    """从 cwd 向上遍历收集所有 CLAUDE.md 文件内容。"""
    parts = []
    d = state.WORKDIR.resolve()
    while True:
        candidate = d / "CLAUDE.md"
        if candidate.exists():
            try:
                parts.insert(0, candidate.read_text(encoding="utf-8"))
            except Exception:
                pass
        parent = d.parent
        if parent == d:
            break
        d = parent
    if not parts:
        return ""
    return "\n\n# Project Instructions (CLAUDE.md)\n" + "\n\n---\n\n".join(parts)


def get_git_context() -> str:
    """采集 Git 上下文信息。"""
    try:
        opts = {
            "cwd": state.WORKDIR, "capture_output": True, "text": True,
            "timeout": settings.context.git_timeout,
            "encoding": "utf-8", "errors": "replace",  # S5: 显式 UTF-8
        }
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], **opts).stdout.strip()
        log = subprocess.run(["git", "log", "--oneline", "-5"], **opts).stdout.strip()
        status = subprocess.run(["git", "status", "--short"], **opts).stdout.strip()
        result = f"\nGit branch: {branch}"
        if log:
            result += f"\nRecent commits:\n{log}"
        if status:
            result += f"\nGit status:\n{status[:2000]}"
        return result
    except Exception:
        return ""


def build_system_prompt() -> list[dict]:
    """
    构建分块的系统提示词（支持 Prompt Cache）。

    返回 list[dict] 格式（Anthropic SDK 支持）：
    - Block 1: 静态内容 + cache_control（跨请求缓存）
    - Block 2: 动态内容（每次可能不同，不缓存）

    对应 CC 的 splitSysPromptPrefix() + SYSTEM_PROMPT_DYNAMIC_BOUNDARY。

    Returns:
        [{"type": "text", "text": ..., "cache_control": ...}, {"type": "text", "text": ...}]
    """
    # P1: 主模板经三级覆盖加载（内置 < ~/.xiaoagent/prompts < .xiaoagent/prompts）
    template = _default_prompt_loader().load("base.md")

    # === 拆分静态/动态区 ===
    if _DYNAMIC_MARKER in template:
        idx = template.index(_DYNAMIC_MARKER)
        static_template = template[:idx].rstrip()
        dynamic_template = template[idx:]
    else:
        static_template = template
        dynamic_template = ""

    # === 构建动态部分 ===
    today = date.today().isoformat()
    platform_str = f"{os.name} ({os.sys.platform})"
    shell = os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown"))
    git_context = get_git_context()
    claude_md = load_claude_md()
    skills_info = ""
    if state.skills and state.skills.skills:
        skills_info = f"\nAvailable skills:\n{state.skills.descriptions()}"

    dynamic_text = (
        dynamic_template
        .replace("{{cwd}}", str(state.WORKDIR))
        .replace("{{date}}", today)
        .replace("{{platform}}", platform_str)
        .replace("{{shell}}", shell)
        .replace("{{git_context}}", git_context)
        .replace("{{claude_md}}", claude_md)
        .replace("{{skills_info}}", skills_info)
    )

    # MCP Instructions
    if state.mcp and state.mcp.server_count > 0:
        dynamic_text += "\n" + state.mcp.get_instructions()

    # Skills 使用说明（安装约定 + 触发方式；技能列表已在 {{skills_info}} 注入）
    if state.skills and state.skills.skills:
        dynamic_text += "\n" + _default_prompt_loader().load("fragments/skills.md")

    # Memory
    if state.memory:
        dynamic_text += "\n" + state.memory.get_prompt_section()

    # === 返回分块数组 ===
    blocks = [
        {
            "type": "text",
            "text": static_template,
            "cache_control": {"type": "ephemeral"},  # ← Prompt Cache 标记
        },
    ]
    if dynamic_text.strip():
        blocks.append({
            "type": "text",
            "text": dynamic_text,
        })
    return blocks


def build_system_prompt_str() -> str:
    """
    构建纯字符串版本的系统提示词（子 Agent 等不需要分块缓存的场景）。
    """
    blocks = build_system_prompt()
    return "\n\n".join(b["text"] for b in blocks)
