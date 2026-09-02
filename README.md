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

按领域分层组织，依赖方向自上而下（上层可依赖下层，反之禁止）：

```
coding agent/
├── main.py                        # CLI 入口：装配全局单例 → 启动 REPL
├── system-prompt.md               # System Prompt 模板（运行时依赖，勿移动）
├── .env.example / mcp.json.example / requirements.txt
│
├── config/                        # 【配置层】
│   ├── defaults.yaml              # 全量默认配置（约 40 项参数，带注释，改配置不改代码）
│   └── loader.py                  # 四层合并（内置<用户级<项目级<环境变量）+ 校验 + 冻结 Settings
│
├── runtime/                       # 【运行时状态】
│   └── state.py                   # ★ 集中式状态存储：路径常量、所有运行时单例
│
├── engine/                        # 【核心引擎】与具体功能无关的循环骨架
│   ├── loop.py                    # ★ 统一 Agent Loop（主/子 agent 共用，差异以 LoopSpec+Hooks 表达）
│   ├── results.py                 # ToolResult 结构化工具结果（str 子类，ok/error 元数据）
│   ├── notifications.py           # 后台/Agent 通知收集（含 Coordinator 阻塞等待）
│   └── errors.py                  # API 错误分类、重试与循环保护配置
│
├── llm/                           # 【模型接入层】
│   └── adapter.py                 # ★ LLM 适配器（Anthropic/OpenAI 双格式，流式，JSON 截断修复）
│
├── context/                       # 【上下文管理】
│   ├── prompt.py                  # ★ System Prompt 构建（动静分离 + Prompt Cache 标记）
│   ├── builder.py                 # 运行时 Prompt 装配器（normal/coordinator 模式切换）
│   └── compact.py                 # ★ 5 级上下文压缩管道（断路器 + TokenTracker）
│
├── agents/                        # 【多 Agent 系统】
│   ├── session.py                 # ★ 主 Agent 会话循环（统一循环的薄组装：权限/压缩/通知/UI 钩子）
│   ├── registry.py                # ★ Agent 类型注册表（内置 + 用户自定义，统一 YAML 定义）
│   ├── builtins/                  # 内置 Agent 定义（explore/plan/general/verification.yaml）
│   ├── subagent.py                # ★ SubAgent 派生执行（统一循环薄封装：同步 + 异步）
│   ├── coordinator.py             # ★ Coordinator 协调者模式（规划-执行分离）
│   ├── task_queue.py              # 异步 Agent 任务通知队列
│   ├── custom_registry.py         # 工作流自定义角色加载
│   └── definitions.py             # 兼容层（旧导出转发到 registry）
│
├── tools/                         # 【工具层】
│   ├── __init__.py                # 工具注册表（get_all_definitions + get_all_handlers）
│   ├── BashTool.py                # Shell 命令执行（支持 run_in_background）
│   ├── FileReadTool.py            # 文件读取（带行号）
│   ├── FileWriteTool.py           # 文件写入（自动创建父目录）
│   ├── FileEditTool.py            # 文件精确编辑（引号容错、唯一性检查）
│   ├── ListFilesTool.py           # Glob 文件列表（mtime 排序）
│   ├── GrepSearchTool.py          # 内容搜索（纯 Python，跨平台）
│   ├── AgentTool.py               # SubAgent 统一入口（type enum 动态反映注册表）
│   ├── SkillTool.py               # 技能按需加载
│   ├── TodoTool.py                # 内存待办清单
│   └── TaskTool.py                # 持久化任务 CRUD（5 个操作）
│
├── services/                      # 【外围服务】agent 依赖的功能子系统
│   ├── permissions.py             # ★ 3 层权限控制管线（5 种模式 + 危险检测）
│   ├── mcp.py                     # ★ MCP 集成（stdio 连接、工具发现、JSON-RPC 通信）
│   ├── memory.py                  # ★ 跨会话记忆系统（4 种类型，Markdown 存储）
│   ├── tasks.py                   # 持久化任务管理器
│   └── background.py              # 后台 Shell 管理器
│
├── skills/                        # 【技能系统】
│   ├── loader.py                  # 技能文件加载器（渐进式披露，参数替换）
│   └── commit/SKILL.md            # 示例技能：Git Conventional Commits
│
├── workflows/                     # 【SOP 工作流】MetaGPT-lite 事件驱动引擎
│   ├── engine.py                  # ★ 工作流主循环
│   ├── role_runtime.py / event_bus.py / prompting.py / structured_output.py
│   ├── artifact_store.py / gateway.py / loader.py / schemas.py
│   └── defaults/metagpt-lite-3role.yaml  # 默认 3 角色工作流
│
├── prompts/workflow/              # 工作流角色 Prompt 模板（analyst/engineer/tester.md）
│
├── ui/                            # 【界面层】终端交互
│   ├── repl.py                    # ★ REPL 交互循环（多行输入、编辑器模式、命令分发）
│   └── render.py                  # spinner（含等待秒数）/ 权限确认交互 / 工具结果打印
│
├── utils/                         # 【通用工具】
│   ├── path.py                    # 路径安全检查（防止目录逃逸）
│   └── truncate.py                # 结果截断（保留头尾各半）
│
├── tests/                         # 测试（unit / component / integration 三层）
├── eval/                          # 模块评估（7 个独立评估脚本）
└── docs/                          # 文档（五分类：调研/计划/复盘/详解/归档）
```

