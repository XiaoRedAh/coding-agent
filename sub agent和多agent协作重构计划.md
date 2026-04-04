# Sub Agent 和多 Agent 协作重构计划

---

## 一、上次重构的反思

### 1.1 对 Claude Code 实现理解不到位的问题

#### 问题 1：Fork 模式的本质理解偏差

**上次实现**：Fork 通过"摘要父对话历史注入子 Agent 首条消息"实现上下文继承。

**cc 实际做法**：Fork 的核心是**字节级继承父 Agent 的完整 API 请求前缀**——系统提示、工具定义、完整对话历史全部保持一致，只有最后一条 user 消息中的指令文本不同。目的是最大化 Prompt Cache 命中。

**偏差原因**：我们没有 Prompt Cache，所以用"摘要注入"替代。但这导致 Fork 和 Simple 的区别变得模糊——都是给子 Agent 一段文本作为开头。实际上 cc 的 Fork 和 Simple 在请求结构上有根本差异。

**修正方向**：Fork 模式应该直接传递父对话的完整消息历史（而非摘要），加上 fork 专用的指令消息。虽然没有缓存节省，但至少行为语义正确——子 Agent 能看到父 Agent 的完整上下文。

#### 问题 2：Coordinator 实现过于简化

**上次实现**：Coordinator 自己管理一个独立的 agent loop，用自定义工具（spawn_worker, read_scratchpad, list_scratchpad, done）。

**cc 实际做法**：Coordinator 不是一个独立的 agent 循环——它是**主 Agent 的一种运行模式**。当 `CLAUDE_CODE_COORDINATOR_MODE=1` 时，主 Agent 变成协调者：
- 系统提示被替换为协调者提示
- 工具池被过滤为只保留 Agent/SendMessage/TaskStop/SyntheticOutput
- 所有 spawn 的子 Agent 自动异步运行
- Worker 通过 task-notification XML 回报结果

**偏差原因**：我错误地把 Coordinator 实现为一个独立的子系统，而非主 Agent 的模式切换。

**修正方向**：Coordinator 应通过修改主 Agent 的配置（系统提示 + 工具池过滤）来实现，而非创建全新的循环。

#### 问题 3：Swarm/Team 和 Coordinator 的关系理解不清

**上次理解**：Swarm 是 Coordinator 的"升级版"，支持对等通信。

**cc 实际做法**：Swarm Team 是一个**独立于 Coordinator 的系统**。它通过 TeammateExecutor 接口管理持久化队友，支持 3 种后端（Tmux/iTerm2/InProcess）。Team 有自己的文件配置、成员管理、信箱系统。而 Coordinator 是主 Agent 的一种模式，不涉及 Team 机制。

**修正方向**：将 Coordinator 和 Swarm 作为两个独立的系统实现，而非层级关系。

#### 问题 4：内置 Agent 的触发机制理解偏差

**上次理解**：似乎暗示系统自动选择 Agent 类型。

**cc 实际做法**：4 种内置 Agent 不是预创建的，也不是系统自动选择的——**是 LLM 自己决定的**。AgentTool 的 prompt 中包含每种类型的 `whenToUse` 描述，LLM 根据任务性质在调用 agent 工具时传入 `subagent_type` 参数。如果未指定且 Fork 实验开启，则走 implicit fork 路径。

### 1.2 代码工程问题

#### 问题 1：工具定义重复

`agents/subagent.py` 中手动维护了一套 `_TOOL_SCHEMAS` 字典，和 `tools/` 下各工具模块的 `DEFINITION` 重复。任何工具参数变动需要两处同步修改。

**修正方向**：子 Agent 的工具定义应从各工具模块的 `DEFINITION` 中动态提取，而非硬编码。

#### 问题 2：工具处理函数重复

`_TOOL_DISPATCH` 字典和 `tools/__init__.py` 的 `get_all_handlers()` 功能重叠。

**修正方向**：子 Agent 的工具处理应复用 `tools/__init__.py` 的注册机制，通过工具名过滤即可。

#### 问题 3：agent loop 重复

`_run_agent_loop()` 是 `query.py` 的 `agent_loop()` 的简化版本。两者逻辑类似但不共用，导致维护两套循环。

**修正方向**：抽取通用的 agent loop 核心逻辑，让主 Agent 和子 Agent 共用。差异通过参数化控制（系统提示、工具集、是否压缩、max_turns 等）。

#### 问题 4：Fork 的结果通知机制缺失

