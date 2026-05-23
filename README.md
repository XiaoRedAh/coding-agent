# XiaoAgent — 模块化 AI 编程助手

参考 [Claude Code](https://github.com/anthropics/claude-code) 源码架构实现的 Python AI 编程助手。集成了工具调用、上下文压缩、多 Agent 协作、权限控制、MCP 集成、Skills 系统、Memory 记忆等机制。

## 功能特性

| 模块 | 说明 |
|------|------|
| **工具系统** | 10 个内置工具：Shell、文件读写/编辑、文件列表、内容搜索、Agent 派生、Skill 加载、Todo、Task |
| **上下文压缩** | 5 级压缩管道：动态预算 → Snip 旧结果 → 空闲微压缩 → 双阶段 LLM 摘要（带断路器保护） |
| **多 Agent 协作** | 三种模式：SubAgent 同步/异步派生、Coordinator 规划-执行分离、MetaGPT-lite SOP 工作流 |
| **权限控制** | 3 层管线：deny 规则 → 危险检测（命令+路径） → 5 种模式决策 |
| **MCP 集成** | stdio JSON-RPC 协议连接外部 MCP 服务器，工具自动发现并合并到工具池 |
| **Skills 系统** | 渐进式披露：启动时只展示简介，LLM 按需加载完整技能内容，支持参数替换 |
| **Memory 记忆** | 跨会话持久化记忆，4 种类型（user/feedback/project/reference），基于 Markdown + YAML frontmatter |
| **Prompt Cache** | System Prompt 动静分离，静态区标注 `cache_control`，动态区每次替换 |
| **任务管理** | 持久化任务 CRUD（JSON 文件），支持依赖关系和认领机制 |
| **后台执行** | Shell 命令后台执行，守护线程 + 通知队列回传结果 |
| **流式输出** | LLM 逐词流式输出 + 等待动画 |

## 技术栈

- **语言**: Python 3.10+
- **LLM SDK**: Anthropic SDK（Claude 模型）、OpenAI SDK（OpenRouter / DeepSeek / Qwen 等兼容 API）
- **协议**: MCP（Model Context Protocol）stdio JSON-RPC
- **并发**: threading（后台 Shell、异步 SubAgent、心跳日志）
- **配置**: YAML（工作流定义）+ JSON（设置、任务）+ Markdown + YAML frontmatter（记忆/技能）
- **持久化**: JSON 文件 + Markdown 文件
- **测试**: pytest

---

## 项目结构

```
coding agent/
├── main.py                        # CLI 入口，初始化所有全局单例
├── query.py                       # ★ Agent Loop 核心状态机（每轮：压缩→调用LLM→处理工具→循环保护）
├── context.py                     # ★ System Prompt 构建器（动静分离 + Prompt Cache 标记）
├── system-prompt.md               # System Prompt 模板（运行时依赖，勿移动）
├── .env.example                   # 环境变量模板
├── mcp.json.example               # MCP 配置示例
├── requirements.txt               # Python 依赖
│
├── bootstrap/                     # 引导和全局状态
│   └── state.py                   # ★ 集中式状态存储：路径常量、压缩阈值、所有运行时单例
│
├── agents/                        # 多 Agent 系统
│   ├── definitions.py             # 4 种内置 Agent 类型（explore/plan/general/verification）
│   ├── subagent.py                # ★ SubAgent 执行引擎（同步+异步，超时护栏，连续错误限制）
│   ├── coordinator.py             # ★ Coordinator 协调者模式（规划-执行分离）
│   ├── task_queue.py              # 异步 Agent 任务通知队列
│   └── custom_registry.py         # 用户自定义角色注册表
│
├── services/                      # 服务层
│   ├── llm.py                     # ★ LLM 适配器（Anthropic/OpenAI 双格式，流式输出，JSON截断修复）
│   ├── compact.py                 # ★ 5 级上下文压缩管道（带断路器和 TokenTracker）
│   ├── permissions.py             # ★ 3 层权限控制管线（5 种模式 + 危险检测）
│   ├── mcp.py                     # ★ MCP 集成（stdio 连接、工具发现、JSON-RPC 通信）
│   ├── memory.py                  # ★ 跨会话记忆系统（4 种类型，Markdown 存储）
│   ├── tasks.py                   # 持久化任务管理器
│   ├── background.py              # 后台 Shell 管理器
│   ├── prompt_builder.py          # 运行时 Prompt 装配器（normal/coordinator 模式切换）
│   └── api_errors.py              # API 错误分类与重试配置
│
├── tools/                         # 工具系统
│   ├── __init__.py                # 工具注册表（get_all_definitions + get_all_handlers）
│   ├── BashTool.py                # Shell 命令执行（支持 run_in_background）
│   ├── FileReadTool.py            # 文件读取（带行号）
│   ├── FileWriteTool.py           # 文件写入（自动创建父目录）
│   ├── FileEditTool.py            # 文件精确编辑（引号容错、唯一性检查）
│   ├── ListFilesTool.py           # Glob 文件列表
│   ├── GrepSearchTool.py          # 内容搜索
│   ├── AgentTool.py               # SubAgent 统一入口（同步/异步派生）
│   ├── SkillTool.py               # 技能按需加载
│   ├── TodoTool.py                # 内存待办清单
│   └── TaskTool.py                # 持久化任务 CRUD（5 个操作）
│
├── screens/                       # 用户界面
│   └── repl.py                    # ★ REPL 交互循环（多行输入、编辑器模式、彩色输出）
│
├── skills/                        # 技能系统
│   ├── loader.py                  # 技能文件加载器（渐进式披露，参数替换）
│   └── commit/SKILL.md            # 示例技能：Git Conventional Commits
│
├── workflows/                     # MetaGPT-lite SOP 工作流引擎
│   ├── engine.py                  # ★ 工作流主循环（事件驱动角色执行）
│   ├── role_runtime.py            # 角色运行时执行器
│   ├── event_bus.py               # 发布-订阅事件总线
│   ├── prompting.py               # 角色提示词构建器
│   ├── structured_output.py       # LLM JSON 输出提取与验证
│   ├── artifact_store.py          # 产物文件存储
│   ├── gateway.py                 # 工作流快捷入口（/workflow 命令 + SOP_MODE）
│   ├── loader.py                  # 工作流配置加载器
│   └── defaults/
│       └── metagpt-lite-3role.yaml  # 默认 3 角色工作流（Analyst → Engineer → Tester）
│
├── prompts/workflow/              # 工作流角色 Prompt 模板
│   ├── analyst.md                 # 分析师：需求分析 → 设计包
│   ├── engineer.md                # 工程师：代码实现
│   └── tester.md                  # 测试员：验证 + pass/fail 判定
│
├── utils/                         # 工具函数
│   ├── path.py                    # 路径安全检查（防止目录逃逸）
│   └── truncate.py                # 结果截断（保留头尾各半）
│
├── tests/                         # 测试
│   ├── conftest.py                # 共享 fixtures（tmp_workdir 等）
│   ├── unit/                      # 单元测试（14 个文件）
│   ├── component/                 # 组件测试（Mock LLM 的 Agent Loop 端到端测试）
│   └── integration/               # 集成测试（需真实 LLM API Key）
│
├── eval/                          # 模块评估（7 个独立评估脚本，~293 用例）
│   ├── eval_permissions.py        # 权限评估（~198 用例）
│   ├── eval_tools.py              # 工具评估（~30 用例）
│   ├── eval_compact.py            # 压缩评估（~20 用例）
│   ├── eval_skills.py             # 技能评估（~15 用例）
│   ├── eval_memory.py             # 记忆评估（~12 用例）
│   ├── eval_mcp.py                # MCP 评估（~10 用例）
│   └── eval_subagent.py           # SubAgent 评估（~8 用例，需 LLM）
│
└── docs/                          # 文档（调研报告、设计文档、计划等）
```

**核心代码文件**（标 ★）是理解项目架构的推荐阅读顺序：
`bootstrap/state.py` → `main.py` → `query.py` → `context.py` → `services/llm.py` → `services/compact.py` → `services/permissions.py` → `agents/subagent.py` → `agents/coordinator.py`

---

## 环境配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，选择一种模型方案配置（详见下方模型配置章节）。

---

## 模型配置

项目通过 `LLM_PROVIDER` 环境变量切换 SDK 格式，支持多种模型方案。

### 方案 A：Claude（Anthropic 官方，效果最好）

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
MODEL_ID=claude-sonnet-4-20250514
```

### 方案 B：DeepSeek 官网（高性价比）

```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_API_KEY=sk-xxx
MODEL_ID=deepseek-chat
MODEL_CONTEXT_WINDOW=128000
```

### 方案 C：Qwen 免费模型（通过 OpenRouter，零成本入门）

```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-你的key
MODEL_ID=qwen/qwen3.6-plus:free
MODEL_CONTEXT_WINDOW=131072
```

### 方案 D：Step 3.5 Flash（免费）

```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-你的key
MODEL_ID=stepfun/step-3.5-flash:free
MODEL_CONTEXT_WINDOW=128000
```

### 关键参数说明

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `LLM_PROVIDER` | SDK 类型：`anthropic` 或 `openai` | `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥 | - |
| `OPENAI_API_KEY` | OpenAI 兼容 API 密钥 | - |
| `OPENAI_BASE_URL` | OpenAI 兼容 API 地址 | `https://api.openai.com/v1` |
| `MODEL_ID` | 模型名称 | - |
| `MODEL_CONTEXT_WINDOW` | 模型上下文窗口大小 | `200000` |
| `PERMISSION_MODE` | 权限模式（见下方说明） | `default` |
| `COORDINATOR_MODE` | Coordinator 模式开关（`1`/`true` 开启） | 关闭 |
| `SOP_MODE` | SOP 工作流模式开关（`1`/`true` 开启） | 关闭 |

> `LLM_PROVIDER=openai` 时使用 OpenAI SDK，可连接 OpenRouter / DeepSeek / Qwen 等所有 OpenAI 兼容 API。`services/llm.py` 自动处理 Anthropic 与 OpenAI 之间的 tool 格式差异。

---

## 启动教程

```bash
cd /path/to/your/project          # 先 cd 到你的目标工作目录
python /path/to/coding-agent/main.py
```

启动后输出示例：

```
[LLM] provider=anthropic, model=claude-sonnet-4-20250514
Tips: /edit for multi-line editor | /compact to compress | q to quit
coding-agent >>
```

### REPL 命令

| 命令 | 说明 |
|------|------|
| `/edit` | 打开系统编辑器（`$EDITOR` 或 nano/vi）编辑多行输入 |
| `/compact` | 手动触发上下文压缩 |
| `/tasks` | 查看所有持久化任务 |
| `q` / `exit` | 退出程序 |

### 权限模式

通过 `.env` 中的 `PERMISSION_MODE` 设置：

| 模式 | 说明 |
|------|------|
| `default` | 危险操作需用户确认（默认） |
| `acceptEdits` | 文件编辑自动放行，其余需确认 |
| `bypassPermissions` | 全部放行（deny 规则和危险检测仍生效） |
| `plan` | 只读模式，拒绝所有修改操作 |
| `dontAsk` | 需确认的操作自动拒绝（适用于 CI/CD） |

---

## MCP 接入教程

MCP（Model Context Protocol）让 Agent 连接外部服务（GitHub、数据库、文件系统等）。

### 1. 创建配置文件

在**工作目录**下创建 `.xiaoagent/mcp.json`（参考项目根目录的 `mcp.json.example`）：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"],
      "env": {}
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_xxx"
      }
    }
  }
}
```

### 2. 启动 Agent

Agent 启动时自动连接配置的 MCP 服务器，启动日志会显示连接状态：

```
[mcp:filesystem] connected, 5 tools available
[mcp:github] connected, 12 tools available
```

### 3. 工具命名规则

MCP 工具自动合并到工具池，命名格式为 `mcp__<server>__<tool>`。LLM 可直接调用，无需额外配置。

### 4. 常用 MCP Server

| Server | 安装命令 | 功能 |
|--------|----------|------|
| `@modelcontextprotocol/server-filesystem` | `npx -y @modelcontextprotocol/server-filesystem <path>` | 文件系统操作 |
| `@modelcontextprotocol/server-github` | `npx -y @modelcontextprotocol/server-github` | GitHub API |
| `@modelcontextprotocol/server-postgres` | `npx -y @modelcontextprotocol/server-postgres <connection-string>` | PostgreSQL |

### 5. 禁用服务器

在配置中添加 `"disabled": true` 可临时禁用某个服务器：

```json
{
  "mcpServers": {
    "my-server": {
      "command": "npx",
      "args": ["-y", "some-package"],
      "disabled": true
    }
  }
}
```

---

## Skills 接入教程

Skills 是可复用的任务指南，采用渐进式披露设计——启动时只展示简介，LLM 按需加载完整内容。

### 1. 创建 Skill 文件

在任意技能目录下创建 `skills/<name>/SKILL.md`：

```markdown
---
name: my-skill
description: Brief one-line description of what this skill does
---

