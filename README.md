# XiaoAgent - 模块化 AI 编程代理

一个功能完整的 AI 编程代理，参考 [Claude Code](https://github.com/anthropics/claude-code) 源码架构实现。集成了工具调用、上下文压缩、多 Agent 协作、权限控制、MCP 集成、Skills 系统、Memory 记忆等完整机制。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件（三种方案选一）：

**方案 A: Claude（Anthropic 官方，效果最好）**
```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-xxx
MODEL_ID=claude-sonnet-4-20250514
```

**方案 B: Qwen 免费模型（通过 OpenRouter，零成本入门）** ⭐ 推荐新手
```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-你的openrouter-key
MODEL_ID=qwen/qwen3.6-plus:free
MODEL_CONTEXT_WINDOW=131072
```

**方案 C: DeepSeek（通过 OpenRouter，高性价比）**
```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-你的openrouter-key
MODEL_ID=deepseek/deepseek-chat
MODEL_CONTEXT_WINDOW=128000
```

> **注意**：`LLM_PROVIDER=openai` 时使用 OpenAI SDK 格式，可连接 OpenRouter/DeepSeek/Qwen 等所有 OpenAI 兼容 API。`LLM_PROVIDER=anthropic`（默认）使用 Anthropic SDK 格式。

### 3. 运行

```bash
cd /path/to/your/project    # 先 cd 到你的工作目录
python /path/to/coding-agent/main.py   # 再运行 agent
```

> **重要**：Agent 在 `当前工作目录` 下创建 `.xiaoagent/` 配置目录，请确保 cd 到正确的项目目录。

### REPL 命令

| 命令 | 说明 |
|------|------|
| `/compact` | 手动压缩对话上下文 |
| `/tasks` | 查看持久化任务 |
| `/team` | 查看队友状态 |
| `/inbox` | 读取收件箱 |
| `q` / `exit` | 退出 |

### 权限模式

通过环境变量 `PERMISSION_MODE` 设置：

| 模式 | 说明 | 环境变量 |
|------|------|---------|
| `default` | 危险操作需确认（默认） | `PERMISSION_MODE=default` |
| `acceptEdits` | 文件编辑自动放行 | `PERMISSION_MODE=acceptEdits` |
| `bypassPermissions` | 全部放行（除安全检查） | `PERMISSION_MODE=bypassPermissions` |
| `plan` | 只读模式 | `PERMISSION_MODE=plan` |
| `dontAsk` | 需确认的自动拒绝（CI 用） | `PERMISSION_MODE=dontAsk` |

---

## MCP 接入教程

MCP（Model Context Protocol）让 Agent 连接外部服务（GitHub、数据库等）。

### 1. 创建配置文件

在**工作目录**下创建 `.xiaoagent/mcp.json`：

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
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

### 2. 运行

启动 Agent 时自动连接配置的 MCP 服务器：

```
[mcp:filesystem] connected, 5 tools available
[mcp:github] connected, 12 tools available
coding-agent >>
```

MCP 工具自动加入工具池，LLM 可直接调用。

### 3. 常用 MCP Server

| Server | 安装 | 功能 |
|--------|------|------|
| `@modelcontextprotocol/server-filesystem` | `npx -y ...` | 文件系统操作 |
| `@modelcontextprotocol/server-github` | `npx -y ...` | GitHub API |
| `@modelcontextprotocol/server-postgres` | `npx -y ...` | PostgreSQL 查询 |

---

## Skills 接入教程

Skills 是可复用的任务指南（Markdown 文件）。

### 1. 创建 Skill 文件

在工作目录下创建 `skills/<name>/SKILL.md`：

```markdown
---
name: commit
description: Create a well-formatted git commit following conventional commits
---

# Git Commit Skill

## Steps
1. Run `git status` to see what changed
2. Analyze changes, determine type (feat/fix/refactor/docs)
3. Write commit message: `type(scope): description`
4. Run `git commit -m "..."`

## Rules
- Keep first line under 72 characters
- If $ARGUMENTS provided, use as commit message hint
```

### 2. 使用

启动后 LLM 自动看到技能列表（渐进式披露）：

```
System Prompt 中:
  Available skills:
    - commit: Create a well-formatted git commit...

用户: "帮我提交代码"
LLM: load_skill(name="commit")  ← 自动加载
LLM: run_shell(command="git status")  ← 按 Skill 指导执行
```

### 3. 多层来源

| 目录 | 优先级 | 说明 |
|------|--------|------|
| `{workdir}/skills/` | 高 | 项目级 |
| `{workdir}/.xiaoagent/skills/` | 中 | 配置级 |
| `~/.xiaoagent/skills/` | 低 | 用户级 |

---

---

## LLM 适配（多模型切换）

项目支持 **Anthropic SDK** 和 **OpenAI SDK** 两种格式，通过 `LLM_PROVIDER` 环境变量切换。

### 使用 Qwen 免费模型（通过 OpenRouter）

```bash
# 1. 注册 https://openrouter.ai 获取 API Key
# 2. 安装 openai 包: pip install openai
# 3. .env 配置:
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_API_KEY=sk-or-v1-你的key
MODEL_ID=qwen/qwen3.6-plus:free
MODEL_CONTEXT_WINDOW=131072
# 4. python main.py → 输出 [LLM] provider=openai, model=qwen/qwen3.6-plus:free
```

### 适配原理

`services/llm.py` 的 `LLMAdapter` 自动转换格式差异（system prompt/tools/tool_use/响应格式）。切换模型只需改 `.env`，不需要改代码。

---

## 测试

### 安装测试依赖

```bash
pip install pytest
```

### 运行单元测试

```bash
cd "coding agent"
pytest tests/unit/ -v
```

### 运行组件测试

```bash
pytest tests/component/ -v
```

### 运行全部测试（单元+组件）

```bash
pytest tests/ -v
```

### 运行集成测试（需要 API Key）

```bash
pytest tests/integration/ -v -s
```

### 测试覆盖的模块

| 测试文件 | 覆盖模块 |
|---------|---------|
| `tests/unit/test_permissions.py` | 权限控制（5 种模式、规则匹配、危险检测） |
| `tests/unit/test_compact.py` | 上下文压缩（TokenTracker、CircuitBreaker、Budget） |
| `tests/unit/test_utils.py` | 工具函数（truncate、safe_path） |
| `tests/unit/test_skills.py` | Skills 加载（frontmatter、参数替换、多目录） |
| `tests/unit/test_definitions.py` | Agent 类型定义 |
| `tests/unit/test_task_queue.py` | 异步任务队列 |
| `tests/unit/test_edit_tool.py` | 文件编辑（引号容错、唯一匹配、diff） |
| `tests/unit/test_llm_adapter.py` | LLM 适配层（Anthropic/OpenAI 格式转换） |
| `tests/component/test_agent_loop.py` | Agent Loop（Mock LLM 的流程测试） |
| `tests/integration/test_real_llm.py` | 真实 LLM 集成（连通性/Tool Calling/多轮对话） |

### 模块评估

7 个模块的系统化评估（6 个免费 + 1 个需 LLM）：

```bash
# 运行所有免费评估
python eval/eval_permissions.py   # 权限控制 (198 用例)
python eval/eval_tools.py         # 工具实现 (~30 用例)
python eval/eval_compact.py       # 上下文压缩 (~20 用例)
python eval/eval_skills.py        # Skills 系统 (~15 用例)
python eval/eval_memory.py        # Memory 系统 (~12 用例)
python eval/eval_mcp.py           # MCP 集成 (~10 用例)

# 需 LLM 的评估（需要 API Key）
python eval/eval_subagent.py      # 子 Agent (~8 用例, ~$0.05)

# 通过 pytest 运行全部（含阈值断言）
pytest eval/ -v
```

详见 `项目评估体系详解.md`。

---

## 目录结构

```
coding agent/
├── main.py                    # CLI 入口
├── query.py                   # Agent Loop 状态机
├── context.py                 # System Prompt 构建（含 Prompt Cache）
├── system-prompt.md           # 提示词模板
├── bootstrap/state.py         # 集中式状态存储
├── screens/repl.py            # REPL 界面
├── tools/                     # 工具系统
│   ├── BashTool.py            # Shell（含 run_in_background）
│   ├── FileReadTool.py        # 文件读取
│   ├── FileWriteTool.py       # 文件写入
│   ├── FileEditTool.py        # 文件编辑
│   ├── ListFilesTool.py       # 文件列表
│   ├── GrepSearchTool.py      # 内容搜索
│   ├── AgentTool.py           # 统一入口（SubAgent + Team）
│   ├── SkillTool.py           # 技能加载
│   ├── TodoTool.py            # 待办清单
│   ├── TaskTool.py            # 持久化任务
│   └── CommTool.py            # 团队通信
├── agents/                    # 多 Agent 系统
│   ├── definitions.py         # 4 种内置类型
│   ├── subagent.py            # SubAgent（同步+异步）
│   ├── task_queue.py          # 异步通知队列
│   ├── coordinator.py         # Coordinator 模式
│   └── team.py                # Swarm 队友
├── services/                  # 服务层
│   ├── compact.py             # 五级压缩流水线
│   ├── permissions.py         # 权限控制（三层管线）
│   ├── mcp.py                 # MCP 集成
│   ├── memory.py              # 跨会话记忆
│   ├── bus.py                 # 消息总线
│   ├── tasks.py               # 任务管理
│   └── background.py          # 后台执行
├── skills/                    # 技能文件
│   └── commit/SKILL.md        # 示例技能
├── utils/                     # 工具库
│   ├── path.py                # 路径安全
│   └── truncate.py            # 结果截断
└── tests/                     # 测试
    ├── unit/                  # 单元测试
    └── component/             # 组件测试
```

## 技术栈

- **语言**: Python 3.10+
- **LLM**: Anthropic SDK（可通过代理使用任意模型）
- **协议**: MCP（Model Context Protocol）
- **并发**: threading
- **持久化**: JSON 文件
- **测试**: pytest