**核心代码文件**（标 ★）是理解项目架构的推荐阅读顺序：
`runtime/state.py` → `main.py` → `engine/loop.py` → `agents/session.py` → `context/prompt.py` → `llm/adapter.py` → `context/compact.py` → `services/permissions.py` → `agents/subagent.py` → `agents/coordinator.py`

---

## 环境配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

**注意：需要 Python 3.10+。**

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，选择一种模型方案配置（详见下方模型配置章节）。`.env` 只放机密（API Key）和模型选择。

### 3. 行为配置（可选）

所有运行参数（超时、压缩阈值、循环保护、各工具上限、目录名等约 40 项）集中在 `config/defaults.yaml`，**改配置无需改代码**。覆盖方式（优先级从低到高）：

| 层级 | 位置 | 用途 |
|------|------|------|
| 内置默认 | `config/defaults.yaml` | 全量参数 + 注释 |
| 用户全局 | `~/.xiaoagent/config.yaml` | 个人偏好 |
| 项目级 | `{工作目录}/.xiaoagent/config.yaml` | 项目定制 |
| 环境变量 | `XIAOAGENT__节__键`（如 `XIAOAGENT__LOOP__DEFAULT_MAX_TURNS=10`） | 临时覆盖 |

配置文件只需写要覆盖的键（YAML 节结构与 defaults.yaml 一致），写错节名/键名/类型会在启动时得到明确的报错。

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

4 种内置 Agent 类型（定义在 `agents/builtins/*.yaml`）：

| 类型 | 说明 | 最大轮次 | 工具范围 |
|------|------|----------|----------|
| `explore` | 只读代码搜索与分析 | 15 | read_file, list_files, grep_search |
| `plan` | 结构化实现规划 | 20 | 全部（不含 agent） |
| `general` | 完整任务执行 | 30 | 全部（不含 agent） |
| `verification` | 对抗性测试验证 | 20 | 全部（始终后台运行） |

#### 自定义子 Agent

无需改代码——在以下任一目录放置 YAML 定义文件即可注册新的子 Agent 类型
（`agent` 工具的 type 参数会自动包含它，LLM 可直接选用）：

| 目录 | 优先级 | 适用场景 |
|------|--------|---------|
| `agents/builtins/` | 低（内置） | 项目内置类型 |
| `~/.xiaoagent/agents/` | 中 | 用户全局 |
| `{工作目录}/.xiaoagent/agents/` | 高 | 项目专属（可覆盖内置） |

YAML 格式（与内置定义完全一致）：

```yaml
name: doc-writer            # 可省略，默认取文件名
description: 一句话用途描述
when_to_use: 何时应选用此类型
system_prompt: |
  You are a documentation writer. ...
allowed_tools:               # 该类型可用的工具白名单
  - read_file
  - write_file
  - grep_search
max_turns: 15                # 最大循环轮次
background: false            # true 则始终后台运行
```

定义文件支持 `.yaml` / `.yml` / `.json`；缺失必填字段、未知字段、类型错误
会在启动时得到带文件定位的明确报错。

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

`docs/` 目录按性质分类存放项目文档，索引见 [`docs/README.md`](docs/README.md)：

| 目录 | 内容 | 数量 |
|------|------|------|
| `docs/01-research/` | 外部技术/产品调研（MCP、Skills、LLM、竞品等） | 8 |
| `docs/02-plans/` | 历史设计方案与实施计划 | 6 |
| `docs/03-retrospectives/` | 开发过程复盘与时点记录 | 7 |
| `docs/04-architecture/` | 项目架构详解（与代码对照阅读） | 5 |
| `docs/archive/` | 已被新版本取代的过时文档 | 1 |

另有 `cc源码调研/`（Claude Code 源码调研）与 `最小化对齐/`（模块对齐笔记）两个调研目录保留在项目根目录。