# My Skill

## When to use
Describe when this skill should be activated.

## Steps
1. First step — do XYZ
2. Second step — do ABC

## Rules
- Rule 1
- Rule 2
- Use `$ARGUMENTS` to reference user-provided arguments
```

### 2. 技能目录优先级

| 目录 | 优先级 | 适用场景 |
|------|--------|----------|
| `{workdir}/skills/` | 高 | 项目专属技能 |
| `{workdir}/.xiaoagent/skills/` | 中 | 项目配置级技能 |
| `~/.xiaoagent/skills/` | 低 | 用户全局技能 |

同名技能以高优先级目录为准。

### 3. 工作流程

```
启动时:  扫描所有目录 → 解析 frontmatter → 注入简介到 System Prompt
运行时:  用户提问 → LLM 判断需要某技能 → 调用 load_skill("skill-name") → 获取完整内容 → 按指导执行
```

### 4. 参数替换

Skill 文件中支持以下占位符，`load_skill` 加载时自动替换：

| 占位符 | 说明 |
|--------|------|
| `$ARGUMENTS` | 用户传入的完整参数字符串 |
| `$ARG_1`, `$ARG_2`, ... | 按空格分割的第 N 个参数 |
| `${SKILL_DIR}` | SKILL.md 所在目录的绝对路径 |

### 5. 内置技能

项目内置了一个 `commit` 技能（`skills/commit/SKILL.md`），用于生成符合 Conventional Commits 规范的 Git 提交。

---

## 多 Agent 协作

项目支持三种协作模式：

### 模式 A：SubAgent（通用）

主 Agent 通过 `agent()` 工具派生工作子 Agent，无需额外配置。

- **同步**：阻塞等待，直接返回结果
- **异步**：后台线程执行，通过通知队列回传结果（`run_in_background=True`）

4 种内置 Agent 类型：

| 类型 | 说明 | 最大轮次 | 工具范围 |
|------|------|----------|----------|
| `explore` | 只读代码搜索与分析 | 15 | read_file, list_files, grep_search |
| `plan` | 结构化实现规划 | 20 | 全部（不含 agent） |
| `general` | 完整任务执行 | 30 | 全部（不含 agent） |
| `verification` | 对抗性测试验证 | 20 | 全部（始终后台运行） |

### 模式 B：Coordinator（规划-执行分离）

设置 `COORDINATOR_MODE=1` 激活。主 Agent 变为项目管理者（Orchestrator），只拥有只读调研工具 + `agent` 工具：

- **规划**：分析用户需求，拆分为独立子任务
- **并行执行**：在一次响应中派生多个 Worker 并行执行
- **合成**：收集 Worker 结果后合成为最终响应

### 模式 C：MetaGPT-lite SOP 工作流

通过 `/workflow <requirement>` 命令或 `SOP_MODE=1` 触发。严格 SOP 流程：

```
AnalystDesigner → Engineer → Tester
       ↑                         │
       └─── test.failed ─────────┘
