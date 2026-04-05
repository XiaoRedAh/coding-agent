"""
bootstrap/state.py - 集中式状态存储

所有全局配置、路径常量、API 客户端和运行时单例实例的唯一来源。
其他模块通过 `from bootstrap.state import ...` 访问共享状态，
避免 import 循环和重复定义。

运行时实例（todo, task_mgr, bg, bus, team, skills）在 main.py 初始化阶段赋值。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

# 加载 .env 环境变量
load_dotenv(override=True)

# 自定义 base_url 时移除可能冲突的 auth token
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# === 路径常量 ===
WORKDIR = Path.cwd()
PROJECT_DIR = WORKDIR / ".xiaoagent"          # 项目配置根目录
TEAM_DIR = PROJECT_DIR / "team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = PROJECT_DIR / "tasks"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = PROJECT_DIR / "transcripts"
SETTINGS_PATH = PROJECT_DIR / "settings.json"  # 权限规则等配置

# === API 客户端与模型 ===
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# === 上下文窗口与压缩阈值 ===
MODEL_CONTEXT_WINDOW = int(os.getenv("MODEL_CONTEXT_WINDOW", "200000"))
MAX_OUTPUT_TOKENS = 8000
EFFECTIVE_WINDOW = MODEL_CONTEXT_WINDOW - min(MAX_OUTPUT_TOKENS, 20000)

# 多级阈值体系（基于有效窗口的百分比）
BUDGET_THRESHOLD = 0.50       # 50% — 开始动态缩减工具结果
SNIP_THRESHOLD = 0.60         # 60% — 开始 snip 过时的工具结果
BUDGET_TIGHT_THRESHOLD = 0.70 # 70% — 更激进的预算
AUTOCOMPACT_THRESHOLD = 0.85  # 85% — 触发全量摘要压缩
WARNING_THRESHOLD = 0.82      # 82% — 显示警告

# 压缩常量
BUDGET_NORMAL = 30000         # 50-70% 时的工具结果字符预算
BUDGET_TIGHT = 15000          # >70% 时的工具结果字符预算
SNIP_KEEP_RECENT = 3          # snip 时保留最近 N 个工具结果
MICROCOMPACT_IDLE_SECONDS = 300  # 5 分钟空闲触发微压缩
MAX_AUTOCOMPACT_FAILURES = 3  # 断路器阈值

# 压缩后恢复预算
POST_COMPACT_MAX_FILES = 5
POST_COMPACT_MAX_TOKENS_PER_FILE = 5000
POST_COMPACT_SKILLS_BUDGET = 25000

# === 权限模式 ===
PERMISSION_MODE = os.getenv("PERMISSION_MODE", "default")  # default/plan/acceptEdits/bypassPermissions/dontAsk

# === 其他阈值 ===
POLL_INTERVAL = 5
IDLE_TIMEOUT = 60

# === 消息类型白名单 ===
VALID_MSG_TYPES = {
    "message", "broadcast", "shutdown_request",
    "shutdown_response", "plan_approval_response",
}

# === 运行时单例实例（在 main.py 初始化阶段赋值） ===
todo = None       # TodoManager 实例
task_mgr = None   # TaskManager 实例
bg = None         # BackgroundManager 实例
bus = None        # MessageBus 实例
team = None       # TeammateManager 实例
skills = None     # SkillLoader 实例
perm_rules = None # PermissionRules 实例
