"""
services/permissions.py - 权限控制与安全

实现三层权限管线：
1. 规则匹配层 — deny/allow/ask 规则（来自配置文件或会话）
2. 危险检测层 — 正则模式匹配危险命令 + 危险路径保护
3. 模式决策层 — 5 种权限模式决定最终行为

决策管线（对齐 cc 的 hasPermissionsToUseTool）：
    deny 规则 → 工具危险检测 → safety check → bypass 模式 → allow 规则 → 默认 ask

核心原则：
- deny > ask > allow（行为优先级铁律）
- bypass 模式跳过通用 ask，但不跳过 deny/safety check（bypass-immune）
- 错误作为工具结果返回给 LLM（不中断循环），LLM 自行调整策略

对应 Claude Code 的 permissions.ts（52KB）的大幅简化版。
"""

import json
import os
import re
from pathlib import Path
from typing import Literal

from runtime import state

# ──────────────────────────────────────────────
#  权限模式
# ──────────────────────────────────────────────

PermissionMode = Literal["default", "plan", "acceptEdits", "bypassPermissions", "dontAsk"]

# 只读工具——所有模式下都直接放行
READ_TOOLS = frozenset({"read_file", "list_files", "grep_search", "load_skill"})

# 编辑工具——受模式控制
EDIT_TOOLS = frozenset({"write_file", "edit_file"})

# ──────────────────────────────────────────────
#  危险命令模式（正则检测）
# ──────────────────────────────────────────────