```

- **AnalystDesigner**：需求分析 → 设计包
- **Engineer**：代码实现
- **Tester**：测试验证 → pass/fail 判定（失败则触发 Engineer 重新实现）
- 自定义工作流：在 `.xiaoagent/workflows/` 下放置自定义 YAML 配置

---

## Memory 记忆系统

跨会话持久化记忆，帮助 Agent 记住用户偏好、项目上下文和外部参考信息。

### 存储位置

记忆文件存储在 `.xiaoagent/memory/` 目录下。

### 4 种记忆类型

| 类型 | 用途 | 示例 |
|------|------|------|
| `user` | 用户的角色、偏好、知识背景 | 用户是 Python 后端开发 |
| `feedback` | 用户给出的行为指导原则 | 单元测试必须用真实数据库 |
| `project` | 项目上下文、决策、约束 | 某 PR 的动机和背景 |
| `reference` | 外部系统指针 | Grafana 面板地址、Linear 项目名 |

### 工作原理

- `MEMORY.md` 索引文件始终保持在 System Prompt 中（最多 200 行 / 25KB）
- 每个记忆记录存储为独立的 Markdown 文件（YAML frontmatter + 内容）
- Agent 使用 `read_file` / `write_file` / `edit_file` 工具直接操作记忆文件
- 记忆目录在权限系统中被列入白名单，编辑无需确认

---

## 测试教程

### 运行单元测试

```bash
cd "coding agent"
pytest tests/unit/ -v
```

### 运行组件测试

```bash
pytest tests/component/ -v
```

### 运行全部测试（单元 + 组件）

```bash
pytest tests/ -v
```

### 运行集成测试（需要 API Key）

```bash
pytest tests/integration/ -v -s
```

### 测试覆盖情况

| 测试层级 | 文件数 | 说明 |
|----------|--------|------|
| `tests/unit/` | 14 | 权限、压缩、LLM 适配、Skills、定义、任务队列、编辑工具、MCP、Memory、Coordinator、API 错误、JSON 修复、LLM 重试、SubAgent、工作流模式 |
| `tests/component/` | 1 | Mock LLM 的 Agent Loop 端到端测试：文本响应、工具调用、权限拒绝、多轮工具、通知注入、maxTurns 限制、连续错误、错误恢复 |
| `tests/integration/` | 1 | 真实 LLM 连接、Tool Calling、多轮对话测试 |

### 模块评估

7 个独立评估脚本，包含 ~293 个测试用例，大部分零成本运行：

```bash
# 无需 LLM（共 6 个，~285 用例）
python eval/eval_permissions.py    # 权限控制（~198 用例）
python eval/eval_tools.py          # 工具实现（~30 用例）
python eval/eval_compact.py        # 上下文压缩（~20 用例）
python eval/eval_skills.py         # Skills 系统（~15 用例）
python eval/eval_memory.py         # Memory 系统（~12 用例）
python eval/eval_mcp.py            # MCP 集成（~10 用例）

# 需要 LLM（~8 用例，约 $0.05）
python eval/eval_subagent.py       # SubAgent 功能验证

# 通过 pytest 运行全部评估（含阈值断言）
pytest eval/ -v
```

每个评估脚本输出 `准确率: xx/yy (zz.z%)` 并可通过 `PASS_RATE` 环境变量自定义阈值。

---

## 文档索引

`docs/` 目录包含项目调研、设计和分析文档：

- `项目详解.md` / `项目详解-v2.md` — 项目架构详细分析
- `MCP深度解读.md` — MCP 协议深入解读
- `Agent Skills深度解读.md` — Skills 系统深度分析
- `Coordinator模式详解.md` — Coordinator 模式设计文档
- `项目评估体系详解.md` — 评估体系说明
- `模型接入调研.md` — 多模型接入调研
- 更多文档见 `docs/` 目录
