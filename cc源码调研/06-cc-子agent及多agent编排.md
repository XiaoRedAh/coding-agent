# Claude Code 子Agent与多Agent编排：深度调研报告

---

## 目录

1. [概述：子Agent与多Agent编排的含义与动机](#1-概述)
2. [Claude Code 的设计亮点与创新点](#2-设计亮点)
3. [模块深度解析](#3-模块深度解析)
   - 3.1 [AgentTool 核心架构](#31-agenttool-核心架构)
   - 3.2 [子Agent模式（同步/异步）](#32-子agent模式)
   - 3.3 [Fork 模式：缓存安全的并行执行](#33-fork-模式)
   - 3.4 [Coordinator 模式：协调者-工作者架构](#34-coordinator-模式)
   - 3.5 [Swarm 团队模式](#35-swarm-团队模式)
   - 3.6 [内置智能体详解](#36-内置智能体详解)
   - 3.7 [自定义智能体系统](#37-自定义智能体系统)
   - 3.8 [工具隔离与安全体系](#38-工具隔离与安全体系)
   - 3.9 [子Agent生命周期管理](#39-子agent生命周期管理)
4. [模块对比分析](#4-模块对比分析)
5. [Agent 如何选择调度方式](#5-选择决策)
6. [总结速记表](#6-总结速记表)

---

## 1. 概述：子Agent与多Agent编排的含义与动机

### 1.1 什么是子Agent？

**子Agent（Subagent）** 是指由一个主Agent（父Agent）在执行过程中动态创建并委派任务的独立Agent实例。子Agent拥有自己独立的系统提示、工具集、对话上下文和生命周期，它代表了AI系统中"分治策略"的工程实现。

打个比方：主Agent就像一位项目经理，当面对一个复杂任务时，它不是事事亲力亲为，而是将不同子任务分配给专门的团队成员（子Agent），每个团队成员在自己擅长的领域独立工作，完成后向项目经理汇报结果。

### 1.2 什么是多Agent编排？

**多Agent编排（Multi-Agent Orchestration）** 是指在一个系统中协调多个Agent实例协同工作的机制，包括：
- 任务的分解与分配
- Agent之间的通信与信息共享
- 并行执行的调度与冲突管理
- 结果的聚合与综合
- 故障的检测与恢复

### 1.3 为什么需要子Agent和多Agent编排？

| 动机 | 说明 | 具体场景 |
|------|------|----------|
| **任务复杂度** | 单个Agent的上下文窗口和能力有限，无法一次性处理大型工程任务 | 大型代码重构涉及数十个文件 |
| **专业分工** | 不同任务需要不同的工具集、模型和行为约束 | 搜索用轻量模型、实现用强推理模型 |
| **并行加速** | 独立的子任务可以并行执行，大幅缩短总时长 | 同时调查API层、数据库层、前端层 |
| **安全隔离** | 只读任务不应该拥有写入权限，验证任务不应该能修改代码 | Explore Agent禁止修改文件 |
| **成本优化** | 简单任务用便宜模型，节省token消耗 | 搜索任务用Haiku，规划任务用Sonnet |
| **故障隔离** | 一个子Agent的失败不应该影响其他Agent或主Agent | 某个Worker崩溃不连锁影响 |

### 1.4 必要性的工程论证

在软件工程的实际场景中，一个"为用户认证模块添加OAuth2支持"的需求，至少涉及：

```
需求分析 → 代码调研（API/数据库/前端） → 方案设计 → 
数据库迁移 → 后端API实现 → 前端组件开发 → 集成测试 → 验证
```

如果全部由单个Agent串行完成：
- **上下文爆炸**：所有中间结果累积在一个对话中，token消耗急剧增加
- **注意力分散**：模型需要在海量上下文中找到相关信息
- **无法并行**：调研三个层面必须串行执行
- **无法隔离**：一次错误的修改可能污染后续所有步骤

多Agent架构通过分治、隔离和并行，将这个线性流程变成高效的并行流水线。

---

## 2. Claude Code 的设计亮点与创新点

### 2.1 三种递进的多Agent模式

Claude Code 提供了三种复杂度递增的多Agent模式，覆盖了从简单到复杂的全部场景：

```
子Agent模式（最简单）→ Fork模式（缓存优化）→ Coordinator模式（企业级编排）→ Swarm团队（对等协作）
```

这种递进设计意味着用户可以按需选择合适的复杂度——简单任务不需要启动复杂的编排机制。

### 2.2 Fork模式的Prompt Cache共享（核心创新）

**这是Claude Code最精巧的架构创新。** Fork模式通过字节级继承父Agent的完整请求前缀（系统提示+工具定义+对话历史），让多个并行子Agent共享Anthropic API的Prompt Cache，从而在继承完整上下文的同时节省60%+的token成本。

其核心思想类比于Unix的Copy-on-Write：不真正复制数据，而是共享同一份数据的引用，只在发生修改时才创建副本。

### 2.3 四层工具过滤的纵深防御

Claude Code的安全体系不依赖单一防线，而是通过四层独立的过滤机制实现纵深防御：
1. 全局禁止列表（所有子Agent）
2. 自定义Agent额外限制
3. 异步Agent白名单
4. Agent自身的disallowedTools

即使某一层有漏洞，其他层仍能拦截危险操作。

### 2.4 对抗性验证Agent

Verification Agent借鉴了安全领域的**红队测试**理念——它的目标不是确认代码能工作，而是尽可能证明代码不能工作。这种"左手打右手"的自我对抗机制，在LLM系统中是一个独特的设计。

### 2.5 Coordinator的"理解不可委派"原则

Coordinator模式强制协调者必须消化所有Worker的研究发现后再编写实施规格，不允许简单转发。这个原则解决了LLM多Agent系统中信息衰减的核心问题。

### 2.6 声明式自定义Agent

通过Markdown frontmatter定义Agent，降低了创建门槛，让非程序员也能设计专用Agent。

### 2.7 上下文隔离的"默认安全"设计

`createSubagentContext()` 将所有可变状态默认设为隔离，开发者必须显式opt-in共享。这种"deny by default"设计确保新增的子Agent功能天生安全。

---

## 3. 模块深度解析

### 3.1 AgentTool 核心架构

#### 设计动机

AgentTool是Claude Code多Agent系统的基石——它是所有子Agent创建和管理的统一入口。设计的核心目标是将"决定做什么"（路由）、"怎么做"（执行）和"怎么做得更高效"（Fork缓存策略）分离开来。

#### 架构概览

```
AgentTool 架构组成：
┌──────────────────────────────────────────────┐
│ 工具主入口 (AgentTool.tsx)                      │
│  - 输入schema解析                               │
│  - 路由策略（同步/异步/Fork/远程）                  │
│  - 类型解析                                     │
├──────────────────────────────────────────────┤
│ 智能体运行器 (agentRunner)                       │
│  - 生命周期管理                                   │
│  - 上下文构建                                    │
│  - MCP初始化                                    │
├──────────────────────────────────────────────┤
│ Fork 模式实现 (forkSubagent)                     │
│  - 缓存安全的消息前缀构建                           │
│  - 递归防护                                     │
├──────────────────────────────────────────────┤
│ 内置智能体注册表 (built-in/)                      │
│  - Explore / Plan / General / Verification     │
├──────────────────────────────────────────────┤
│ 自定义智能体加载 (agents/*.md)                    │
│  - Markdown frontmatter 解析                    │
├──────────────────────────────────────────────┤
│ 工具函数集 (agentToolUtils)                      │
│  - 工具过滤、结果格式化                             │
└──────────────────────────────────────────────┘
```

#### AgentTool 的输入参数

```typescript
{
  description: string,        // 3-5 词任务描述（必填）
  prompt: string,             // 完整任务指令（必填）
  subagent_type?: string,     // 专用Agent类型
  model?: 'sonnet' | 'opus' | 'haiku',  // 模型覆盖
  run_in_background?: boolean, // 异步执行
  name?: string,              // 可寻址名称
  isolation?: 'worktree' | 'remote'  // 隔离模式
}
```

**关键设计：prompt���须自包含**——Worker无法看到父Agent的对话历史。这意味着每个prompt都需要包含文件路径、行号、具体的修改内容等完成任务所需的全部信息。

#### 路由决策逻辑

AgentTool的路由决策是整个系统的"交通枢纽"：

```typescript
// 类型解析的核心逻辑
const effectiveType = subagent_type
  ?? (isForkSubagentEnabled() ? undefined : GENERAL_PURPOSE_AGENT.agentType);
const isForkPath = effectiveType === undefined;
```

决策树：
```
subagent_type 明确指定？
  ├─ 是 → 使用指定类型（显式指定优先）
  └─ 否 → Fork实验开启？
        ├─ 是 → Fork路径（继承完整上下文）
        └─ 否 → 默认 general-purpose
```

#### BaseAgentDefinition 类型体系

所有Agent定义基于统一的类型结构，按功能维度归为四大类：

| 维度 | 字段 | 说明 |
|------|------|------|
| **身份与描述** | agentType, whenToUse, color | Agent的标识和何时使用 |
| **工具与能力** | allowedTools, disallowedTools, skills, mcpServers | Agent能做什么 |
| **执行控制** | model, effort, maxTurns, permissionMode, background | Agent怎么执行 |
| **上下文管理** | omitClaudeMd, isolationMode, hooks, memory | Agent的上下文配置 |

三种具体实现：
- **BuiltInAgentDefinition**：内置Agent，通过`getSystemPrompt()`动态生成提示
- **CustomAgentDefinition**：用户通过Markdown定义
- **PluginAgentDefinition**：插件提供，携带版本信息

### 3.2 子Agent模式（同步/异步）

#### 设计动机

这是最基础的多Agent模式——父Agent通过AgentTool派生子Agent执行独立任务，适合单个明确的子任务。

#### 设计思路

子Agent模式的核心设计理念是**"无上下文"启动**：子Agent从零开始，不继承父Agent的对话历史。这一设计的原因有三：

1. **隔离性**：不被父Agent对话中无关信息干扰
2. **成本控制**：避免传输完整对话历史的token开销
3. **并行安全**：多个子Agent并行时不会因共享可变历史产生竞态条件

#### 完整工作流程

当模型发出一次Agent工具调用时，系统经历5个阶段：

**阶段1：类型解析**
```
模型调用 Agent({description, prompt, subagent_type})
    ↓
从 agentDefinitions.activeAgents 查找匹配的 AgentDefinition
    ↓
找不到时区分"不存在"和"被权限拒绝"（给出不同错误提示）
```

**阶段2：工具池组装**
```typescript
// 子Agent的工具池独立于父级构建
const workerPermissionContext = {
  ...appState.toolPermissionContext,
  mode: selectedAgent.permissionMode ?? 'acceptEdits'  // 默认自动接受编辑
};
const workerTools = assembleToolPool(workerPermissionContext, appState.mcp.tools);
```

注意`permissionMode`默认是`'acceptEdits'`——子Agent可以自动执行编辑操作，无需逐个确认，因为它已经由父Agent委托了明确任务。

**阶段3：系统提示构建**
- 普通路径：`getSystemPrompt()` + `enhanceSystemPromptWithEnvDetails()` + 用户prompt作为独立user消息
- Fork路径：直接使用父级已渲染的系统提示字节（不重新计算）

**阶段4：上下文创建**
通过`createSubagentContext()`创建隔离的执行上下文（详见3.8节）

**阶段5：执行分支**
```typescript
const shouldRunAsync = (
  run_in_background === true ||
  selectedAgent.background === true ||
  isCoordinator ||    // 协调器模式下所有Agent都异步
  forceAsync ||       // fork实验开启时所有Agent都异步
  assistantForceAsync
) && !isBackgroundTasksDisabled;
```

#### 同步 vs 异步执行

| 维度 | 同步模式 | 异步模式 |
|------|----------|----------|
| **执行方式** | 进程内直接执行 | LocalAgentTask后台运行 |
| **父Agent行为** | 阻塞等待 | 立即收到taskId，继续其他工作 |
| **结果传递** | 直接作为tool_result嵌入 | 通过`<task-notification>` XML投递 |
| **适用场景** | 快速搜索/探索 | 长时间运行的实现/验证任务 |
| **自动转换** | 超过120秒自动转后台 | - |

#### 异步结果通知格式

```xml
<task-notification>
  <task-id>ae9a65ee22594487c</task-id>
  <status>completed</status>
  <summary>Agent "research query engine" completed</summary>
  <result>... 详细结果内容 ...</result>
  <usage>
    <total_tokens>71330</total_tokens>
    <tool_uses>21</tool_uses>
    <duration_ms>81748</duration_ms>
  </usage>
</task-notification>
```

#### 示例模拟

**场景**：主Agent需要查找项目中所有TODO注释

```
主Agent (运行中)
   │
   ├── 决策：这是只读搜索任务，使用Explore子Agent
   │
   ├── 调用 AgentTool({
   │     description: "search TODOs",
   │     prompt: "搜索项目中所有TODO注释，按文件分类汇总",
   │     subagent_type: "explore"
   │   })
   │
   ├── [阶段1] 类型解析 → 找到 Explore Agent 定义
   ├── [阶段2] 工具池：Read, Grep, Glob, Bash（排除Edit/Write）
   ├── [阶段3] 系统提示：只读约束 + 环境信息
   ├── [阶段4] 创建隔离上下文
   ├── [阶段5] 同步执行（搜索通常很快）
   │
   │   Explore子Agent开始工作：
   │   ├── Grep("TODO", recursive=true)
   │   ├── Read(匹配到的文件)
   │   └── 生成分类汇总报告
   │
   ├── 收到结果（作为tool_result嵌入对话）
   └── 主Agent根据结果决定下一步
```

#### 是否阻塞主Agent？

- **同步模式**：**是**，主Agent阻塞等待子Agent完成。适合快速任务（<120秒）
- **异步模式**：**否**，主Agent立即继续。结果通过`<task-notification>`在下一轮对话中到达
- **自动后台化**：同步任务超过120秒自动转为异步，防止长时间阻塞

### 3.3 Fork 模式：缓存安全的并行执行

#### 设计动机

Fork模式解决的是一个经济学问题：**如何让多个并行子Agent共享父Agent的上下文而不产生巨额token开销？**

普通子Agent每次都是"冷启动"——有自己的系统提示和空的消息历史，与父级的请求前缀完全不同，无法共享Anthropic API的Prompt Cache。

Fork模式的灵感来自Unix的`fork()`系统调用：

| 类比维度 | Unix fork() | Claude Code Fork 模式 |
|----------|-------------|----------------------|
| 触发时机 | 父进程调用fork() | 主Agent调用Agent工具 |
| 继承内容 | 内存映像、文件描述符 | 系统提示、工具定义、对话历史 |
| 分叉后关系 | 父子进程独立运行 | 主/子Agent并行运行 |
| 资源节省 | Copy-on-Write内存共享 | Prompt Cache token共享 |

#### 设计思路——字节级继承

Fork模式的核心原则是**字节级继承**：子Agent必须与父Agent共享完全相同的API请求前缀，才能命中Prompt Cache。

```
为什么是"字节级"而非"语义级"？

Prompt Cache通过字节前缀匹配来复用已处理的token。
即使两段文本"语���完全相同"，只要有任何一个字符的差异
（哪怕是一个多余的空格），缓存就不会命中。

类比：就像HTTP缓存中的ETag，比对的是内容的精确哈希值。
```

#### CacheSafeParams——五维缓存契约

```typescript
export type CacheSafeParams = {
  systemPrompt: SystemPrompt        // 系统提示必须字节一致
  userContext: { [k: string]: string }  // 用户上下文（CLAUDE.md等）
  systemContext: { [k: string]: string } // 系统注入的上下文
  toolUseContext: ToolUseContext     // 工具定义 + 模型选择
  forkContextMessages: Message[]    // 对话历史前缀消息
}
```

**五维度全部一致 → 缓存命中；任一维度偏离 → 完整重新处理**

#### buildForkedMessages——缓存共享的核心

这个函数是Fork机制的精华所在：

```
步骤1: 保留完整的父assistant消息
       （所有tool_use、thinking、text，分配新UUID）
       
步骤2: 收集所有tool_use块

步骤3: 为每个tool_use生成统一的占位符tool_result
       → "Fork started -- processing in background"（固定字符串！）

步骤4: 构建单条user消息 = 占位符结果 + 子任务指令

结果结构：
[...history, assistant(all_tool_uses), user(placeholder_results..., directive)]
```

**关键巧妙之处**：
- 占位符是所有Fork子Agent**共享的固定字符串**
- 只有最后的指令文本不同
- 这最大化了缓存命中面积

#### 缓存效率分析

```
假设场景：
- 父对话积累了50,000 token历史
- 父assistant消息包含3个tool_use（约2,000 token）
- 系统提示+工具定义约10,000 token

不使用Fork模式（每个子Agent独立构建）：
  每个子Agent：50,000 + 2,000 + 10,000 = 62,000 token
  3个子Agent总计：186,000 input token

使用Fork模式：
  父请求：62,000 token（首次，建立缓存）
  3个子Agent各自的新增token：仅指令文本（约200 token/个）
  3个子Agent总计：600 新增 + 62,000 缓存命中
  总计：62,600 input token

节省比例：(186,000 - 62,600) / 186,000 ≈ 66%
```

#### Fork路径的工具定义保持

```typescript
// Fork路径通过useExactTools标志确保工具定义不变
// 直接使用父工具池而非重新解析Agent工具
```

当Fork模式激活时，直接使用父工具池，保持工具定义的字节一致性。

#### 递归Fork防护

Fork子Agent保留了Agent工具（为了缓存一致性——移除会改变工具定义的字节），但在运行时通过**双重检测**阻止递归：

```typescript
// 第一道：querySource检查（主防线，抗消息压缩）
if (toolUseContext.options.querySource === 
    `agent:builtin:${FORK_AGENT.agentType}`)
// 第二道：消息扫描（后备，检测FORK_BOILERPLATE_TAG）
|| isInForkChild(toolUseContext.messages)
```

**为什么需要两道？**
- `querySource`设置在context的options上，不受自动压缩影响——首选方案
- 消息扫描是后备方案，覆盖querySource未被正确传递的边缘情况

**为什么禁止递归Fork？**
- 资源爆炸：每层Fork创建新连接和工具实例，指数级增长
- 缓存失效：每层Fork的上下文都略有不同，命中率急剧下降
- 调试困难：嵌套结构使错误追踪极其复杂

#### Fork Agent的特殊定义

```typescript
export const FORK_AGENT = {
  agentType: 'fork',
  tools: ['*'],             // 全部工具，保持与父级缓存一致
  maxTurns: 200,
  model: 'inherit',         // 继承父级模型
  permissionMode: 'bubble', // 权限请求冒泡到父级终端
  getSystemPrompt: () => '', // 未使用——直接使用父级已渲染的系统提示
}
```

- `permissionMode: 'bubble'` 是独特设计——权限请求"冒泡"到父级终端，因为Fork子级是"父级的延伸"
- `getSystemPrompt: () => ''` 是**故意设计**——如果代码路径错误调用了它，空字符串会导致明显异常，而不是微妙的缓存失效

#### 示例模拟

```
主Agent处理用户请求："分析这个项目的代码质量"
   │
   ├── 主Agent决定并行调查三个方面
   │
   ├── 当前对话已有50K token的历史上下文
   │
   ├── 调用AgentTool({prompt: "搜索所有TODO注释"})  ── Fork A
   ├── 调用AgentTool({prompt: "分析测试覆盖率"})     ── Fork B  
   ├── 调用AgentTool({prompt: "检查代码复杂度"})     ── Fork C
   │
   │   系统构建Fork消息：
   │   ┌─────────────────────────────────────────┐
   │   │ [共享前缀 - 缓存命中区]                      │
   │   │  系统提示(10K) + 历史消息(50K)               │
   │   │  + 父assistant消息(含3个tool_use)            │
   │   │  + user消息(3个占位符tool_result)             │
   │   ├─────────────────────────────────────────┤
   │   │ Fork A: directive="搜索TODO..."  (200 token) │
   │   │ Fork B: directive="分析覆盖率..." (350 token) │  
   │   │ Fork C: directive="检查复杂度..." (180 token) │
   │   └─────────────────────────────────────────┘
   │
   │   Fork A: 62,000(缓存) + 200(新增) = 62,200 token
   │   Fork B: 62,000(缓存) + 350(新增) = 62,350 token
   │   Fork C: 62,000(缓存) + 180(新增) = 62,180 token
   │
   │   所有Fork并行异步执行，通过<task-notification>返回结果
   │
   └── 主Agent不被阻塞，可以继续处理
```

#### Agent系统架构（Fork模式激活时）

```
                    ┌──────────────────┐
                    │    Anthropic API │
                    │   Prompt Cache   │
                    │  ┌────────────┐  │
                    │  │ 缓存前缀    │  │ ← 所有Fork共享
                    │  │ (62K token) │  │
                    │  └────────────┘  │
                    └──────┬───────────┘
                           │
           ┌───────────────┼───────────────┐
           │               │               │
    ┌──────┴──────┐ ┌──────┴──────┐ ┌──────┴──────┐
    │  Fork A     │ │  Fork B     │ │  Fork C     │
    │ 独立上下文   │ │ 独立上下文   │ │ 独立上下文   │
    │ 独立工具池   │ │ 独立工具池   │ │ 独立工具池   │
    │ 异步执行     │ │ 异步执行     │ │ 异步执行     │
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                           │ <task-notification>
                    ┌──────┴──────┐
                    │  主Agent    │ ← 不被阻塞
                    │ (继续运行)  │
                    └─────────────┘
```

### 3.4 Coordinator 模式：协调者-工作者架构

#### 设计动机

当任务需要**有依赖关系的多步骤协作**时，Fork模式的"对等并行"不够用了。需要一个中央协调者来：
- 分析任务结构和依赖关系
- 按阶段分配任务给Worker
- 综合各Worker的研究发现
- 控制并发策略（防止文件冲突）
- 处理Worker失败和部分完成

这就像建筑工地：项目经理（Coordinator）不需要亲自砌砖，但需要知道哪些任务可以并行、哪些有依赖。

#### 与Fork模式的核心区别

| 维度 | Coordinator 模式 | Fork 模式 |
|------|----------------|----------|
| 架构 | 中心化（协调者-工作者） | 去中心化（对等并行） |
| 上下文 | Worker只看到分配的任务 | 继承完整父上下文 |
| 通信 | 协调者中转 + Scratchpad | 无直接通信 |
| 缓存效率 | 不共享缓存前缀 | 字节级共享 |
| 适用场景 | 需要协调的复杂多步骤 | 独立的并行调查 |

#### 双重门控机制

```
编译时（Feature Gate）：
  代码是否包含Coordinator功能？
    ├─ 否 → 相关代码不编译进二进制
    └─ 是 → 继续

运行时（环境变量）：
  CLAUDE_CODE_COORDINATOR_MODE 是否设置？
    ├─ 否 → 使用普通模式（可能激活Fork）
    └─ 是 → Coordinator模式激活
```

**设计洞察**：Feature Gate是编译时优化（减小二进制体积），环境变量是运行时控制（最小权限原则）。

#### 互斥关系

```
isCoordinatorMode? ─── Yes ──→ Coordinator模式（禁用Fork）
        │
       No
        │
isForkModeEnabled? ─── Yes ──→ Fork模式
        │
       No ──→ 普通模式（同步子Agent）
```

Coordinator模式优先级高于Fork，因为Coordinator已经拥有自己的任务委派模型。

#### 工具集的权力边界

**协调者的工具（管理权）**：
| 工具 | 用途 |
|------|------|
| Agent | 创建并分配任务给Worker |
| TaskStop | 停止方向错误的Worker |
| SendMessage | 向Worker发送消息 |
| Structured Output | 输出结构化结果 |

**关键约束：协调者没有Read/Write/Edit/Bash等执行工具，不能直接修改代码。**

**Worker的工具（执行权）**：
| 模式 | 工具集 |
|------|--------|
| Simple | Bash, Read, Edit |
| Full | Read, Write, Edit, Bash, Grep, Glob, WebSearch, WebFetch, NotebookEdit, Skill, MCP等 |

**Worker默认使用`acceptEdits`权限模式**——自动接受编辑，不需要逐个确认。

#### 四阶段标准工作流

```
阶段1: Research（研究）
  ├── Worker们并行调查代码库
  ├── 将发现写入Scratchpad
  └── 只读操作，自由并行

阶段2: Synthesis（综合）
  ├── Coordinator读取所有Scratchpad文件
  ├── 理解并综合所有发现
  ├── 编写包含具体文件路径和修改说明的实施规格
  └── 必须由Coordinator串行完成

阶段3: Implementation（实施）
  ├── Worker按规格修改代码
  ├── 同一文件集一次一个（防止冲突）
  └── 不同文件可并行

阶段4: Verification（验证）
  ├── Worker验证修改的正确性
  ├── 运行测试、检查类型错误
  └── 可与不同区域的实施并行
```

#### Scratchpad协作空间

Scratchpad是一个跨Worker共享的临时文件空间：
- **路径**：`/tmp/claude-{uid}/{sanitized-cwd}/{sessionId}/scratchpad/`
- **无权限提示**：Worker可自由读写
- **持久化知识**：一个Worker的发现可被其他Worker读取
- **会话隔离**：每个会话独立
- **结构自由**：不规定文件结构

**为什么不让Worker直接通信？**
消息传递是瞬时的——消费后就消失。Scratchpad是持久的，可被反复读取，还支持增量构建。

#### 消息传递机制（SendMessage）

| 寻址模式 | 格式 | 使用场景 |
|----------|------|----------|
| 点对点 | `to: "agent-name"` | 向指定Worker发送指令 |
| 广播 | `to: "*"` | 向所有Worker发布信息 |
| UDS | `to: "uds:<socket-path>"` | 跨进程通信 |
| Bridge | `to: "bridge:<session-id>"` | 跨会话/远程通信 |

**智能路由**：向运行中的Worker发消息→排队等下一轮；向已停止的Worker发消息→**自动恢复**该Worker。

#### 关键设计原则

**1. "Never write 'based on your findings'"**
```
// 反模式——懒惰委托
Agent({ prompt: "Based on your findings, fix the auth bug" })

// 正确——综合后的具体指令  
Agent({ prompt: "Fix the null pointer in src/auth/validate.ts:42.
  The user field on Session is undefined when sessions expire but
  the token remains cached. Add a null check before user.id access." })
```

**2. Continue vs Spawn 决策表**

| 场景 | 决策 | 原因 |
|------|------|------|
| 研究了需要编辑的文件 | Continue | Worker已有文件上下文 |
| 研究范围广但实施范围窄 | Spawn | 避免探索噪声 |
| 上次方法完全错误 | **Spawn** | 错误上下文会锚定重试思路（锚定效应） |
| 验证其他Worker刚写的代码 | Spawn | 验证者应以新鲜视角审视 |

#### 故障恢复

| 失败类型 | Coordinator的应对策略 |
|----------|----------------------|
| 工具执行失败 | 分析原因，重试或调整策略 |
| maxTurns耗尽 | 评估已完成部分，决定是否重新分配 |
| MCP连接断开 | 降级到不依赖该工具的策略 |
| 上下文过长 | 压缩或拆分为更小的子任务 |

#### 完整示例模拟

**场景**："为Express.js应用添加通知系统，支持邮件和站内信"

```
Phase 1: Research（并行）
  ┌─ Worker "api-researcher"
  │    任务 → "调查Express.js路由结构和中间件链"
  │    输出 → /scratchpad/api-analysis.md
  │
  ├─ Worker "db-researcher"  
  │    任务 → "调查数据库schema���ORM"
  │    输出 → /scratchpad/db-analysis.md
  │
  └─ Worker "frontend-researcher"
       任务 → "调查前端框架和组件结构"
       输出 → /scratchpad/frontend-analysis.md

Phase 2: Synthesis（Coordinator串行）
  Coordinator:
    1. 读取三个scratchpad文件
    2. 理解整体架构
    3. 编写实施规格到 /scratchpad/implementation-spec.md
       - 数据库：新增Notification和NotificationPreference模型
       - API：新增5个端点
       - 前端：修改SettingsPage

Phase 3: Implementation（部分并行）
  ┌─ Worker "db-implementer" ──── prisma/schema.prisma
  │   （与service-implementer并行，操作不同文件）
  ├─ Worker "service-implementer" ── src/services/, src/routes/
  │
  └─ Worker "frontend-implementer" ── 等待后端完成后开始
       src/components/NotificationSettings.tsx

Phase 4: Verification
  └─ Worker "verifier"
       检查迁移、API、前端、错误处理、默认值
```

#### Agent系统架构（Coordinator模式）

```
                    ┌──────────────────┐
                    │     用户         │
                    └────────┬─────────┘
                             │
                    ┌────────┴─────────┐
                    │  Coordinator     │
                    │  (协调者)         │
                    │  工具：Agent,     │
                    │  SendMessage,    │
                    │  TaskStop        │
                    │  无执行工具       │
                    └────────┬─────────┘
                             │
          ┌──────────────────┼──────────────────┐
          │                  │                  │
   ┌──────┴──────┐   ┌──────┴──────┐   ┌──────┴──────┐
   │  Worker A   │   │  Worker B   │   │  Worker C   │
   │  (研究)     │   │  (实现)     │   │  (验证)     │
   │  Read,Grep  │   │  Edit,Write │   │  Bash,Read  │
   │  Glob,Bash  │   │  Bash       │   │  Grep       │
   └──────┬──────┘   └──────┬──────┘   └──────┬──────┘
          │                  │                  │
          └──────────────────┼──────────────────┘
                             │
                    ┌────────┴─────────┐
                    │   Scratchpad     │
                    │  (共享文件空间)    │
                    └──────────────────┘
```

### 3.5 Swarm 团队模式

#### 设计动机

Swarm模式在Coordinator的基础上更进一步，支持Agent之间的**对等通信**（而非仅通过协调者中转）。Agent通过命名信箱（Mailbox）直接互相通信。

#### 三种执行后端

| 后端 | 实现方式 | 特点 | 选择条件 |
|------|----------|------|----------|
| **Tmux** | 创建/管理tmux分屏面板 | 支持隐藏/显示，最常用 | 已在tmux内 |
| **iTerm2** | 原生iTerm2面板 | macOS原生体验 | 在iTerm2内 + it2 CLI可用 |
| **InProcess** | 同一Node.js进程内运行 | AsyncLocalStorage隔离 | 非交互式环境（CI/CD） |

#### 统一接口

```typescript
interface TeammateExecutor {
  spawn(config): Promise<void>              // 创建队友
  sendMessage(agentId, message): Promise<void> // 发送消息
  terminate(agentId, reason): Promise<void> // 优雅关闭
  kill(agentId): Promise<void>              // 立即终止
  isActive(agentId): boolean                // 检查存活
}
```

#### InProcess后端的上下文隔离

```
Leader Agent (主进程上下文)
      │
      └── AsyncLocalStorage 上下文隔离层
           │
           ├── Worker 1 (独立TeammateIdentity + AbortController)
           │       │
           ├── Worker 2 (独立TeammateIdentity + AbortController)
           │       │
           └── 共享：API客户端、MCP连接（无状态，线程安全）
```

**为什么API客户端和MCP连接可以共享？** 它们本质上是无状态的连接复用，HTTP客户端和WebSocket连接是线程安全的。

#### 与Coordinator模式的区别

| 维度 | Coordinator | Swarm |
|------|-------------|-------|
| 通信拓扑 | 星型（所有通信经协调者） | 网状（Agent间对等通信） |
| Worker间通信 | 禁止直接通信 | 通过信箱直接通信 |
| 协调方式 | 中央协调者决策 | Agent自主协调 |
| 共享资源 | Scratchpad | Scratchpad + 信箱 |

### 3.6 内置智能体详解

Claude Code预置了四种专家Agent，覆盖软件工程的核心工作流：

```
只读层                    读写层
┌────────────────┐      ┌────────────────┐
│ Explore (搜索)  │      │ General (执行)  │
│ Plan (规划)     │      │ Verification   │
│                │      │ (验证)          │
└────────────────┘      └────────────────┘
```

#### Explore Agent（只读代码探索专家）

**设计动机**：提供一个高速、低成本、安全的代码搜索工具。

| 配置项 | 设置 | 设计原因 |
|--------|------|----------|
| **disallowedTools** | Agent, FileEdit, FileWrite, NotebookEdit | 双重锁：提示层+工具层确保只读 |
| **model** | haiku（外部用户）/ inherit（内部） | 搜索不需要强推理，速度更重要 |
| **omitClaudeMd** | true | 不需要commit/PR规范，节省5-15 Gtok/周 |
| **系统提示** | 严格只读约束 + 并行搜索优化 | 即使模型"幻觉"也被物理阻止 |

**"双重锁"设计**：系统提示中声明禁止操作列表（软约束）+ disallowedTools物理禁止（硬约束），即使模型想通过Bash间接写文件也不行。

**最适合场景**：代码考古、依赖分析、架构探索、知识检索。

#### Plan Agent（结构化规划智能体）

| 配置项 | 设置 | 设计原因 |
|--------|------|----------|
| **工具集** | 复用Explore的工具集 | 与Explore保持一致 |
| **model** | inherit | 规划需要更强推理能力 |
| **omitClaudeMd** | true | 规划关注"做什么"而非"怎么做" |
| **输出要求** | 结构化+关键文件列表 | 确保结果可操作 |

**输出结构**：

| 要素 | 对后续阶段的价值 |
|------|----------------|
| 问题分析 | 确保实现方向正确 |
| 实施步骤 | General Agent按步骤执行 |
| 关键文件列表（3-5个） | 减少后续搜索开销 |
| 风险评估 | Verification Agent的检查重点 |
| 依赖关系 | 决定是否可并行执行 |

**为什么Plan也省略CLAUDE.md？** Plan省略的原因是"不应该"看到——如果Plan Agent看到"使用camelCase"这样的规则，它可能在规划阶段就纠结命名细节，而这些应该在实现阶段处理。

#### General Purpose Agent（通用执行智能体）

| 配置项 | 设置 | 设计原因 |
|--------|------|----------|
| **tools** | `['*']`（全部） | 最大灵活性 |
| **omitClaudeMd** | false | 可能需要遵守commit规范 |
| **系统提示** | 最小化——"完成任务，简洁汇报" | 不做预设限制 |

**设计哲学："默��信任，边界后移"**——不做工具层面的预设限制，依赖全局安全层确保安全。

#### Verification Agent（对抗性验证智能体）

| 配置项 | 设置 | 设计原因 |
|--------|------|----------|
| **color** | 红色 | 强调对抗性质 |
| **background** | 始终后台运行 | 不阻塞主线程 |
| **禁止修改** | 不能修改项目文件 | 只验证不改代码 |
| **目标** | 尽可能破坏代码 | 红队测试理念 |

**对抗性设计**防范两种失败模式：

1. **验证回避**：模型倾向于找借口不运行测试（"看起来正确"/"环境复杂"）→ 系统提示列出常见借口，要求必须实际执行验证
2. **表面正确性陷阱**：代码通过happy path但在边界条件下崩溃 → 要求特别关注"不明显"的失败模式

**为什么后台运行？** 三个原因：
- 验证"可以等待"，用户只需最终结果
- 释放主线程，用户可继续交互
- 强制独立工作，不会因等待用户输入中断

### 3.7 自定义智能体系统

#### 设计动机

让用户能够通过简单的声明式配置创建专用Agent，降低门槛。

#### Markdown Frontmatter 格式

```yaml
---
name: security-auditor
description: 分析代码中的安全漏洞并生成审计报告
tools:
  - Bash
  - Read
  - Grep
  - Glob
disallowedTools:
  - Write
model: haiku
effort: high
permissionMode: default
maxTurns: 30
color: orange
background: true
memory: project
skills:
  - /commit
mcpServers:
  - slack
hooks:
  PreToolUse:
    - matcher: Bash
      command: "audit-log.sh"
---

你是一位代码安全审计专家。你的职责是：
1. 分析代码中潜在的安全漏洞
2. 检查常见攻击向量（XSS、SQL注入、CSRF等）
3. 生成结构化审计报告
4. 提供修复建议
```

#### 加载优先级

```
内置智能体（最低）
  ↓ 被覆盖
插件智能体
  ↓ 被覆盖
用户设置（~/.claude/settings.json）
  ↓ 被覆盖
项目设置（.claude/settings.json）
  ↓ 被覆盖
Flag设置（CLI启动参数）
  ↓ 被覆盖
策略设置（企业管理配置，最高优先级）
```

这意味着企业可以通过策略设置覆盖同名内置Agent，强制执行安全审查标准。

### 3.8 工具隔离与安全体系

#### 四层过滤流水线

```
所有可用工具
    │
    ▼
第一层：ALL_AGENT_DISALLOWED_TOOLS
    移除 TaskOutput/EnterPlanMode/AskUserQuestion 等
    （"元工具"，只有父级应该使用）
    │
    ▼
第二层：CUSTOM_AGENT_DISALLOWED_TOOLS
    对非内建Agent额外限制
    │
    ▼
第三层：ASYNC_AGENT_ALLOWED_TOOLS（白名单模式）
    异步Agent只允许 Read/Grep/Glob/Edit/Write/Bash/Skill 等
    │
    例外：MCP工具(mcp__*)始终放行
    例外：ExitPlanMode在plan模式下放行
    │
    ▼
第四层：Agent自身的 disallowedTools
    如 Explore 排除 FileEdit/FileWrite
    │
    ▼
最终工具集
```

**纵深防御的精髓**：前三层是全局策略（所有Agent都受约束），第四层是类型级策略。即使有人定义了`disallowedTools: []`的Agent，仍受前三层保护。

#### 上下文隔离深度解析

`createSubagentContext()` 为每个子Agent创建隔离的`ToolUseContext`，核心原则是**"默认隔离，显式共享"**：

| 字段 | 隔离方式 | 设计原因 |
|------|----------|----------|
| **readFileState** | 克隆 | 子Agent的文件读取不"污染"父级缓存 |
| **abortController** | 新建子控制器 | 父级中断→子级中断，但反过来不会 |
| **getAppState** | 包装 | 后台Agent返回`shouldAvoidPermissionPrompts: true` |
| **setAppState** | **默认no-op** | 子Agent的状态变更不传播到父级UI |
| **setAppStateForTasks** | **始终共享** | 防止子Agent启动的后台进程成为僵尸 |
| **queryTracking** | 新chainId + depth+1 | 防止无限递归 + 链路追踪 |
| **contentReplacementState** | 克隆（非新建） | Fork子Agent需要对已知tool_use_id做相同的替换决策 |

**为什么`setAppStateForTasks`必须共享？** 子Agent可能通过Bash启动后台进程。如果注册信息到不了根store，子Agent结束时这些进程会成为僵尸进程（PPID=1，无人回收）。

### 3.9 子Agent生命周期管理

#### 状态转换图

```
[创建] ──→ [上下文构建] ──→ [运行中] ──→ [完成] ──→ [清理] ──→ [结束]
                              │    ↑
                              │    │
                         [等待工具] ←┘
                              │
                         [被中断] ──→ [清理] ──→ [结束]
                              │
                      [异步完成] ──→ [通知主Agent] ──→ [结束]
```

#### 上下文构建阶段（5步）

1. **系统提示渲染**：根据Agent定义生成系统提示
2. **工具池组装**：根据allowedTools/disallowedTools + 全局过滤
3. **MCP服务器初始化**：为Agent专属MCP建立连接
4. **Skill预加载**：加载指定技能
5. **内存注入**：如果启用memory，注入持久化记忆

#### 资源清理阶段

- 关闭Agent专属MCP连接（非专属连接由父级管理）
- 释放工具实例引用
- 结果格式化为任务通知
- 后台Agent通知排队等待主Agent下一轮处理

#### maxTurns最佳实践

| 任务类型 | 推荐maxTurns |
|----------|-------------|
| 只读搜索 | 10-15轮 |
| 探索性任务 | 15-20轮 |
| 代码生成 | 20-30轮 |
| 复杂重构 | 30-50轮 |

---

## 4. 模块对比分析

### 4.1 三种主要模式的全面对比

| 维度 | 子Agent（同步） | Fork模式 | Coordinator模式 | Swarm团队 |
|------|---------------|----------|----------------|----------|
| **架构模型** | 父-子（串行） | 去中心化并行 | 中心化协调者-工作者 | 对等网状 |
| **上下文共享** | 无（自包含prompt） | 字节级继承完整上下文 | Worker只看到分配任务 | 信箱通信 |
| **缓存效率** | 无共享（冷启动） | 极高（共享前缀） | 无共享 | 无共享 |
| **是否阻塞主Agent** | 是（同步等待） | 否（全部异步） | 否（全部异步） | 否 |
| **通信方式** | fork-return | 无直接通信 | 协调者中转 + Scratchpad | 命名信箱 |
| **任务分配** | 父Agent显式调用 | 隐式并行 | 协调者显式分配 | Agent自主协调 |
| **故障恢复** | 父Agent收到失败 | 主Agent收到通知 | 协调者重新分配 | Agent自主处理 |
| **资源开销** | 低 | 低（共享缓存） | 较高（协调者常驻） | 中等 |
| **适用场景** | 简单独立子任务 | 独立的并行搜索 | 复杂多步骤协调任务 | 并行协作任务 |
| **心智模型** | 委托一个助手 | 派出多个侦察兵 | 项目经理+工人 | 协作团队 |
| **互斥关系** | 与Fork/Coordinator兼容 | 与Coordinator互斥 | 与Fork互斥 | - |

### 4.2 内置Agent的对比

| 维度 | Explore | Plan | General Purpose | Verification |
|------|---------|------|-----------------|--------------|
| **权限级别** | 只读 | 只读 | 全部 | 只读（禁止修改项目文件） |
| **模型** | haiku | inherit | 默认子Agent模型 | inherit |
| **CLAUDE.md** | 省略 | 省略 | 保留 | 保留 |
| **运行方式** | 前台/后台 | 前台/后台 | 前台/后台 | 始终后台 |
| **设计理念** | 高速低成本搜索 | 结构化规划 | 最小约束执行 | 对抗性验证 |
| **安全策略** | 双重锁 | 工具限制 | 依赖全局安全层 | 禁止修改+红队测试 |
| **输出格式** | 搜索结果汇总 | 结构化计划+关键文件 | 任务完成报告 | 问题列表+修复建议 |

### 4.3 各模式适合的场景

| 场景 | 推荐模式 | 原因 |
|------|----------|------|
| "找到所有使用deprecated API的地方" | 子Agent（Explore） | 简单只读搜索 |
| "同时搜索3个模块的代码结构" | Fork模式 | 独立并行搜索，共享缓存 |
| "为应用添加OAuth2支持" | Coordinator | 需要多阶段协调 |
| "将单体应用拆分为微服务" | Coordinator | 复杂多步骤+文件冲突管理 |
| "快速修复一个bug" | 子Agent（General） | 简单直接的修改任务 |
| "生成项目的API文档" | 自定义Agent（后台） | 专用任务，不阻塞主流程 |
| "对PR进行安全审计" | Verification Agent | 对抗性验证 |

---

## 5. Agent 如何选择调度方式

### 5.1 模式选择的自动决策流程

Claude Code的模式选择不是由用户手动指定的，而是通过一系列条件自动决定：

```
用户发出请求
    │
    ▼
主Agent分析任务
    │
    ▼
是否启用了Coordinator模式？（环境变量）
    ├─ 是 → Coordinator模式
    │       协调者分析任务，创建Worker
    │       所有Worker异步执行
    │
    └─ 否 → 是否启用了Fork实验？（feature gate）
              ├─ 是 → 用户是否指定了subagent_type？
              │       ├─ 是 → 使用指定类型的Agent
              │       └─ 否 → Fork路径（继承完整上下文）
              │
              └─ 否 → 使用general-purpose Agent
                       同步执行（除非指定background）
```

### 5.2 同步/异步的自动决策

```typescript
const shouldRunAsync = (
  run_in_background === true ||     // 用户显式指定后台
  selectedAgent.background === true || // Agent定义为后台
  isCoordinator ||                  // Coordinator模式下全部异步
  forceAsync ||                     // Fork实验开启全部异步
  assistantForceAsync               // 助手模式强制异步
) && !isBackgroundTasksDisabled;
```

### 5.3 子Agent类型的选择

主Agent（或Coordinator）根据任务性质选择适当的子Agent类型：

| 任务性质 | 选择 | 判断依据 |
|----------|------|----------|
| 只需要搜索/阅读代码 | Explore | 只读操作，不需要修改 |
| 需要制定实施方案 | Plan | 只读+结构化输出 |
| 需要修改代码/运行命令 | General Purpose | 需要全部工具权限 |
| 需要验证修改是否正确 | Verification | 对抗性验证，后台运行 |
| 有专用自定义Agent | 自定义Agent | 匹配description/whenToUse |

---

## 6. 总结速记表

### 6.1 模式速记表

| 模式 | 一句话描述 | 何时使用 | 关键特性 | 是否阻塞 | 缓存共享 |
|------|----------|---------|---------|---------|---------|
| **子Agent（同步）** | 委托一个助手完成子任务 | 简单独立任务 | 自包含prompt，无上下文继承 | ✅ 阻塞 | ❌ |
| **子Agent（异步）** | 后台助手，完成后通知 | 长时间任务 | `<task-notification>` 通知 | ❌ 不阻塞 | ❌ |
| **Fork模式** | 共享上下文的并行侦察 | 独立并行搜索 | 字节级缓存共享，节省60%+ token | ❌ 不阻塞 | ✅ 极高 |
| **Coordinator** | 项目经理编排工人 | 复杂多步骤 | 四阶段工作流，Scratchpad | ❌ 不阻塞 | ❌ |
| **Swarm** | 对等协作团队 | 并行协作 | 信箱通信，三种后端 | ❌ 不阻塞 | ❌ |

### 6.2 内置Agent速记表

| Agent | 角色 | 权限 | 模型 | CLAUDE.md | 后台 | 核心约束 |
|-------|------|------|------|-----------|------|----------|
| **Explore** | 🔍 搜索专家 | 只读 | haiku | 省略 | 可选 | 双重锁（提示+工具） |
| **Plan** | 📋 规划专家 | 只读 | inherit | 省略 | 可选 | 结构化输出+关键文件列表 |
| **General** | 🔧 万能执行者 | 全部 | 默认 | 保留 | 可选 | 最小约束 |
| **Verification** | 🔴 红队验证 | 只读 | inherit | 保留 | **始终** | 对抗性，尝试破坏代码 |

### 6.3 安全机制速记表

| 层级 | 机制 | 作用范围 | 说明 |
|------|------|----------|------|
| **第一层** | ALL_AGENT_DISALLOWED_TOOLS | 所有子Agent | 移除元工具 |
| **第二层** | CUSTOM_AGENT_DISALLOWED_TOOLS | 自定义Agent | 额外限制非内建Agent |
| **第三层** | ASYNC_AGENT_ALLOWED_TOOLS | 异步Agent | 白名单模式（MCP例外） |
| **第四层** | Agent.disallowedTools | 特定类型 | 类型级约束 |
| **上下文** | createSubagentContext | 所有子Agent | 默认隔离，显式共享 |
| **递归防护** | querySource + 消息扫描 | Fork子Agent | 双重检测防止递归Fork |

### 6.4 关键设计原则速记表

| 原则 | 含义 | 体现 |
|------|------|------|
| **关注点分离** | 路由、执行、优化策略分离 | AgentTool架构 |
| **最小权限** | Agent只拥有完成任务所需的最小工具集 | Explore无写入权限 |
| **默认安全** | 可变状态默认隔离 | createSubagentContext |
| **纵深防御** | 四层独立过滤 | 工具过滤流水线 |
| **字节级一致** | 缓存共享要求精确匹配 | CacheSafeParams |
| **理解不可委派** | 协调者必须消化发现再指令 | "Never write based on your findings" |
| **对抗性验证** | 主动尝试证明代码不能工作 | Verification Agent |
| **双重锁** | 提示层软约束 + 工具层硬约束 | Explore的只读保证 |
| **停止-恢复** | Worker按需激活，不总在线 | SendMessage自动恢复 |
| **声明式配置** | Markdown定义Agent | 自定义Agent系统 |

---

*本报告基于Claude Code的子Agent与Fork��式（第9章）、协调器模式（第10章）以及多Agent架构（第7章）的深度分析文档编写，涵盖了从设计哲学到实现细节的完整技术栈。*