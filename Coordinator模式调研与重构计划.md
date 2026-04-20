# Coordinator 模式调研与重构计划

## 一、当前项目 Coordinator 模式的实现分析

### 1.1 架构概述

当前项目的 Coordinator 模式是**主 Agent 的一种运行模式切换**，通过环境变量 `COORDINATOR_MODE=1` 激活。

```
用户请求
    ↓
query.py::agent_loop()
    ↓
检测 is_coordinator_mode() = True
    ↓
系统提示词 → COORDINATOR_SYSTEM_PROMPT
工具集 → COORDINATOR_ALLOWED_TOOLS (仅管理工具)
    ↓
Coordinator (主 Agent) 思考 → 自己规划任务
    ↓
调用 agent 工具 → 派生 Worker (并行)
    ↓
Worker 执行结果通过 AgentTaskQueue 通知主 Agent
    ↓
Coordinator 综合结果，决定下一步
```

### 1.2 核心代码实现

**文件：`agents/coordinator.py`**

```python
# 工具白名单（有问题 - 引用了已删除的 Team 模式工具）
COORDINATOR_ALLOWED_TOOLS = frozenset({
    "agent",            # 派生 Worker
    "send_message",     # ❌ 向队友发消息 (Team 模式已删除)
    "read_inbox",       # ❌ 读取收件箱 (Team 模式已删除)
    "broadcast",        # ❌ 广播消息 (Team 模式已删除)
    "list_teammates",   # ❌ 列出队友 (Team 模式已删除)
})

# 系统提示词
COORDINATOR_SYSTEM_PROMPT = """\
You are a Coordinator — a project manager that breaks down complex tasks \
and delegates them to specialized Worker agents.
...
"""
```

**文件：`query.py` 中的模式切换逻辑**

```python
if is_coordinator_mode():
    coord_config = get_coordinator_config()
    system_prompt = coord_config["system_prompt"]
    allowed = coord_config["allowed_tools"]
    tool_defs = [d for d in all_defs if d["name"] in allowed]
    tool_handlers = {k: v for k, v in all_handlers.items() if k in allowed}
else:
    system_prompt = build_system_prompt()
    tool_defs = all_defs
    tool_handlers = all_handlers
```

### 1.3 四种 Worker Agent 类型

定义在 `agents/definitions.py`：

| 类型 | 系统提示词 | 工具集 | max_turns | 异步默认 |
|------|----------|--------|----------|---------|
| `explore` | 只读代码探索专家 | READ_ONLY_TOOLS | 15 | 否 |
| `plan` | 结构化规划专家 | READ_ONLY_TOOLS | 20 | 否 |
| `general` | 通用执行智能体（可执行任何任务） | GENERAL_TOOLS | 30 | 否 |
| `verification` | 对抗性验证专家 | READ_ONLY_TOOLS | 20 | **是** |

---

## 二、当前实现的问题分析

### 2.1 严重问题：依赖已删除的 Team 模式

**问题描述**：Coordinator 的工具白名单包含 Team 模式专属工具，但这些文件已在删除 Team 模式时被移除。

**影响**：
1. 工具白名单中的 `send_message`、`read_inbox`、`broadcast`、`list_teammates` 无法找到处理函数
2. 提示词错误地告诉 Coordinator 可以使用这些不存在的工具

### 2.2 用户理解的协调者模式 vs 当前实现

**用户期望的 Orchestrator 模式**：
```
┌─────────────────────────────────────────────────────┐
│                    Orchestrator                      │
│  (接收用户请求 → 自己规划任务 → 分发给 Worker → 汇总结果) │
└─────────────────────────────────────────────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
    ┌─────────┐     ┌─────────┐     ┌─────────┐
    │ Worker1 │     │ Worker2 │     │ Worker3 │
    │(并行执行)│     │(并行执行)│     │(并行执行)│
    └────┬────┘     └────┬────┘     └────┬────┘
         │               │               │
         └───────────────┼───────────────┘
                         ▼
              ┌─────────────────────┐
              │ 汇报给 Orchestrator   │
              │  (结果汇总)           │
              └─────────────────────┘
```

**当前实现的 Coordinator**：
- ✅ 任务规划和分发机制存在
- ✅ Worker 派生机制存在
- ⚠️ 工具白名单引用了已删除的 Team 通信工具
- ⚠️ **缺少对"无依赖并行"的专业提示词设计**

### 2.3 问题根因

1. **设计时参考了 Claude Code 的 Swarm Team 架构**：Coordinator 原本设计来与 Swarm Team 配合使用

2. **删除 Team 模式后未同步更新 Coordinator**：导致工具白名单过时

---

## 三、重构计划

### 3.1 重构目标

实现用户理解的 Orchestrator 协调者模式：
1. **任务规划是协调者的核心职责**：协调者自己分析任务、拆分为可并行的子任务
2. **并行执行**：使用 `run_in_background=True` 派生多个 Worker 并行执行
3. **结果汇总**：Worker 完成后，协调者负责汇总结果并响应用户
4. **适用场景**：任何可拆分的复杂任务 —— 调研、写文档、实现功能等

