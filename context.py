"""
context.py - 上下文构建

基于 Markdown 模板组装系统提示词，通过变量替换注入动态信息。
实现了三个关键机制：
1. CLAUDE.md 层级发现 — 从 cwd 向上遍历收集项目指令文件
2. Git 上下文采集 — 分支、最近提交、工作区状态
3. 模板变量替换 — {{placeholder}} → 实际值

对应 Claude Code 源码中的：
- constants/prompts.ts → getSystemPrompt()
- utils/claudemd.ts → CLAUDE.md 发现
- context.ts → getSystemContext() / getUserContext()
"""

import os
import subprocess
from datetime import date
from pathlib import Path

from bootstrap.state import WORKDIR
from bootstrap import state


def load_claude_md() -> str:
    """
    从当前工作目录向上遍历，收集所有 CLAUDE.md 文件内容。

    Claude Code 从 4 个位置收集（~/.claude/、项目根、.claude/、cwd + 父目录），
    我们简化为从 cwd 向上遍历直到根目录。

    Returns:
        合并后的 CLAUDE.md 内容（用分隔线连接），或空字符串
    """
    parts = []
    d = WORKDIR.resolve()
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
    return (
        "\n\n# Project Instructions (CLAUDE.md)\n"
        + "\n\n---\n\n".join(parts)
    )


def get_git_context() -> str:
    """
    采集当前 Git 仓库的上下文信息：分支、最近提交、工作区状态。

    这些信息帮助 LLM 理解项目上下文，减少不必要的 git status 工具调用。
    如果不在 Git 仓库中则静默返回空字符串。

    Returns:
        格式化的 Git 上下文字符串
    """
    try:
        opts = {"cwd": WORKDIR, "capture_output": True, "text": True, "timeout": 3}
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], **opts
        ).stdout.strip()
        log = subprocess.run(
            ["git", "log", "--oneline", "-5"], **opts
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short"], **opts
        ).stdout.strip()

        result = f"\nGit branch: {branch}"
        if log:
            result += f"\nRecent commits:\n{log}"
        if status:
            result += f"\nGit status:\n{status[:2000]}"
        return result
    except Exception:
        return ""


def build_system_prompt() -> str:
    """
    加载 system-prompt.md 模板并替换所有变量占位符。

    模板变量：
    - {{cwd}} — 工作目录
    - {{date}} — 当前日期
    - {{platform}} — 操作系统信息
    - {{shell}} — Shell 类型
    - {{git_context}} — Git 分支/提交/状态
    - {{claude_md}} — CLAUDE.md 项目指令
    - {{skills_info}} — 可用技能列表

    Returns:
        完整的系统提示词字符串
    """
    template_path = Path(__file__).parent / "system-prompt.md"
    template = template_path.read_text(encoding="utf-8")

    today = date.today().isoformat()
    platform = f"{os.name} ({os.sys.platform})"
    shell = os.environ.get("SHELL", os.environ.get("COMSPEC", "unknown"))
    git_context = get_git_context()
    claude_md = load_claude_md()
    skills_info = ""
    if state.skills and state.skills.skills:
        skills_info = f"\nAvailable skills:\n{state.skills.descriptions()}"

    return (
        template
        .replace("{{cwd}}", str(WORKDIR))
        .replace("{{date}}", today)
        .replace("{{platform}}", platform)
        .replace("{{shell}}", shell)
        .replace("{{git_context}}", git_context)
        .replace("{{claude_md}}", claude_md)
        .replace("{{skills_info}}", skills_info)
    )
