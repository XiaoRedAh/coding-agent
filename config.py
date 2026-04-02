"""
config.py - 全局配置模块

集中管理所有全局配置、路径常量和单例客户端实例。
所有其他模块都从此处导入配置，避免重复定义。
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from anthropic import Anthropic

# 加载 .env 环境变量（override=True 确保 .env 优先级最高）
load_dotenv(override=True)

# 如果设置了自定义 base_url，移除可能冲突的 auth token
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# === 路径常量 ===
WORKDIR = Path.cwd()                        # 工作目录（运行 main.py 时的当前目录）
TEAM_DIR = WORKDIR / ".team"                # 团队配置与消息目录
INBOX_DIR = TEAM_DIR / "inbox"              # 队友消息收件箱目录
TASKS_DIR = WORKDIR / ".tasks"              # 持久化任务文件目录
SKILLS_DIR = WORKDIR / "skills"             # 技能文件目录
TRANSCRIPT_DIR = WORKDIR / ".transcripts"   # 压缩转录文件目录

# === 模型与客户端 ===
client = Anthropic(base_url=os.getenv("ANTHROPIC_BASE_URL"))  # Anthropic API 客户端单例
MODEL = os.environ["MODEL_ID"]                                  # 使用的模型 ID

# === 阈值与超时 ===
TOKEN_THRESHOLD = 100000   # 自动压缩触发的 token 阈值
POLL_INTERVAL = 5          # 队友空闲阶段轮询间隔（秒）
IDLE_TIMEOUT = 60          # 队友空闲超时时间（秒）

# === 消息类型白名单 ===
VALID_MSG_TYPES = {
    "message", "broadcast", "shutdown_request",
    "shutdown_response", "plan_approval_response"
}