### 3.2 提示词结构澄清

```
Coordinator 主 Agent (系统提示词: COORDINATOR_SYSTEM_PROMPT)
    │
    ├── 收到用户请求
    │
    ├── 自己分析任务，决定如何拆分（Plan 是协调者的职责，不是派生子 Agent）
    │
    └── 派生多个 Worker 并行执行子任务
            │
            └── Worker 返回结果 (task-notification)
                    │
                    └── Coordinator 汇总结果
```

**关键点**：
- **Plan 是 Coordinator 自己做的**，不需要派生子 Agent
- Coordinator 只需要只读调研工具 + agent 工具

### 3.3 重构方案

#### Phase 1：修复并完善工具白名单

**文件：`agents/coordinator.py`**

```python
# 重构后
COORDINATOR_ALLOWED_TOOLS = frozenset({
    "agent",            # 派生 Worker
    "read_file",        # 读取文件
    "list_files",       # 列出文件
    "grep_search",      # 搜索代码
    "run_shell",        # 运行命令
})
```

**关键约束**：`write_file` 和 `edit_file` 不在白名单中 —— Coordinator 不直接修改文件。

**输出方式**：Coordinator 通过最终的文本输出（LLM 的文本响应）呈现汇总结果给用户，不需要写文件工具。

#### Phase 2：重新设计 Coordinator 系统提示词

```python
COORDINATOR_SYSTEM_PROMPT = f"""\
You are an Orchestrator — a project manager that decomposes complex requests \
into independent sub-tasks, delegates to Workers, and synthesizes results.

## YOUR RESPONSIBILITIES

1. **Plan**: Analyze request, decompose into independent sub-tasks
2. **Delegate**: Spawn Workers to execute sub-tasks in parallel
3. **Synthesize**: Collect results and present final output to user

## DECOMPOSITION RULES

**CRITICAL**: Sub-tasks must be truly independent:
- Each Worker works on DIFFERENT files or topics
- No Worker waits for another Worker
- Each outputs a self-contained result

**If tasks have dependencies, they CANNOT run in parallel — consider using SubAgent mode instead.**

## DELEGATION

- Use `agent(run_in_background=True)` for parallel execution
- Provide each Worker: task description, target files, expected output
- Workers run independently and concurrently

## RESULT SYNTHESIS

After Workers complete:
1. Collect all task-notifications
2. Integrate findings into a coherent response
3. Output directly to user (you are the final deliverable)

## WORKER TYPES

- **explore**: Read-only investigation
- **general**: Full capability (can execute any task, including file operations, shell commands, etc.)
- **verification**: Adversarial testing

## PARALLEL EXAMPLE

User: "Analyze this codebase: auth system, database, API, tests"

```
1. [Worker: explore] Analyze auth system
   - Files: auth/*.py
   - Output: Auth architecture summary

2. [Worker: explore] Analyze database models
   - Files: models/*.py, db/*.py
   - Output: DB schema summary

3. [Worker: explore] Analyze API endpoints
   - Files: api/*.py, routes/*.py
   - Output: API inventory

4. [Worker: explore] Analyze test coverage
   - Files: tests/*.py
   - Output: Test status report

PARALLEL: All 4 tasks — no dependencies, different files
```

## WORKING DIRECTORY: {WORKDIR}
"""
```

**关键改进**：
- 强调"无依赖"是并行的前提
- 强调 Coordinator 通过最终文本来输出结果
- 示例展示真正的并行（4个调研任务，无依赖）
- 去掉冗余的"YOUR ROLE"列表（与"RESPONSIBILITIES"重复）

### 3.4 重构文件清单

| 文件 | 修改内容 |
|------|---------|
| `agents/coordinator.py` | 1. 更新工具白名单（移除 Team 工具）<br>2. 更新 COORDINATOR_SYSTEM_PROMPT（重写提示词） |
| `tools/__init__.py` | 无需修改（只过滤 `agent` 工具即可） |

### 3.5 验证计划

1. 编写单元测试验证 Coordinator 模式激活正常
2. 手动测试完整工作流：
   - 设置 `COORDINATOR_MODE=1`
   - 发送复杂调研请求
   - 验证 Worker 并行执行
   - 验证结果正确汇总

---

## 四、预期效果

### 重构前
```
Coordinator 收到请求
  ↓
工具白名单包含已删除的 Team 工具
  ↓
提示词与实际功能不符
```

### 重构后
```
Coordinator 收到请求
  ↓
（如需要）调研代码库以了解结构
  ↓
自己进行任务规划（输出 PLAN）
  ↓
并行派生多个 Worker (run_in_background=True)
  ↓
Worker 执行中...（并行）
  ↓
结果通过 task-notification 汇总
  ↓
Coordinator 合成最终结果
  ↓
响应用户
```

---

## 五、注意事项

1. **Coordinator 通过文本输出结果**：不需要 write_file，直接把汇总后的内容作为最终响应输出给用户

2. **无依赖是并行的前提**：如果任务之间有依赖，就不要强求并行，用 SubAgent 模式更合适

3. **Coordinator 工具集**：只读调研工具 + agent 工具，职责清晰
