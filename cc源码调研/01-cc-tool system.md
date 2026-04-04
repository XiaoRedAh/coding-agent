# Claude Code Tool System 深度调研报告

---

## 目录

1. [AI Agent中Tool System的概念解析](#1-ai-agent中tool-system的概念解析)
2. [Claude Code Tool System设计亮点与创新点](#2-claude-code-tool-system设计亮点与创新点)
3. [深入调研：工具定义与注册机制](#3-深入调研工具定义与注册机制)
4. [深入调研：内置工具分类与解析](#4-深入调研内置工具分类与解析)
5. [深入调研：工具调用全流程](#5-深入调研工具调用全流程)
6. [重点工具深入分析](#6-重点工具深入分析)
7. [Agent系统开发的设计参考](#7-agent系统开发的设计参考)
8. [总结速记表](#8-总结速记表)

---

## 1. AI Agent中Tool System的概念解析

### 1.1 什么是Tool System？

Tool System（工具系统）是AI Agent区别于普通Chatbot的核心能力载体。**普通Chatbot只能"说"，Agent能"做"。** Tool System就是让Agent能够执行动作的基础设施——读文件、执行命令、搜索代码、调用API、与用户交互等一切操作，都通过工具系统完成。

用一个类比来理解：如果LLM是Agent的"大脑"，那Tool System就是Agent的"双手"。大脑负责思考和决策（选择哪个工具、传什么参数），双手负责执行（实际的文件I/O、Shell命令等）。

**核心动机与必要性：**

| 维度 | 没有Tool System | 有Tool System |
|------|---------------|-------------|
| 能力边界 | 只能生成文本 | 可以操作文件、执行命令、调用API |
| 信息获取 | 依赖训练数据，无法获取实时信息 | 可以读取文件、搜索网络、查询数据库 |
| 任务完成 | 只能"建议"用户操作 | 可以直接"执行"操作 |
| 反馈闭环 | 无法验证结果 | 可以执行→观察结果→调整策略 |

### 1.2 Tool System与Function Calling的关系

**Tool System本质上是Function Calling的工程化落地。** 二者的关系可以理解为：

- **Function Calling** 是LLM API层面的协议——模型可以在回复中输出结构化的函数调用请求（tool_use block），而非纯文本
- **Tool System** 是应用层面的完整架构——围绕Function Calling协议，构建了工具定义、注册、发现、权限检查、执行、结果处理、UI渲染等一整套工程体系

```
┌─────────────────────────────────────────────┐
│            Tool System (应用层)               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌───────┐ │
│  │工具定义 │ │权限检查│ │并发控制│ │UI渲染 │ │
│  └────────┘ └────────┘ └────────┘ └───────┘ │
│  ┌──────────────────────────────────────────┐│
│  │       工具注册 / 过滤 / 发现              ││
│  └──────────────────────────────────────────┘│
├─────────────────────────────────────────────┤
│        Function Calling (API协议层)          │
│  模型输出 tool_use → 应用执行 → tool_result  │
├─────────────────────────────────────────────┤
│            LLM API (基础层)                  │
└─────────────────────────────────────────────┘
```

简言之：**Function Calling是协议，Tool System是系统。** Function Calling解决的是"模型如何表达'我要调用某个函数'"的问题，Tool System解决的是"如何定义、管理、安全执行、展示这些函数"的全链路问题。

### 1.3 Tool System vs MCP vs Skill

| 维度 | Tool System | MCP (Model Context Protocol) | Skill |
|------|------------|------------------------------|-------|
| **定义** | Agent内部的工具管理框架 | 跨进程/跨语言的工具扩展协议 | 可复用的任务模板/工作流 |
| **设计理念** | 深度集成（直接访问进程内状态） | 广度扩展（协议而非SDK） | 知识复用（经验沉淀） |
| **集成方式** | 编译时/运行时直接加载 | JSON-RPC协议通信 | Prompt注入 + 工具组合 |
| **通信开销** | 零（进程内调用） | 有（需要序列化/反序列化） | 零（Prompt层面） |
| **扩展性** | 需要修改代码 | 任何语言/进程都可实现 | 通过配置文件扩展 |
| **安全边界** | 共享进程权限 | 进程隔离 | 复用已有工具的安全机制 |
| **典型场景** | 内置的文件操作、Shell执行 | 连接GitHub、Slack等外部服务 | "部署React应用"等标准流程 |

**在Claude Code中的关系：**
- **内置Tool**（如BashTool、FileReadTool）是"深度集成"的工具，直接访问进程内状态
- **MCP工具**是"广度扩展"的工具，通过JSON-RPC协议连接外部能力（如GitHub、数据库）
- **Skill**是更高级别的抽象，它本质上是一套Prompt模板，指导Agent如何组合使用多个Tool来完成复杂任务

三者在Claude Code中通过统一的`Tool<Input, Output, P>`接口共存——这是其架构的精妙之处。

---

## 2. Claude Code Tool System设计亮点与创新点

### 亮点1：统一接口 + Fail-Closed安全默认

所有工具——无论是内置工具、MCP工具还是REPL工具——都共享同一个`Tool<Input, Output, P>`泛型接口。`buildTool()`工厂函数通过对象展开合并，自动填充安全默认值：

```typescript
const TOOL_DEFAULTS = {
  isConcurrencySafe: () => false,  // 默认不可并发
  isReadOnly: () => false,         // 默认有写入副作用
  isDestructive: () => false,
  checkPermissions: () => ({ behavior: 'allow', updatedInput: input }),
  toAutoClassifierInput: () => '', // 默认不自动批准
}
```

**设计哲学：任何新工具在缺少显式配置时，都走最保守的路径。** 忘记标记`isReadOnly: true`的后果是多一个权限弹窗（烦人但安全），反过来忘记标记的后果是数据损坏（危险且隐蔽）。

### 亮点2：编译时工具裁剪（Dead Code Elimination）

通过Bun打包器的编译时宏`feature()`，内部工具在外部构建中被**物理删除**，而非运行时隐藏：

```typescript
const SleepTool = feature('PROACTIVE')
  ? require('./tools/SleepTool/SleepTool.js').SleepTool
  : null  // 编译时被求值为null，require()被死代码消除
```

这意味着逆向工程也无法恢复内部工具代码。

### 亮点3：流式并行执行（StreamingToolExecutor）

不等待模型完整输出所有tool_use blocks，一旦检测到完整的tool_use block就立即启动执行：

```
串行模式：[========API流式输出========][tool1][tool2][tool3]
流式并行：[========API流式输出========]
            [tool1] ← 立即启动
              [tool2] ← 利用流式窗口覆盖延迟
                [tool3]
          [===结果在API输出完成时已就绪===]
```

### 亮点4：缓存感知的分区排序

工具池组装时，内置工具和MCP工具分别排序后拼接（而非全局排序），确保添加/移除MCP工具只影响后缀部分，内置工具的缓存键始终稳定。

### 亮点5：工具延迟加载（ToolSearch）

不常用工具标记`shouldDefer: true`后不在初始请求中发送，模型通过`ToolSearchTool`按需发现和加载，减少system prompt体积，提高prompt cache命中率。

### 亮点6：纵深防御的BashTool安全

BashTool实现了7+层重叠安全机制：Tree-sitter AST解析、23个命名安全检查、引用内容提取、路径约束验证、sed白名单验证、沙箱隔离、多源权限规则系统。任何单层都可以失败，但攻击者需要同时绕过所有层。

### 亮点7：渲染即工具（Self-Describing Rendering）

每个工具自带6个React渲染方法，覆盖工具调用的完整生命周期。新增工具只需实现自己的`UI.tsx`，不需要修改任何全局渲染逻辑。

### 亮点8：输入感知的安全语义

`isReadOnly(input)`接收工具输入作为参数，同一工具对不同输入可以有不同的安全语义。BashTool对`ls`返回`isReadOnly: true`，对`rm`返回`false`。

---

## 3. 深入调研：工具定义与注册机制

### 3.1 工具是如何定义的？

Claude Code中所有工具的定义都遵循统一的`Tool<Input, Output, P>`泛型接口（定义在`src/Tool.ts`），这是整个系统最核心的类型。一个完整的工具需要实现**五大要素**：

```typescript
export type Tool<
  Input extends AnyObject = AnyObject,
  Output = unknown,
  P extends ToolProgressData = ToolProgressData,
> = {
  // ===== 要素一：身份标识 =====
  name: string                    // 唯一名称标识
  aliases?: string[]              // 别名（向后兼容）
  searchHint?: string             // ToolSearch关键词匹配
  maxResultSizeChars: number      // 结果最大字符数
  shouldDefer?: boolean           // 是否延迟加载

  // ===== 要素二：Schema定义 =====
  inputSchema: Input              // Zod输入Schema（双重职责：运行时验证+API通信）
  inputJSONSchema?: ToolInputJSONSchema // JSON Schema（MCP工具直接用）
  outputSchema?: z.ZodType<unknown>

  // ===== 要素三：安全与权限 =====
  isReadOnly(input): boolean      // 是否只读
  isDestructive?(input): boolean  // 是否破坏性
  isConcurrencySafe(input): boolean // 是否可并发
  isEnabled(): boolean            // 是否启用
  validateInput?(input, context): Promise<ValidationResult>
  checkPermissions(input, context): Promise<PermissionResult>

  // ===== 要素四：核心执行 =====
  call(args, context, canUseTool, parentMessage, onProgress?):
    Promise<ToolResult<Output>>
  description(input, options): Promise<string>
  prompt(options): Promise<string>

  // ===== 要素五：UI渲染 =====
  renderToolUseMessage(input, options): React.ReactNode
  renderToolResultMessage?(content, progress, options): React.ReactNode
  renderToolUseProgressMessage?(progress, options): React.ReactNode
  renderToolUseRejectedMessage?(input, options): React.ReactNode
  renderToolUseErrorMessage?(result, options): React.ReactNode
  renderGroupedToolUse?(toolUses, options): React.ReactNode | null

  // ===== 结果序列化 =====
  mapToolResultToToolResultBlockParam(content, toolUseID): ToolResultBlockParam
}
```

**各字段的作用与设计意图：**

| 字段分组 | 关键字段 | 作用 | 设计意图 |
|---------|---------|------|--------|
| 身份标识 | `name` | 唯一标识，API和权限系统都使用 | 工具的"身份证" |
| 身份标识 | `aliases` | 重命名后旧名称仍可匹配 | 向后兼容，"只增不减" |
| 身份标识 | `searchHint` | ToolSearch的关键词 | 提高延迟工具的可发现性 |
| 身份标识 | `maxResultSizeChars` | 结果超限时持久化到磁盘 | 防止上下文窗口爆炸 |
| Schema | `inputSchema` | Zod Schema → 运行时验证 + 自动转JSON Schema给API | 一份定义，双重职责 |
| 安全 | `isReadOnly(input)` | 基于输入判断是否只读 | 细粒度并发调度 |
| 安全 | `isConcurrencySafe(input)` | 基于输入判断是否可并发 | 并行性与安全性平衡 |
| 执行 | `call()` | 实际执行逻辑 | 工具的核心价值 |
| 执行 | `prompt()` | 向system prompt注入工具使用指南 | 每个工具可以"教"模型如何使用自己 |
| UI | `renderToolUseMessage` | 工具调用时的展示 | 自描述渲染，工具最了解自己 |

**ToolResult的设计：**

```typescript
export type ToolResult<T> = {
  data: T                           // 工具输出数据
  newMessages?: Message[]            // 额外注入的消息
  contextModifier?: (ctx) => ToolUseContext  // 上下文修改器
}
```

`contextModifier`允许工具在执行后修改上下文（如更新文件缓存），这是工具影响后续行为的关键通道。

### 3.2 为什么这么定义？

1. **三个泛型参数分离**（Input, Output, Progress）：每个关注点有独立的类型空间，编译器可以分别检查
2. **安全方法接收input参数**：同一工具对不同输入可以有不同的安全语义（BashTool对`ls`只读，对`rm`非只读）
3. **每个工具自带渲染方法**：避免中央渲染器根据工具类型分发的耦合
4. **Zod Schema承担双重职责**：一份定义既用于运行时验证又自动生成JSON Schema发送给API

### 3.3 buildTool()工厂模式

所有工具的创建都通过`buildTool()`工厂函数完成：

```typescript
const TOOL_DEFAULTS = {
  isEnabled: () => true,
  isConcurrencySafe: () => false,  // 默认不安全
  isReadOnly: () => false,         // 默认有写入
  isDestructive: () => false,
  checkPermissions: (input) => ({ behavior: 'allow', updatedInput: input }),
  toAutoClassifierInput: () => '',
  userFacingName: () => '',
}

function buildTool<D extends AnyToolDef>(def: D): BuiltTool<D> {
  return {
    ...TOOL_DEFAULTS,          // 先铺默认值
    userFacingName: () => def.name,  // 默认使用工具名
    ...def,                     // 工具自定义覆盖
  } as BuiltTool<D>
}
```

**类型层的精巧设计**：`BuiltTool<D>`在类型层面精确模拟了运行时的spread语义——如果工具定义了`isReadOnly`，返回类型用工具自己的实现；如果没定义，返回默认值的类型。

### 3.4 工具目录结构

每个工具独立存放在`src/tools/`下的同名目录中：

```
src/tools/FileEditTool/
├── FileEditTool.ts    // 主实现：call(), validateInput(), checkPermissions()
├── UI.tsx             // React渲染：renderToolUseMessage, renderToolResultMessage
├── types.ts           // Zod inputSchema + TypeScript类型
├── prompt.ts          // 工具特定的system prompt注入内容
├── constants.ts       // 常量定义
└── utils.ts           // 辅助函数
```

### 3.5 工具注册与组装：三层流水线

```
┌──────────────────────────────────────────────────────┐
│ Layer 1: getAllBaseTools()  — 编译时工具裁剪           │
│  核心工具(~20个) 直接import                           │
│  + Feature-gated工具(~46个) 条件require()             │
├──────────────────────────────────────────────────────┤
│ Layer 2: getTools()  — 运行时上下文过滤               │
│  1. SIMPLE模式裁剪  2. REPL模式过滤                   │
│  3. Deny规则过滤    4. isEnabled()检查                │
├──────────────────────────────────────────────────────┤
│ Layer 3: assembleToolPool()  — 合并与缓存感知排序      │
│  内置工具(排序) + MCP工具(排序) → uniqBy('name')      │
└──────────────────────────────────────────────────────┘
```

**Layer 1：编译时裁剪**

```typescript
// 核心工具：始终存在
import { BashTool } from './tools/BashTool/BashTool.js'
import { FileReadTool } from './tools/FileReadTool/FileReadTool.js'

// Feature-gated工具：编译时决定
const SleepTool = feature('PROACTIVE') || feature('KAIROS')
  ? require('./tools/SleepTool/SleepTool.js').SleepTool
  : null  // feature()是编译时宏，false时整个require被DCE删除
```

**Layer 2：四层递进过滤**

1. **SIMPLE模式**：仅保留BashTool、FileReadTool、FileEditTool
2. **REPL模式**：隐藏被REPL封装的原始工具
3. **Deny规则**：`mcp__server`前缀匹配一次性移除整个MCP服务器的工具
4. **isEnabled()**：工具根据运行时条件自行决定

**Layer 3：缓存感知排序**

```typescript
export function assembleToolPool(permissionContext, mcpTools): Tools {
  const builtInTools = getTools(permissionContext)
  const allowedMcpTools = filterToolsByDenyRules(mcpTools, permissionContext)
  const byName = (a, b) => a.name.localeCompare(b.name)
  return uniqBy(
    [...builtInTools].sort(byName).concat(allowedMcpTools.sort(byName)),
    'name',
  )
}
```

**为什么分区排序���非全局排序？** API服务器在最后一个内置工具之后设置缓存断点。如果MCP工具混入内置区间（如`mcp__github__create_issue`插入到`GlobTool`和`GrepTool`之间），会导致所有下游缓存键失效。分区排序确保MCP工具变动只影响后缀部分。

### 3.6 如何让Agent知道有哪些工具？

**并非把所有工具都放入system prompt。** Claude Code使用两层机制：

1. **非延迟工具**：完整的Schema（名称、描述、参数定义）通过API的`tools`数组发送给模型
2. **延迟工具**（`shouldDefer: true`）：只在prompt中以名称列表形式告知模型，模型通过`ToolSearchTool`按需加载完整Schema

```xml
<!-- 延迟工具只展示名称列表 -->
<available-deferred-tools>
mcp__slack__slack_send_message
mcp__github__create_pull_request
...
</available-deferred-tools>
```

当模型需要使用延迟工具时，调用`ToolSearchTool`，搜索结果以`tool_reference`块返回，API会自动展开为完整工具定义。

---

## 4. 深入调研：内置工具分类与解析

Claude Code包含66+内置工具，按功能分为以下类别：

### 4.1 文件操作工具

| 工具 | 作用 | 并发安全 | 只读 | 亮点 |
|-----|------|---------|------|------|
| **BashTool** | Shell命令执行 | 否 | 否 | 18个源文件，最复杂的工具，7+层安全防御 |
| **FileReadTool** | 读取文件（支持图片、PDF、Jupyter） | 是 | 是 | 文件状态缓存(LRU)，避免重复I/O |
| **FileEditTool** | 精确字符串替换编辑 | 否 | 否 | old_string→new_string模式，幂等性强 |
| **FileWriteTool** | 创建/覆写文件 | 否 | 否 | 检查是否已读过文件再写入 |
| **GlobTool** | 文件名模式匹配 | 是 | 是 | 基于fast-glob |
| **GrepTool** | 正则搜索文件内容 | 是 | 是 | 基于ripgrep |
| **NotebookEditTool** | Jupyter Notebook编辑 | 否 | 否 | 单元格级别操作 |

**工作流程示例：**
```
用户："在src目录下找到所有包含TODO的文件"
→ GrepTool({ pattern: "TODO", path: "src/" })
→ 返回匹配的文件列表和行号
→ FileReadTool读取具体文件
→ FileEditTool修改或删除TODO
```

### 4.2 网络工具

| 工具 | 作用 | 并发安全 | 场景 |
|-----|------|---------|------|
| **WebFetchTool** | 获取网页内容 | 是 | 查看文档、API响应 |
| **WebSearchTool** | API驱动的网络搜索 | 是 | 搜索技术文档、解决方案 |

### 4.3 Agent管理工具

| 工具 | 作用 | 亮点 |
|-----|------|------|
| **AgentTool** | 派生子Agent | 多Agent架构核心，支持worktree/remote隔离 |
| **TaskOutputTool** | 输出任务结果 | 子Agent向父Agent传递结果 |
| **TaskStopTool** | 停止后台任务 | 优雅终止 |
| **TaskCreate/Get/Update/ListTool** | 任务管理v2 | 完整的任务生命周期管理 |
| **SendMessageTool** | Agent间通信 | 支持Tmux/iTerm2会话间通信 |

### 4.4 用户交互工具

| 工具 | 作用 | 场景 |
|-----|------|------|
| **AskUserQuestionTool** | 向用户提问 | 需要澄清需求时 |
| **TodoWriteTool** | 管理待办列表 | 跟踪多步骤任务进度 |
| **SkillTool** | 加载并执行技能 | 调用预定义工作流 |

### 4.5 系统工具

| 工具 | 作用 | 场景 |
|-----|------|------|
| **EnterPlanModeTool / ExitPlanModeTool** | 规划模式切换 | 复杂任务先规划再执行 |
| **EnterWorktreeTool / ExitWorktreeTool** | Git Worktree隔离 | 子Agent在独立文件视图中工作 |
| **ToolSearchTool** | 搜索并加载延迟工具 | 工具数量多时按需发现 |
| **ConfigTool** | 配置管理 | 修改Agent配置 |
| **BriefTool** | 生成简要摘要 | 压缩上下文 |

### 4.6 MCP集成工具

| 工具 | 作用 | 传输机制 |
|-----|------|---------|
| **MCPTool** | 调用MCP工具 | 7种传输：stdio/sse/http/ws/sdk等 |
| **ListMcpResourcesTool** | 列出MCP资源 | 资源发现 |
| **ReadMcpResourceTool** | 读取MCP资源内容 | 资源消费 |
| **LSPTool** | 语言服务器操作 | 代码智能 |

### 4.7 团队协作工具

| 工具 | 作用 |
|-----|------|
| **TeamCreateTool** | 创建Agent团队 |
| **TeamDeleteTool** | 删除Agent团队 |
| **ListPeersTool** | 列出同级Agent |

---

## 5. 深入调研：工具调用全流程

### 5.1 完整生命周期（8个阶段）

```
模型输出tool_use block
    ↓
[Stage 1] 工具查找（name/alias匹配）
    ↓
[Stage 2] 输入验证（Zod Schema → validateInput）
    ↓
[Stage 3] 并行启动（Pre-Tool Hook ∥ Bash分类器）
    ↓
[Stage 4] 权限检查（7源规则链 + 分类器 + 交互确认）
    ↓
[Stage 5] 工具执行（tool.call + 流式进度）
    ↓
[Stage 6] 结果处理（大结果持久化 + 截断）
    ↓
[Stage 7] Post-Tool Hook（成功/失败分别触发）
    ↓
[Stage 8] 消息发射（tool_result block）
```

### 5.2 各阶段详解

#### Stage 1 - 工具查找

系统按`name`和`aliases`匹配工具定义。如果通过废弃别名调用，在`tool_result`中附加废弃警告。未找到匹配工具时返回错误消息（模型幻觉出不存在的工具时发生）。

#### Stage 2 - 输入验证（两阶段）

```typescript
// Phase 1: Zod Schema强制转换
const parsed = tool.inputSchema.safeParse(rawInput)
// safeParse不仅验证，还做类型强制（如字符串数字→数字）

// Phase 2: 业务逻辑验证（仅在Schema验证通过后执行）
const validation = await tool.validateInput(parsed.data, context)
// 返回类型：
// { result: true }                         — 验证通过
// { result: false, message, errorCode }    — 直接拒绝
// { result: false, message, behavior: 'ask' } — 让用户决定
```

**两阶段分离确保**：Schema层做结构验证（字段、类型），业务层做语义验证（文件是否存在、是否先读后写）。

#### Stage 3 - 并行启动

Pre-Tool Hook和Bash分类器**同时**启动，而非串行等待：
- **Pre-Tool Hook**：执行用户在`hooks.preToolUse`中配置的外部脚本
- **Bash分类器**：对BashTool调用进行投机性安全分类

#### Stage 4 - 权限检查（最复杂的阶段）

权限检查涉及多个决策源，按优先级链式求值：

```
4a. Hook权限覆盖（最高优先级：allow/deny/穿透）
    ↓
4b. 工具自身checkPermissions()
    ↓
4c. 规则匹配（7个来源：session > cliArg > local > user > project > policy > flag）
    ↓
4d. 投机分类器结果（Bash专用）
    ↓
4e. 交互式确认弹窗（最后手段）
    ↓
4f. 拒绝追踪（防止请求→拒绝→再请求死循环）
```

**7个规则来源的优先级**：

| 来源 | 说明 | 示例 |
|------|------|------|
| session | 当前会话临时授权 | 用户点击"允许一次" |
| cliArg | 命令行参数 | `--allowedTools 'Bash(git *)'` |
| localSettings | `.claude/settings.local.json` | 不提交到git的个人设置 |
| userSettings | `~/.claude/settings.json` | 用户级全局设置 |
| projectSettings | `.claude/settings.json` | 项目级共享设置 |
| policySettings | 组织策略配置 | 企业管理员下发的强制规则 |
| flagSettings | 功能标志动态配置 | 服务端远程配置 |

#### Stage 5 - 工具执行

`tool.call()`执行实际操作。关键机制是`onProgress`回调，允许工具实时发射进度消息（如BashTool流式传输stdout）。

#### Stage 6 - 结果处理

如果结果超过`maxResultSizeChars`：
1. 完整结果保存到`~/claude-code/tool-results/`目录
2. 模型接收：文件路径 + 截断指示符
3. 模型可通过FileReadTool按需读取

**三级大小限制**：

| 限制 | 值 | 作用 |
|------|---|------|
| `DEFAULT_MAX_RESULT_SIZE_CHARS` | 50,000 | 单个工具结果上限 |
| `MAX_TOOL_RESULT_TOKENS` | 100,000 (~400KB) | 绝对上限 |
| `MAX_TOOL_RESULTS_PER_MESSAGE_CHARS` | 200,000 | 单条消息所有工具结果聚合上限 |

#### Stage 7 - Post-Tool Hook

- `postToolUse`：工具成功时触发
- `postToolFail`：工具失败时触发

#### Stage 8 - 消息发射

将结果转换为`tool_result` block发送回API。

### 5.3 错误处理哲学：错误是数据，不是异常

任何阶段的错误都不会导致进程崩溃——它们被转换为`tool_result`消息（带`is_error: true`）返回给模型，让模型自我纠正。

### 5.4 示例：模拟全流程

**用户请求**：`"在src/utils.ts文件中，把所有的console.log替换为logger.info"`

**Step 1**：模型决定先读取文件，输出`tool_use` block：
```json
{ "name": "FileReadTool", "input": { "path": "src/utils.ts" } }
```

**Step 2 - 工具查找**：按name匹配到FileReadTool ✓

**Step 3 - 输入验证**：
- Zod Schema验证：path是string ✓
- validateInput：文件路径在允许范围内 ✓

**Step 4 - 权限检查**：FileReadTool的isReadOnly返回true，跳过权限弹窗 ✓

**Step 5 - 执行**：读取文件内容，返回文件文本

**Step 6 - 结果处理**：文件内容在maxResultSizeChars范围内，直接返回

**Step 7/8**：发射tool_result，包含文件内容

**模型看到文件内容后**，决定使用FileEditTool：
```json
{
  "name": "FileEditTool",
  "input": {
    "path": "src/utils.ts",
    "old_string": "console.log(",
    "new_string": "logger.info("
  }
}
```

**Step 2-4**：验证通过 → 权限检查（FileEditTool是非只读，检查规则匹配或弹出确认）

**Step 5**：执行精确替换

**Step 6-8**：返回编辑结果（diff信息），FileEditTool通过`contextModifier`更新文件缓存

**如果有多个console.log**，模型会连续发出多个FileEditTool调用，由于FileEditTool非并发安全，它们会串行执行。

---

## 6. 重点工具深入分析

### 6.1 BashTool 深度解析

BashTool是整个工具系统中**最复杂的工具**，实现分布在18个源文件中。其复杂性源于根本矛盾：Shell是最强大的工具（几乎可以做任何事），也是最危险的工具。

#### 输入Schema

```typescript
{
  command: string              // Shell命令
  timeout?: number             // 超时（毫秒）
  description?: string         // 活动描述（UI展示）
  run_in_background?: boolean  // 异步执行
  dangerouslyDisableSandbox?: boolean // 禁用沙箱
}
```

#### 安全验证（bashSecurity.ts，~800行）

实现了23个命名安全检查，通过`BASH_SECURITY_CHECK_IDS`映射为数字ID（避免遥测日志中的可变字符串）。

**最关键的防御——命令替换阻断**（11种模式）：

```typescript
const COMMAND_SUBSTITUTION_PATTERNS = [
  { pattern: /<\(/, message: 'process substitution <()' },
  { pattern: /\$\(/, message: '$() command substitution' },
  { pattern: /\$\{/, message: '${} parameter substitution' },
  // Zsh equals展开：=curl evil.com → /usr/bin/curl evil.com
  // 绕过Bash(curl:*) deny规则
  { pattern: /(?:^|[\s;&|])=[a-zA-Z_]/, message: 'Zsh equals expansion' },
  // ... 更多模式
]
```

**Tree-sitter AST解析**：当tree-sitter-bash可用时，将命令解析为AST进行结构化分析。太复杂的命令（包含嵌套替换、复杂控制流）返回`'too-complex'`，触发`ask`行为。

#### 多层权限系统（bashPermissions.ts）

`bashToolHasPermission()`是整个代码库中最复杂的权限函数：

```
第1步：AST解析与复杂度判断 → simple/too-complex/parse-unavailable
第2步：子命令拆分（上限50个，防CPU耗尽）
第3步：安全环境变量剥离（NODE_ENV=prod → 剥离后匹配规则）
第4步：前缀提取与规则建议（git commit → Bash(git commit:*)）
第5步：复合命令权限聚合（任一deny则整体deny）
```

**安全环境变量剥离示例**：

| 命令 | 剥离后 | 匹配规则 |
|-----|--------|---------|
| `NODE_ENV=prod npm run build` | `npm run build` | `Bash(npm run:*)` |
| `git commit -m "fix typo"` | `git commit` | `Bash(git commit:*)` |
| `bash -c "rm -rf /"` | 不生成前缀规则 | 阻止`Bash(bash:*)`等同于`Bash(*)` |

#### 命令语义理解

BashTool不只是检查退出码——它理解不同命令的语义约定：

| 命令 | 退出码0 | 退出码1 | 退出码2+ |
|-----|--------|--------|---------|
| grep | 找到匹配 | **无匹配（不是错误）** | 真正的错误 |
| diff | 无差异 | **有差异（不是错误）** | 真正的错误 |
| test | 条件为真 | **条件为假（不是错误）** | 语法错误 |

`interpretCommandResult()`避免模型将grep的"无匹配"误判为执行失败。

#### 后台任务管理

- **显式后台化**：`run_in_background: true`，从一开始就异步
- **自动后台化**：阻塞命令15秒后自动转后台，防止`npm install`阻塞对话

#### 沙箱模式

- macOS：`sandbox-exec`配置
- Linux：`bubblewrap (bwrap)` 提供类landlock限制

### 6.2 AgentTool 深度解析

AgentTool负责派生子Agent，是多Agent架构的核心。

#### 输入Schema

```typescript
{
  description: string            // 3-5词任务描述
  prompt: string                 // 子Agent任务指令
  subagent_type?: string         // 专用Agent类型(coder/researcher)
  model?: 'sonnet' | 'opus' | 'haiku'
  run_in_background?: boolean    // 异步执行
  name?: string                  // 可寻址的队友名称
  isolation?: 'worktree' | 'remote' // 隔离模式
}
```

#### 子Agent生命周期（6阶段）

```
Stage 1: Agent定义查找（按subagent_type匹配 + MCP需求过滤）
    ↓
Stage 2: 模型解析（参数指定 > 定义默认 > 继承父级）
    ↓
Stage 3: 隔离环境搭建（worktree: git worktree add / remote: CCR部署）
    ↓
Stage 4: 工具池组装（按Agent定义的白名单/黑名单过滤）
    ↓
Stage 5: 系统提示词渲染（模板 + CWD/OS/Shell/Git状态注入）
    ↓
Stage 6: 执行与返回（同步/异步/队友/远程 四种模式）
```

**四种执行模式**：

| 模式 | 描述 | 结果获取 |
|------|------|---------|
| 同步 | 当前进程内直接执行 | 嵌入父对话的tool_result |
| 异步 | LocalAgentTask | 父Agent通过TaskGetTool轮询 |
| 队友 | Tmux/iTerm2新会话 | 通过SendMessageTool通信 |
| 远程 | CCR WebSocket | 结果异步回传 |

**应用场景示例**：
```
用户："重构整个项目的错误处理"
→ 主Agent分析项目结构
→ AgentTool({
    description: "Refactor error handling in auth module",
    prompt: "...",
    isolation: "worktree"  // 独立工作树,避免文件冲突
  })
→ 子Agent在隔离环境中工作
→ 结果合并回主分支
```

### 6.3 FileEditTool 设计解析

#### 为什么用字符串匹配而非行号？

| 方案 | 优点 | 缺点 |
|------|------|------|
| 行号范围 | 直观 | 脆弱：文件被修改后行号偏移 |
| 精确字符串匹配 | 幂等：只要目标字符串存在就能正确定位 | 需要精确匹配 |

FileEditTool选择了后者，并在prompt中注入关于精确匹配的规则（通过`prompt.ts`），教模型如何正确使用。

#### isDestructive的输入感知

FileEditTool的`isDestructive`方法根据编辑内容判断是否为破坏性操作（如删除大量代码），而非简单的"写入即破坏性"。

### 6.4 ToolSearchTool 设计解析

#### 三种查询模式

| 语法 | 说明 | 示例 |
|------|------|------|
| `"select:Name1,Name2"` | 精确选择 | `"select:Read,Edit,Grep"` |
| `"关键词1 关键词2"` | 关键词搜索 | `"notebook jupyter"` |
| `"+前缀 关键词"` | 名称前缀约束 | `"+slack send"` |

#### 搜索评分权重

```
name部分精确匹配：MCP 12分 / 普通 10分
name部分包含匹配：MCP 6分 / 普通 5分
searchHint匹配：4分
description匹配：2分
```

#### tst-auto模式

计算所有deferred工具定义占上下文窗口的比例，超过阈值（默认10%）才启用延迟加载：

```typescript
function getAutoToolSearchTokenThreshold(model: string): number {
  const contextWindow = getContextWindowForModel(model, betas)
  const percentage = getAutoToolSearchPercentage() / 100
  return Math.floor(contextWindow * percentage)
}
```

---

## 7. Agent系统开发的设计参考

### 参考1：Builder + Fail-Closed安全默认

```typescript
// 可直接复用的模式
const DEFAULTS = {
  isReadOnly: () => false,      // 默认假设不安全
  canRunConcurrently: () => false,
  requiresPermission: () => true,
}

function buildPlugin(def) {
  return { ...DEFAULTS, ...def }
}
```

**适用场景**：任何插件/中间件系统，特别是涉及安全敏感操作时。

### 参考2：分层条件注册

```
编译期 feature() → 模块加载时 env check → 运行时 isEnabled() → 权限 deny rules
```

**适用场景**：需要从同一份代码构建多个版本的项目。

### 参考3：并发安全分区

通过`isConcurrencySafe`标记将批量操作分区为可并发组和必须串行组。连续的安全工具合并为一个并发batch，遇到不安全工具就切换为独立batch。

```typescript
// 分区算法核心
if (isConcurrencySafe && lastBatch?.isConcurrencySafe) {
  lastBatch.blocks.push(toolUse)  // 合并
} else {
  batches.push({ isConcurrencySafe, blocks: [toolUse] })  // 新batch
}
```

**适用场景**：任何需要批量执行异构任务的系统。

### 参考4：大结果的按需读取模式

不直接把大量数据注入上下文，而是保存到磁盘后返回路径引用。模型需要详细数据时主动拉取。

```
工具输出 > 50KB？
  → 保存到磁盘
  → 返回路径 + 摘要
  → 模型通过FileReadTool按需读取
```

**适用场景**：上下文窗口有限的任何Agent系统。

### 参考5：流式并行执行

不等待所有工具请求完成再执行，一旦单个tool_use block完整就立即启动。配合4阶段状态机（queued→executing→completed→yielded）和FIFO顺序保证。

### 参考6：错误是数据，不是异常

所有阶段的错误都转换为`tool_result`消息返回给模型，而非抛出异常中断对话。模型可以自我纠正。

```typescript
// 错误分类用于遥测
1. TelemetrySafeError → telemetryMessage
2. Error + errno → "Error:ENOENT"
3. Error + 长name → 原始错误名
4. 其他Error → "Error"
5. 非Error值 → "UnknownError"
```

### 参考7：缓存感知的工具列表管理

多个设计决策都服务于同一个隐形约束——prompt cache命中率：
- 分区排序（防止MCP工具变动污染缓存键）
- backfillObservableInput只修改UI层（不影响API缓存）
- 延迟加载（稳定初始工具列表）

### 参考8：工具自带渲染方法

每个工具知道如何最好地展示自己的输入输出——FileEditTool渲染diff、BashTool渲染终端输出、GrepTool渲染带行号的搜索结果。新增工具不需要修改全局渲染逻辑。

### 参考9：Hook系统实现可扩展性

Pre-Tool Hook和Post-Tool Hook允许用户注入自定义逻辑（如自动审批特定命令、记录日志），而无需修改工具本身。

---

## 8. 总结速记表

| 维度 | 要点 | 关键设计 |
|------|------|---------|
| **工具定义** | `Tool<Input, Output, P>` 统一泛型接口 | 五要素：名称、Schema、权限、执行、渲染 |
| **工具创建** | `buildTool()`工厂函数 | Fail-closed默认值（���安全的默认为false） |
| **工具注册** | 三层流水线 | 编译时DCE → 运行时过滤 → 缓存感知排序 |
| **工具发现** | ToolSearchTool延迟加载 | 只发名称列表，按需加载完整Schema |
| **工具调用** | 8阶段生命周期 | 查找→验证→Hook/分类器→权限→执行→结果→Hook→发射 |
| **权限系统** | 7源规则 + 链式求值 | Hook > 工具自身 > 规则匹配 > 分类器 > 交互确认 |
| **并发控制** | 并发安全分区 | 只读工具并行，写入工具串行，上限10 |
| **流式执行** | StreamingToolExecutor | 4阶段状态机，边接收边执行，FIFO输出 |
| **大结果** | 三级大小限制 | 50K/100K/200K，超限持久化到磁盘 |
| **错误处理** | 错误是数据不是异常 | 转为tool_result(is_error:true)返回模型 |
| **BashTool** | 18个源文件，最复杂 | 7+层安全：AST/正则/引用提取/路径/sed/沙箱/权限 |
| **AgentTool** | 多Agent核心 | 6阶段生命周期，4种执行模式，上下文隔离 |
| **FileEditTool** | 精确编辑 | 字符串匹配(非行号)，幂等性，输入感知破坏性 |
| **MCP集成** | 7种传输 + 7层配置 | 桥接层统一到Tool接口，二进制blob自动保存 |
| **安全设计** | 纵深防御 | 每层都可以失败，攻击者需同时绕过所有层 |
| **缓存优化** | 多个设计服务缓存命中率 | 分区排序/backfill不改API/延迟加载 |
| **UI渲染** | 渲染即工具 | 6个render方法覆盖完整生命周期，自描述渲染 |

---

**一句话总结**：Claude Code的Tool System通过**统一接口 + Fail-closed默认 + 三层注册流水线 + 流式并行执行 + 纵深安全防御 + 按需加载**的组合设计，实现了一个从20个工具无缝扩展到66+个工具、同时保持安全性和高性能的生产级Agent工具框架。对于自研Agent系统，最值得借鉴的是：Builder+安全默认模式、并发安全分区、大结果按需读取、以及"错误是数据"的哲学。