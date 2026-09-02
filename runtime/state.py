"""
bootstrap/state.py - 集中式状态存储

所有全局配置、路径常量、API 客户端和运行时单例实例的唯一来源。
其他模块通过 `from bootstrap.state import ...` 访问共享状态，
避免 import 循环和重复定义。

配置来源（S1 重构后）：
- 数值参数全部来自 config/ 分层配置（defaults.yaml + 用户/项目覆盖 + 环境变量）
- 本模块保持原有的模块级常量名，作为下游代码的兼容层
- 机密（API key）仍由 .env 提供

运行时实例（todo, task_mgr, bg, skills）在 main.py 初始化阶段赋值。

注意：本模块存在 import 副作用（加载 .env、绑定 cwd），
这是 S2（Runtime 容器）要消除的历史问题。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 环境变量（优先 .env，fallback 到 .env.example）
from pathlib import Path as _P
_root = _P(__file__).parent.parent
if not load_dotenv(_root / ".env", override=True):
    load_dotenv(_root / ".env.example", override=True)

# 自定义 base_url 时移除可能冲突的 auth token
if os.getenv("ANTHROPIC_BASE_URL"):
    os.environ.pop("ANTHROPIC_AUTH_TOKEN", None)

# === 分层配置（defaults.yaml < 用户级 < 项目级 < 环境变量）===
from config.loader import load_settings

settings = load_settings()

# === 路径常量（目录名来自 settings.paths，可配置）===
WORKDIR = Path.cwd()
PROJECT_DIR = WORKDIR / settings.paths.project_dir_name
TASKS_DIR = PROJECT_DIR / settings.paths.tasks_dir_name
SKILLS_DIR = WORKDIR / settings.paths.skills_dir_name
TRANSCRIPT_DIR = PROJECT_DIR / settings.paths.transcripts_dir_name
SETTINGS_PATH = PROJECT_DIR / settings.paths.settings_file_name
MEMORY_DIR = PROJECT_DIR / settings.paths.memory_dir_name

# === LLM 客户端（延迟初始化，在 main.py 中赋值） ===
LLM_PROVIDER = settings.llm.provider
MODEL = settings.llm.model_id
llm = None  # LLMAdapter 实例，在 main.py 初始化

# === 上下文窗口与压缩阈值（来自 settings.llm / settings.compact）===
MODEL_CONTEXT_WINDOW = settings.llm.context_window
MAX_OUTPUT_TOKENS = settings.llm.max_output_tokens
EFFECTIVE_WINDOW = MODEL_CONTEXT_WINDOW - min(MAX_OUTPUT_TOKENS, 20000)

# 多级阈值体系（基于有效窗口的百分比）
BUDGET_THRESHOLD = settings.compact.budget_threshold        # 50% — 开始动态缩减工具结果
SNIP_THRESHOLD = settings.compact.snip_threshold            # 60% — 开始 snip 过时的工具结果
BUDGET_TIGHT_THRESHOLD = settings.compact.budget_tight_threshold  # 70% — 更激进的预算
AUTOCOMPACT_THRESHOLD = settings.compact.autocompact_threshold    # 85% — 触发全量摘要压缩
WARNING_THRESHOLD = settings.compact.warning_threshold      # 82% — 显示警告

# 压缩常量
BUDGET_NORMAL = settings.compact.budget_normal_chars        # 50-70% 时的工具结果字符预算
BUDGET_TIGHT = settings.compact.budget_tight_chars          # >70% 时的工具结果字符预算
SNIP_KEEP_RECENT = settings.compact.snip_keep_recent        # snip 时保留最近 N 个工具结果
MICROCOMPACT_IDLE_SECONDS = settings.compact.microcompact_idle_seconds  # 空闲触发微压缩
MAX_AUTOCOMPACT_FAILURES = settings.compact.max_autocompact_failures    # 断路器阈值

# 压缩后恢复预算
POST_COMPACT_MAX_FILES = settings.compact.post_compact_max_files
POST_COMPACT_MAX_TOKENS_PER_FILE = settings.compact.post_compact_max_tokens_per_file
POST_COMPACT_SKILLS_BUDGET = settings.compact.post_compact_skills_budget

# === 权限模式 ===
PERMISSION_MODE = os.getenv("PERMISSION_MODE", "default")  # default/plan/acceptEdits/bypassPermissions/dontAsk

# === 运行时单例实例（在 main.py 初始化阶段赋值） ===
todo = None       # TodoManager 实例
task_mgr = None   # TaskManager 实例
bg = None         # BackgroundManager 实例
skills = None     # SkillLoader 实例
perm_rules = None # PermissionRules 实例
mcp = None        # McpManager 实例
memory = None     # MemoryManager 实例
agent_tasks = None # AgentTaskQueue 实例（异步 SubAgent 结果通知）
