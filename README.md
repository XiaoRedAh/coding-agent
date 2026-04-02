# Coding Agent - 模块化 AI 编程代理

一个功能完整的 AI 编程代理，集成了工具调用、任务管理、上下文压缩、后台执行、团队协作等机制。基于 Anthropic Claude API 构建。

## 架构概览

```
+------------------------------------------------------------------+
|                        CODING AGENT                               |
|                                                                   |
|  System prompt (技能加载 + 任务优先 + 待办提醒)                     |
|                                                                   |
|  每次 LLM 调用前:                                                  |
|  +--------------------+  +------------------+  +--------------+   |
|  | 微压缩 + 自动压缩   |  | 后台任务通知      |  | 收件箱检查    |   |
|  | (context)          |  | (background)     |  | (comm)       |   |
|  +--------------------+  +------------------+  +--------------+   |
|                                                                   |
|  工具分发 (tools/registry):                                        |
|  +--------+----------+----------+---------+-----------+           |
|  | bash   | read     | write    | edit    | TodoWrite |           |
|  | task   | load_sk  | compress | bg_run  | bg_check  |           |
|  | t_crt  | t_get    | t_upd    | t_list  | spawn_tm  |           |
|  | list_tm| send_msg | rd_inbox | bcast   | shutdown  |           |
|  | plan   | idle     | claim    |         |           |           |
|  +--------+----------+----------+---------+-----------+           |
|                                                                   |
|  子代理 (agents/subagent):  spawn -> work -> return summary       |
|  队友 (agents/team):       spawn -> work -> idle -> auto-claim    |
|  关闭协议 (communication): request_id handshake                    |
|  计划审批 (communication): submit -> approve/reject                |
+------------------------------------------------------------------+
```

## 目录结构

```
coding agent/
├── README.md              # 本文件
├── .env.example           # 环境变量示例
├── requirements.txt       # Python 依赖
├── main.py                # 入口文件（REPL + agent_loop）
├── config.py              # 全局配置（路径、常量、客户端初始化）
├── tools/
│   ├── __init__.py        # 导出基础工具函数
│   ├── base.py            # 核心工具：safe_path, run_bash, run_read, run_write, run_edit
│   ├── registry.py        # TOOL_HANDLERS 工具处理函数映射表
│   └── definitions.py     # 所有工具的 JSON Schema 定义
├── planning/
│   ├── __init__.py        # 导出 TodoManager 和 TaskManager
│   ├── todo.py            # TodoManager - 内存待办清单
│   └── tasks.py           # TaskManager - 文件持久化任务系统
├── context/
│   ├── __init__.py        # 导出压缩函数和 SkillLoader
│   ├── compression.py     # token 估算、微压缩、自动压缩
│   └── skills.py          # SkillLoader - SKILL.md 文件加载器
├── agents/
│   ├── __init__.py        # 导出 run_subagent 和 TeammateManager
│   ├── subagent.py        # 一次性子代理（Explore / general-purpose）
│   └── team.py            # TeammateManager - 持久化自主队友管理
├── communication/
│   ├── __init__.py        # 导出 MessageBus 和协议函数
│   ├── bus.py             # MessageBus - 基于文件的消息总线
│   └── protocols.py       # 关闭请求和计划审批协议
└── background/
    ├── __init__.py        # 导出 BackgroundManager
    └── manager.py         # BackgroundManager - 异步后台命令执行
```

### 模块说明

| 模块 | 职责 |
|------|------|
| `config.py` | 集中管理路径常量、API 客户端、模型配置、阈值参数 |
| `tools/` | 文件/命令操作工具、JSON schema 定义、工具名到处理函数的映射 |
| `planning/` | 两种任务管理：轻量内存待办（Todo）+ 文件持久化任务（Task） |
| `context/` | 对话上下文压缩（三层策略）+ 技能文件加载 |
| `agents/` | 子代理（一次性隔离任务）+ 团队队友（持久化自主工作） |
| `communication/` | 消息总线（文件收件箱）+ 关闭/审批协议 |
| `background/` | 异步后台命令执行，线程 + 通知队列 |

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
- **架构模式**: 工具分发 + 依赖注入 + 消息队列