DANGEROUS_PATTERNS = [
    # Unix 通用
    re.compile(r"\brm\s+.*-[rR]", re.IGNORECASE),       # rm -r / rm -rf
    re.compile(r"\bgit\s+(push\s+.*(-f|--force)|reset\s+--hard|clean\s+-[fdx])"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bkill(all)?\s"),
    re.compile(r"\bpkill\s"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\bchmod\s+777\b"),
    re.compile(r"\b(curl|wget)\b.*\|\s*(ba)?sh"),          # curl/wget | sh 管道注入
    # Windows
    re.compile(r"\bdel\s", re.IGNORECASE),
    re.compile(r"\brmdir\s", re.IGNORECASE),
    re.compile(r"\bformat\s", re.IGNORECASE),
    re.compile(r"\btaskkill\s", re.IGNORECASE),
]

# 危险路径——bypass 模式下也需确认（bypass-immune）
DANGEROUS_PATHS = {
    ".git", ".gitconfig", ".gitmodules",
    ".bashrc", ".zshrc", ".profile", ".bash_profile",
    ".ssh", ".env", ".xiaoagent",
}


def is_dangerous_command(command: str) -> bool:
    """检测命令是否匹配危险模式"""
    return any(p.search(command) for p in DANGEROUS_PATTERNS)


def is_dangerous_path(file_path: str) -> bool:
    """检测文件路径是否在危险路径列表中（含前缀匹配如 .env.production）"""
    path = Path(file_path)
    parts = path.parts
    for part in parts:
        if part in DANGEROUS_PATHS:
            return True
        # 前缀匹配：.env.production, .env.local 等变体
        for dp in DANGEROUS_PATHS:
            if part.startswith(dp + ".") or part.startswith(dp + "/"):
                return True
    name = path.name
    if name in DANGEROUS_PATHS:
        return True
    for dp in DANGEROUS_PATHS:
        if name.startswith(dp + "."):
            return True
    return False


def is_outside_workdir(file_path: str) -> bool:
    """检测文件路径是否在工作目录之外"""
    workdir = state.WORKDIR
    try:
        resolved = (workdir / file_path).resolve()
        return not resolved.is_relative_to(workdir.resolve())
    except (ValueError, OSError):
        return True


# ──────────────────────────────────────────────
#  权限规则系统
# ──────────────────────────────────────────────

class PermissionRules:
    """
    权限规则管理器。

    支持从配置文件加载 allow/deny 规则，以及会话级动态规则。
    规则格式：工具名(内容模式)，如 "run_shell(npm test*)", "edit_file"

    对应 cc 的多源规则系统（简化为项目级 + 会话级两层）。
    """

    def __init__(self):
        self.deny_rules: list[str] = []      # deny 规则列表
        self.allow_rules: list[str] = []     # allow 规则列表
        self.session_allows: set[str] = set() # 会话级白名单（用户确认后记住）

    def load_from_settings(self):
        """从 .xiaoagent/settings.json 加载规则"""
        from runtime.state import SETTINGS_PATH
        settings_path = SETTINGS_PATH
        if not settings_path.exists():
            return
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            perms = data.get("permissions", {})
            self.deny_rules = perms.get("deny", [])
            self.allow_rules = perms.get("allow", [])
        except Exception:
            pass

    def match_rule(self, rules: list[str], tool_name: str, content: str = "") -> str | None:
        """
        在规则列表中匹配工具名和内容。

        规则格式：
        - "tool_name"           — 整工具级匹配
        - "tool_name(exact)"    — 精确匹配
        - "tool_name(prefix*)"  — 前缀匹配

        Returns:
            匹配到的规则字符串，或 None
        """
        for rule in rules:
            if "(" in rule and rule.endswith(")"):
                rule_tool = rule[:rule.index("(")]
                rule_content = rule[rule.index("(") + 1:-1]
            else:
                rule_tool = rule
                rule_content = None

            if rule_tool != tool_name:
                continue

            if rule_content is None:
                return rule  # 整工具级匹配

            if rule_content.endswith("*"):
                prefix = rule_content[:-1]
                if content.startswith(prefix):
                    return rule  # 前缀匹配
            else:
                if content == rule_content:
                    return rule  # 精确匹配

        return None

    def is_session_allowed(self, key: str) -> bool:
        """检查是否在会话白名单中"""
        return key in self.session_allows

    def add_session_allow(self, key: str):
        """添加到会话白名单"""
        self.session_allows.add(key)


# ──────────────────────────────────────────────
#  权限检查管线
# ──────────────────────────────────────────────

# 检查结果类型
CheckResult = dict  # {"action": "allow"|"deny"|"confirm", "reason": str}


def check_permission(
    tool_name: str,
    tool_input: dict,
    mode: PermissionMode,
    rules: PermissionRules,
) -> CheckResult:
    """
    三层权限检查管线。

    管线顺序（对齐 cc 的 hasPermissionsToUseTool）：
    1. deny 规则 → 直接拒绝（不可覆盖）
    2. 工具特定的危险检测 + safety check → bypass-immune
    3. 模式决策 → bypass 放行 / allow 规则放行 / 默认 ask

    Args:
        tool_name: 工具名称
        tool_input: 工具输入参数
        mode: 当前权限模式
        rules: 权限规则管理器
    Returns:
        {"action": "allow"|"deny"|"confirm", "reason": str}
    """
    # 提取内容键（用于规则匹配）
    content = _get_content_key(tool_name, tool_input)

    # ═══ Layer 1: deny 规则（最高优先级，不可覆盖） ═══
    deny_match = rules.match_rule(rules.deny_rules, tool_name, content)
    if deny_match:
        return {"action": "deny", "reason": f"Blocked by deny rule: {deny_match}"}

    # ═══ Layer 2: 模式级硬性拒绝（优先于危险检测） ═══
    # plan 和 dontAsk 模式的拒绝比 "confirm" 更严格——如果模式直接拒绝该工具类型，
    # 就不需要走到 confirm 环节（confirm 意味着"可以问用户"，但 plan/dontAsk 不允许问）

    if tool_name in READ_TOOLS:
        return {"action": "allow", "reason": "Read-only tool"}

    if mode == "plan":
        if tool_name in EDIT_TOOLS:
            return {"action": "deny", "reason": "Edit blocked in plan mode"}
        if tool_name == "run_shell":
            return {"action": "deny", "reason": "Shell blocked in plan mode"}

    # ═══ Layer 3: 危险检测 + safety check（bypass-immune） ═══

    # 3a. Shell 命令危险检测
    if tool_name == "run_shell" and is_dangerous_command(tool_input.get("command", "")):
        if rules.is_session_allowed(f"run_shell:{content}"):
            return {"action": "allow", "reason": "Session whitelist"}
        # dontAsk 模式：需确认的直接拒绝（不弹对话框）
        if mode == "dontAsk":
            return {"action": "deny", "reason": f"Dangerous command auto-denied (dontAsk): {content}"}
        return {"action": "confirm", "reason": f"Dangerous command: {content}"}

    # 3b. Memory 目录白名单
    file_path = tool_input.get("file_path", "")
    if file_path and tool_name in EDIT_TOOLS:
        from runtime import state as _state
        if _state.memory and _state.memory.is_memory_path(file_path):
            return {"action": "allow", "reason": "Memory directory (whitelisted)"}

    # 3c. 危险路径保护（bypass-immune）
    if file_path and tool_name in EDIT_TOOLS and is_dangerous_path(file_path):
        if mode == "dontAsk":
            return {"action": "deny", "reason": f"Dangerous path auto-denied (dontAsk): {file_path}"}
        return {"action": "confirm", "reason": f"Dangerous path: {file_path}"}

    # 3d. 工作目录外路径保护
    if file_path and tool_name in EDIT_TOOLS and is_outside_workdir(file_path):
        if mode == "dontAsk":
            return {"action": "deny", "reason": f"Outside workdir auto-denied (dontAsk): {file_path}"}
        return {"action": "confirm", "reason": f"Outside working directory: {file_path}"}

    # ═══ Layer 4: 模式决策 ═══

    # 4a. bypassPermissions 模式
    if mode == "bypassPermissions":
        return {"action": "allow", "reason": "Bypass mode"}

    # 4b. acceptEdits 模式：编辑工具自动放行
    if mode == "acceptEdits" and tool_name in EDIT_TOOLS:
        return {"action": "allow", "reason": "acceptEdits mode"}

    # 4c. allow 规则
    allow_match = rules.match_rule(rules.allow_rules, tool_name, content)
    if allow_match:
        return {"action": "allow", "reason": f"Allow rule: {allow_match}"}

    # 4d. 会话白名单
    session_key = f"{tool_name}:{content}" if content else tool_name
    if rules.is_session_allowed(session_key):
        return {"action": "allow", "reason": "Session whitelist"}

    # 4e. 安全工具直接放行
    if tool_name in {"agent", "TodoWrite", "task_create", "task_get",
                      "task_update", "task_list"}:
        return {"action": "allow", "reason": "Safe tool"}

    # 4f. dontAsk 模式：需确认的直接拒绝
    if mode == "dontAsk":
        return {"action": "deny", "reason": f"Auto-denied in dontAsk mode: {tool_name}"}

    # 3i. default 模式：默认 confirm
    return {"action": "confirm", "reason": f"Requires confirmation: {tool_name}"}


def _get_content_key(tool_name: str, tool_input: dict) -> str:
    """提取工具的内容键，用于规则匹配和白名单"""
    if tool_name == "run_shell":
        return tool_input.get("command", "")
    if tool_name in ("write_file", "edit_file", "read_file"):
        return tool_input.get("file_path", "")
    return ""