Fork 子 Agent 异步执行后，结果通过 `on_complete` 回调通知，但主 Agent 的 agent_loop 中没有处理这个回调的机制——Fork 结果实际上被丢弃了。

**修正方向**：
- 方案 A：Fork 结果写入一个共享队列，主 Agent 每轮循环检查（类似 BackgroundManager.drain()）
- 方案 B：对齐 cc 的 `<task-notification>` 机制，Fork 结果作为 user 消息注入

---

## 二、重构计划

### 2.1 设计原则

1. **复用优先**：子 Agent 复用主 Agent 的工具定义、处理函数和 agent loop
2. **配置驱动**：不同模式/类型通过配置差异区分，而非代码分支
3. **正确语义**：每种模式的行为语义对齐 cc，即使实现细节简化
4. **渐进式**：先实现 Simple + Fork，再启用 Coordinator + Swarm

### 2.2 目标文件结构

```
agents/
├── __init__.py              # 导出
├── definitions.py           # 4 种内置 Agent 类型配置（提示词 + 工具集 + 参数）
├── runner.py                # 通用 agent loop（主 Agent 和子 Agent 共用）
├── subagent.py              # Simple + Fork 模式（使用 runner.py）
├── coordinator.py           # Coordinator 模式（主 Agent 模式切换）
├── team.py                  # Swarm Team（持久化队友）
└── task_queue.py            # 异步任务队列（Fork/背景任务的结果通知）
```

### 2.3 核心重构：抽取通用 agent loop

**目标**：`agents/runner.py` 提供一个通用的 `run_agent()` 函数，主 Agent 和子 Agent 都使用它。

```python
# agents/runner.py — 通用 agent loop

def run_agent(
    system_prompt: str,
    messages: list,
    tool_defs: list,          # 工具 JSON Schema 列表
    tool_handlers: dict,      # 工具名 → 处理函数
    max_turns: int = 30,
    tracker: TokenTracker = None,   # 可选：token 追踪
    breaker: CircuitBreaker = None, # 可选：断路器
    enable_compression: bool = True, # 主 Agent 开启，子 Agent 关闭
    on_tool_result: Callable = None, # 工具执行后回调（主 Agent 用于 UI）
) -> str:
    """通用 agent loop，主 Agent 和子 Agent 共用。"""
```

**差异通过参数控制**：

| 参数 | 主 Agent | 子 Agent |
|------|---------|---------|
| `enable_compression` | True | False |
| `tracker` / `breaker` | 传入实例 | None |
| `on_tool_result` | 打印输出 | 静默 |
| `max_turns` | 无限制 | 15-30 |

### 2.4 消除工具定义重复

**目标**：子 Agent 从 `tools/` 模块动态提取工具定义和处理函数。

```python
# agents/subagent.py — 从全局工具注册表过滤

from tools import get_all_definitions, get_all_handlers

def _filter_tools(allowed_names: set):
    """从全局工具池中过滤出子 Agent 允许使用的工具"""
    all_defs = get_all_definitions()
    all_handlers = get_all_handlers()
    
    defs = [d for d in all_defs if d["name"] in allowed_names]
    handlers = {k: v for k, v in all_handlers.items() if k in allowed_names}
    return defs, handlers
```

### 2.5 Fork 模式修正

**目标**：Fork 传递完整父消息历史（非摘要），加上 fork 专用指令。

```python
def fork_subagent(prompt, parent_messages, agent_type="general"):
    # 不是摘要——是完整的父消息历史
    fork_messages = list(parent_messages)  # 浅拷贝
    # 追加 fork 指令
    fork_messages.append({
        "role": "user",
        "content": f"[Fork task — complete independently]\n{prompt}"
    })
    # 异步执行
    threading.Thread(target=_run_fork, args=(fork_messages, agent_type), daemon=True).start()
```

### 2.6 异步结果通知机制

**目标**：Fork/后台任务完成后，结果通过队列注入主 Agent 的消息流。

```python
# agents/task_queue.py — 异步任务结果队列

class AgentTaskQueue:
    """管理异步子 Agent 的结果通知"""
    
    def __init__(self):
        self._results = Queue()
    
    def submit_result(self, agent_id: str, agent_type: str, result: str):
        """子 Agent 完成后提交结果"""
        self._results.put({
            "agent_id": agent_id,
            "type": agent_type,
            "result": result,
            "timestamp": time.time(),
        })
    
    def drain(self) -> list:
        """获取所有待处理的结果"""
        results = []
        while not self._results.empty():
            results.append(self._results.get_nowait())
        return results
```

