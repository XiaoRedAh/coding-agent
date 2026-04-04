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
TEAM_DIR = WORKDIR / ".team"
INBOX_DIR = TEAM_DIR / "inbox"
TASKS_DIR = WORKDIR / ".tasks"
SKILLS_DIR = WORKDIR / "skills"
TRANSCRIPT_DIR = WORKDIR / ".transcripts"

# === API 客户端与模型 ===
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))
MODEL = os.environ["MODEL_ID"]

# === 阈值与超时 ===
TOKEN_THRESHOLD = 100000
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
