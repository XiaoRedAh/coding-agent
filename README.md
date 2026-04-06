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

编辑 `.env` 文件：

```bash
# 方案 A: 使用 Claude（Anthropic 官方）
ANTHROPIC_API_KEY=sk-ant-xxx
MODEL_ID=claude-sonnet-4-20250514

# 方案 B: 使用 DeepSeek（通过 OpenRouter，更便宜）
ANTHROPIC_BASE_URL=https://openrouter.ai/api/v1
ANTHROPIC_API_KEY=sk-or-v1-xxx
MODEL_ID=deepseek/deepseek-chat

# 方案 C: 使用其他模型（通过任何 Anthropic API 兼容代理）
ANTHROPIC_BASE_URL=https://your-proxy.example.com/v1
ANTHROPIC_API_KEY=your-key
MODEL_ID=your-model-id
```

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

### 运行全部测试

```bash
pytest tests/ -v
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
| `tests/component/test_agent_loop.py` | Agent Loop（Mock LLM 的流程测试） |

### 模块评估

权限控制模块的系统化评估（不调 LLM，$0）：

```bash
# 方式 1: 独立运行，输出评估报告
python tests/eval/eval_permissions.py

# 方式 2: 通过 pytest 运行（含阈值断言）
pytest tests/eval/eval_permissions.py -v
```

输出示例：

```
======================================================================
  权限控制模块评估报告
======================================================================

✅ 危险命令拦截率 (Recall): 21/21 (100.0%)
✅ 安全命令误报率 (1 - FPR): 28/28 (100.0%)
✅ 危险路径拦截率: 10/10 (100.0%)
✅ 安全路径放行率: 7/7 (100.0%)
✅ 规则+模式决策准确率: 20/20 (100.0%)
✅ 模式矩阵一致性: 20/20 (100.0%)

----------------------------------------------------------------------
  总计: 106/106 (100.0%)
  API 调用: 0 次  |  费用: $0
----------------------------------------------------------------------
```

评估维度说明：

| 维度 | 用例数 | 达标阈值 | 说明 |
|------|--------|---------|------|
| 危险命令拦截率 | 21 | ≥95% | 21 种危险命令模式（rm -rf/sudo/git force push/curl\|sh等） |
| 安全命令放行率 | 28 | ≥95% | 28 种安全命令（ls/git status/npm test/curl GET等） |
| 危险路径拦截率 | 10 | =100% | .git/.ssh/.env/.bashrc 等 bypass-immune 路径 |
| 安全路径放行率 | 7 | =100% | src/*.py/README.md 等普通路径 |
| 规则+模式决策准确率 | 20 | =100% | deny>allow 优先级/5种模式/bypass-immune/safe tools |
| 模式矩阵一致性 | 20 | =100% | 同一操作在 5 种模式下的预期行为一致性 |

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