在 `query.py` 的 agent_loop 中：

```python
# 检查异步 Agent 结果（类似 bg.drain()）
agent_results = state.agent_tasks.drain()
if agent_results:
    txt = "\n".join(
        f"<task-notification>\n"
        f"  <task-id>{r['agent_id']}</task-id>\n"
        f"  <status>completed</status>\n"
        f"  <result>{r['result'][:2000]}</result>\n"
        f"</task-notification>"
        for r in agent_results
    )
    messages.append({"role": "user", "content": txt})
```

### 2.7 Coordinator 模式修正

**目标**：Coordinator 是主 Agent 的模式切换，不是独立系统。

```python
# agents/coordinator.py — 模式切换而非独立系统

COORDINATOR_TOOLS = {"agent", "send_message", "read_inbox"}  # 只有管理工具

def get_coordinator_config():
    """返回 Coordinator 模式的配置覆盖"""
    return {
        "system_prompt": COORDINATOR_SYSTEM_PROMPT,
        "allowed_tools": COORDINATOR_TOOLS,
        "force_async_subagents": True,  # 所有子 Agent 强制异步
    }
```

在 `query.py` 中：

```python
if COORDINATOR_MODE:
    config = get_coordinator_config()
    system_prompt = config["system_prompt"]
    tool_defs = [d for d in all_defs if d["name"] in config["allowed_tools"]]
    tool_handlers = {k: v for k, v in all_handlers.items() if k in config["allowed_tools"]}
```

### 2.8 Swarm Team 保持现有实现

现有的 `agents/team.py`（TeammateManager）已经实现了 Swarm 的核心功能：
- 队友在独立线程中运行
- 通过 MessageBus 通信
- 支持自动认领任务
- 工作-空闲-关闭生命周期

保持不变，但需要：
- 将工具定义从硬编码改为从全局注册表过滤（消除重复）
- 添加 team name / agent id 的标准化

### 2.9 实施步骤

```
步骤 1: 创建 agents/runner.py（通用 agent loop）
  - 从 query.py 提取核心循环
  - 参数化差异（压缩、tracker、max_turns 等）
  - query.py 改为调用 runner.py

步骤 2: 创建 agents/task_queue.py（异步结果通知）
  - AgentTaskQueue 类
  - 在 state.py 中注册实例
  - 在 query.py 的 agent_loop 中 drain 结果

步骤 3: 重写 agents/subagent.py
  - 工具定义/处理从全局注册表过滤（消除重复）
  - Simple: 使用 runner.run_agent()
  - Fork: 传递完整父消息历史 + fork 指令
  - Fork 结果提交到 AgentTaskQueue

步骤 4: 重写 agents/coordinator.py
  - 改为主 Agent 模式切换配置
  - 在 query.py 中集成模式判断

步骤 5: 更新 agents/team.py
  - 工具定义从全局注册表过滤
  - 其余保持不变

步骤 6: 更新 tools/AgentTool.py 和 tools/__init__.py
  - 支持所有 4 种模式的路由
  - 工具注册表更新

步骤 7: 更新文档
  - 项目详解-v2.md 的第四章重写
  - 更新架构图
```

### 2.10 功能对照表

| 功能 | cc 实现 | 当前项目（修正后） | 简化说明 |
|------|--------|------------------|---------|
| Simple SubAgent | 独立上下文 + 5阶段 | 独立上下文 + runner.run_agent() | 简化为单函数调用 |
| Fork SubAgent | 字节级前缀继承 + async | 完整消息传递 + async | 无 Prompt Cache，传完整消息 |
| Coordinator | 主 Agent 模式切换 | 同 | 对齐 cc |
| Swarm Team | Tmux/iTerm2/InProcess | 线程 + MessageBus | 简化后端 |
| 4 种内置类型 | 声明式配置 + feature gate | 声明式配置 | 去掉 feature gate |
| 工具过滤 | 4 层管道 | 1 层声明式 + disallowedTools | 简化层级 |
| 异步结果通知 | task-notification XML | AgentTaskQueue → 消息注入 | 对齐格式 |
| 递归防护 | querySource + 消息扫描 | 工具排除 + depth 计数 | 简化 |
| 上下文隔离 | createSubagentContext deny-by-default | 独立消息列表 | 天然隔离 |
| 自定义 Agent | .claude/agents/*.md | 暂不实现 | 后续迭代 |
