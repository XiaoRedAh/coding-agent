# Coding Agent - 模块化 AI 编程代理

一个功能完整的 AI 编程代理，集成了工具调用、任务管理、上下文压缩、后台执行、团队协作等机制。基于 Anthropic Claude API 构建。

项目结构参考 [Claude Code](https://github.com/anthropics/claude-code) 源码的架构模式进行组织。

## 架构概览

```
+------------------------------------------------------------------+
|                        CODING AGENT                               |
|                                                                   |
|  main.py (CLI 入口)                                               |
|    ├── init(): 初始化所有全局单例 → bootstrap/state.py              |
|    └── run_repl(): 分发到 screens/repl.py                         |
|                                                                   |
|  query.py (核心查询循环):                                          |
|  +----------------------------------------------------+         |
|  | 压缩检查 -> 后台通知 -> 收件箱 -> LLM 调用 -> 工具执行 |         |
|  +----------------------------------------------------+         |
|                                                                   |
|  工具分发 (tools/):                                                |
|  +----------+------------+-----------+----------+                 |
|  | BashTool | FileRead   | FileWrite | FileEdit |                 |
|  | TodoTool | TaskTool   | AgentTool | SkillTool|                 |
|  | BgTool   | CommTool   | Compress  |          |                 |
|  +----------+------------+-----------+----------+                 |
|                                                                   |
|  服务层 (services/):                                               |
|  +----------+-----------+------------+-------------+              |
|  | compact  | bus       | tasks      | background  |              |
|  | (压缩)   | (消息总线) | (持久任务)  | (后台执行)   |              |
|  +----------+-----------+------------+-------------+              |
|                                                                   |
|  代理系统 (agents/):                                               |
|  ├── subagent: spawn → work → return summary                     |
|  └── team:     spawn → work → idle → auto-claim                  |
+------------------------------------------------------------------+
```

## 目录结构

```
coding agent/
├── main.py                    # CLI 主入口：初始化所有单例 + 分发到 REPL
├── query.py                   # 核心查询循环（压缩→API调用→工具执行→通知）
├── context.py                 # 上下文构建（系统提示词组装）
│
├── bootstrap/                 # 全局状态管理
│   └── state.py               # 集中式状态存储（路径、客户端、阈值、运行时实例）
│                              # 所有子系统通过访问器读写共享状态，避免 import 循环
│
├── screens/                   # 界面层
│   └── repl.py                # REPL 交互界面（命令解析、输出渲染）
│
├── tools/                     # 工具系统（每个工具独立模块）
│   ├── __init__.py            # 工具注册与组装（聚合所有定义和处理函数）
│   ├── BashTool.py            # Shell 命令执行（含危险命令过滤）
│   ├── FileReadTool.py        # 文件读取（支持行数限制）
│   ├── FileWriteTool.py       # 文件写入（自动创建父目录）
│   ├── FileEditTool.py        # 文件编辑（search-and-replace 策略）
│   ├── TodoTool.py            # 内存待办清单（TodoManager）
│   ├── TaskTool.py            # 持久化任务管理（创建/查询/更新/认领）
│   ├── AgentTool.py           # 子代理派生（Explore / general-purpose）
│   ├── SkillTool.py           # 技能加载（SKILL.md 文件）
│   ├── BackgroundTool.py      # 后台命令执行（异步线程）
│   ├── CommTool.py            # 通信工具（消息/广播/关闭/审批）
│   └── CompressTool.py        # 上下文压缩信号
│
├── services/                  # 服务层
│   ├── compact.py             # 压缩系统（token 估算、微压缩、自动压缩）
│   ├── bus.py                 # 消息总线（基于文件的消息传递）
│   ├── tasks.py               # 持久化任务管理器（JSON 文件存储）
│   └── background.py          # 后台任务管理器（线程 + 通知队列）
│
├── agents/                    # 代理系统
│   ├── subagent.py            # 一次性子代理（独立上下文，最多 30 轮）
│   └── team.py                # 持久化自主队友（工作/空闲/关闭生命周期）
│
├── skills/                    # 技能系统
│   └── loader.py              # SKILL.md 文件加载器（YAML frontmatter 解析）
│
├── utils/                     # 通用工具库
│   └── path.py                # 路径安全检查（防路径逃逸）
│
├── .env.example               # 环境变量示例
└── requirements.txt           # Python 依赖
```

### 与 Claude Code 源码的结构对照

| 本项目 | Claude Code 源码 | 职责 |
|--------|-----------------|------|
| `main.py` | `main.tsx` + `entrypoints/init.ts` | 入口初始化与分发 |
| `query.py` | `query.ts` | 核心查询循环状态机 |
| `context.py` | `context.ts` | 系统提示词构建 |
| `bootstrap/state.py` | `bootstrap/state.ts` | 集中式状态存储 |
| `screens/repl.py` | `screens/REPL.tsx` | 交互界面 |
| `tools/*Tool.py` | `tools/BashTool/` 等 | 独立工具模块 |
| `services/compact.py` | `services/compact/` | 压缩系统 |
| `services/bus.py` | 无直接对应（类似 MCP） | 消息总线 |
| `services/tasks.py` | 无直接对应 | 持久化任务管理 |
| `agents/subagent.py` | `tools/AgentTool/` | 子代理 |
| `agents/team.py` | `coordinator/` | 多代理协调 |
| `skills/loader.py` | `skills/` | 技能系统 |
| `utils/path.py` | `utils/` | 通用工具 |

### 模块职责说明

| 模块 | 职责 |
|------|------|
| `bootstrap/state.py` | 集中管理路径常量、API 客户端、模型配置、阈值参数、运行时单例引用 |
| `tools/` | 每个工具独立定义 JSON Schema 和处理函数，`__init__.py` 统一聚合 |
| `services/` | 跨模块共享的核心服务：压缩、消息总线、任务持久化、后台执行 |
| `agents/` | 子代理（一次性隔离任务）+ 团队队友（持久化自主工作） |
| `skills/` | SKILL.md 技能文件扫描、解析与按需加载 |
| `utils/` | 路径安全检查等通用工具函数 |

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key 和模型 ID
```

必须配置的环境变量：
- `ANTHROPIC_API_KEY`: Anthropic API 密钥
- `MODEL_ID`: 使用的模型（如 `claude-sonnet-4-20250514`）
- `ANTHROPIC_BASE_URL`（可选）: 自定义 API 地址

### 3. 运行

```bash
cd "coding agent"
python main.py
```

## 使用示例

### 基础对话

```
coding-agent >> 帮我分析一下当前目录的项目结构
> bash:
src/ tests/ README.md ...
（LLM 分析并回答）
```

### 多步骤任务

```
coding-agent >> 帮我重构 utils.py，拆分成多个模块
> task_create:
{"id": 1, "subject": "重构 utils.py", ...}
> TodoWrite:
[ ] 分析 utils.py 的函数分组
[>] 创建新模块文件 <- 进行中
[ ] 迁移函数
```

### 后台执行

```
coding-agent >> 在后台运行测试
> background_run:
Background task a1b2c3d4 started: pytest
（稍后自动收到通知）
```

### REPL 命令

| 命令 | 说明 |
|------|------|
| `/compact` | 手动压缩对话上下文 |
| `/tasks` | 查看所有持久化任务 |
| `/team` | 查看团队队友状态 |
| `/inbox` | 读取 lead 收件箱 |
| `q` / `exit` | 退出 |

## 技术栈

- **语言**: Python 3.10+
- **LLM API**: Anthropic Claude (anthropic SDK)
- **并发**: threading（后台任务、队友线程）
- **持久化**: JSON 文件（任务、团队配置、消息收件箱）
- **架构模式**: 集中式状态管理 + 工具分发 + 服务层分离
