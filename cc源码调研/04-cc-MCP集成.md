# Claude Code MCP集成 深度调研报告

---

## 目录

1. [MCP协议概念解析](#1-mcp协议概念解析)
2. [Claude Code MCP集成设计亮点](#2-claude-code-mcp集成设计亮点)
3. [深入调研：MCP定义与注册机制](#3-深入调研mcp定义与注册机制)
4. [深入调研：内置MCP桥接工具](#4-深入调研内置mcp桥接工具)
5. [深入调研：MCP调用全流程](#5-深入调研mcp调用全流程)
6. [深入调研：MCP权限校验与安全审查](#6-深入调研mcp权限校验与安全审查)
7. [Tool与MCP全流程对比](#7-tool与mcp全流程对比)
8. [Agent系统开发的MCP设计参考](#8-agent系统开发的mcp设计参考)
9. [总结速记表](#9-总结速记表)

---

## 1. MCP协议概念解析

### 1.1 什么是MCP？

**MCP（Model Context Protocol）** 是Anthropic提出的开放标准协议，定义了AI应用（Client）与外部工具/数据服务（Server）之间的通信规范。可以将其理解为**AI世界的"USB-C接口"**——只要服务实现了MCP协议，任何支持MCP的AI应用都能自动发现并使用它提供的工具，无需修改AI应用本身的代码。

### 1.2 动机与必要性

**碎片化的集成困境：** 在LLM应用生态中，每个AI应用连接外部数据源和工具的方式各不相同。如果你是一个数据库供应商，想让数据被各种AI工具访问，你需要为每个平台分别开发适配器——为Claude写一个，为ChatGPT写一个，为Cursor写一个……

| 维度 | 没有MCP | 有MCP |
|------|--------|-------|
| 工具开发者 | 为每个AI平台写适配器（N×M问题） | 实现一次MCP Server，所有客户端可用 |
| AI应用开发者 | 为每个工具写集成代码 | 实现一次MCP Client，接入整个生态 |
| 集成成本 | O(N×M) | O(N+M) |
| 安全标准 | 每个集成自定义安全策略 | 统一的安全协议和能力协商 |

### 1.3 MCP协议架构详解

#### 三大设计原则

```
┌─────────────────────────────────────────────────┐
│                 MCP 设计哲学                      │
├─────────────┬───────────────┬───────────────────┤
│ 协议即契约    │ 传输无关性     │ 安全边界内嵌       │
│ Protocol as  │ Transport     │ Security by       │
│ Contract     │ Agnostic      │ Design            │
├─────────────┼───────────────┼───────────────────┤
│ 先声明后使用  │ 不绑定传输方式  │ 默认不信任         │
│ 严格消息格式  │ stdio/HTTP/WS │ 每层都有安全策略    │
│ 能力协商机制  │ 均可           │                   │
└─────────────┴───────────────┴───────────────────┘
```

#### 协议分层架构

```
┌───────────────────────────────────────────────────┐
│ 应用层 (Application Layer)                         │
│   Tools（工具）/ Resources（资源）/ Prompts（提示模板）│
├───────────────────────────────────────────────────┤
│ 协议层 (Protocol Layer)                            │
│   JSON-RPC 2.0 消息格式                             │
│   能力协商 (Capability Negotiation)                  │
│   tools/list, tools/call, resources/list 等方法     │
├───────────────────────────────────────────────────┤
│ 传输层 (Transport Layer)                           │
│   stdio | SSE | HTTP Streamable | WebSocket | SDK  │
└───────────────────────────────────────────────────┘
```

#### MCP服务器能力声明

MCP服务器可以提供三类能力：

| 能力类型 | 说明 | 发现方法 | 在CC中的映射 |
|---------|------|---------|-----------|
| **Tools** | 可调用的工具函数 | `tools/list` | 映射为`Tool`对象 |
| **Resources** | 可读取的数据资源 | `resources/list` | 通过`ListMcpResourcesTool`/`ReadMcpResourceTool`访问 |
| **Prompts** | 提示模板 | `prompts/list` | 映射为斜杠命令 |

#### MCP与Tool System、Skill的关系

| 维度 | Tool System（内置工具） | MCP（外部工具协议） | Skill（技能模板） |
|------|----------------------|-------------------|-----------------|
| **本质** | 进程内函数调用 | 跨进程/跨网络的标准化协议 | Prompt模板+工具组合 |
| **集成深度** | 深度集成（直接访问进程状态） | 广度扩展（协议适配） | 知识复用 |
| **通信开销** | 零 | 有（序列化/反序列化） | 零（Prompt层面） |
| **安全边界** | 共享进程权限 | 进程隔离/网络隔离 | 复用已有安全机制 |
| **在CC中的统一** | `Tool<Input,Output,P>`接口 | 映射为相同的`Tool`接口 | 转化为Prompt注入 |

**关键洞察：** Claude Code将MCP工具映射为内部的`Tool`对象后，MCP工具和内置工具在执行流水线上**完全统一**——经过相同的输入验证、权限检查、并发调度、结果处理。MCP不是一个独立子系统，而是工具系统的自然延伸。

---

## 2. Claude Code MCP集成设计亮点

### 亮点1：统一接口——MCP工具与内置工具无缝融合

MCP工具被映射为与内置工具相同的`Tool<Input, Output, P>`接口，共享完整的执行流水线（验证→权限→Hook→执行→结果处理）。新增一个MCP服务器不需要修改任何执行逻辑。

### 亮点2：8种传输协议全覆盖

从零开销的SDK（进程内调用）到stdio（进程间管道），从SSE/HTTP（远程服务）到WebSocket（全双工通信），每种协议针对特定场景优化。

### 亮点3：两阶段配置加载——快启动+延迟补充

Phase 1只读本地文件（毫秒级），Phase 2的claude.ai网络请求与Phase 1并行发起，实现启动性能隔离。

### 亮点4：签名去重——基于实际效果而非表面配置

通过`stdio:JSON.stringify([cmd,...args])`和`url:originalUrl`的内容签名机制，确保多来源配置（手动/插件/claude.ai连接器）不会产生重复连接。

### 亮点5：四层权限深度防御

企业策略（denylist>allowlist）→ IDE工具白名单 → 用户权限配置 → 运行时确认，即使某一层被绕过，其他层仍然提供保护。

### 亮点6：三段式命名`mcp__server__tool`

不仅解决工具名称冲突，更在权限检查时提供独立命名空间，防止MCP工具与内置工具之间的权限混淆。

### 亮点7：本地/远程分治并发

本地服务器（stdio/sdk）使用低并发（默认3），远程服务器使用高并发（默认20），并通过`pMap`滑动窗口替代固定批次调度。

### 亮点8：InProcess传输——避免325MB子进程

对Chrome MCP等内置服务器使用进程内直连（`createLinkedTransportPair`），避免每个MCP启动独立进程的内存开销。

### 亮点9：行为注解桥接

MCP协议的Hints（`readOnlyHint`、`destructiveHint`）被桥接为Claude Code工具系统的Decisions（`isConcurrencySafe()`、`isDestructive()`），允许服务器描述行为，由客户端做最终安全决策。

---

## 3. 深入调研：MCP定义与注册机制

### 3.1 MCP服务器配置是如何定义的？

MCP的类型定义集中在`services/mcp/types.ts`（约259行），使用TypeScript + Zod构建数据契约层。

#### 配置作用域

```typescript
// services/mcp/types.ts:10-26
export const ConfigScopeSchema = lazySchema(() =>
  z.enum([
    'local',       // .claude/settings.local.json
    'user',        // ~/.claude/settings.json
    'project',     // .mcp.json（从CWD向上遍历）
    'dynamic',     // 运行时动态注入（--mcp-config）
    'enterprise',  // managed-mcp.json（企业管控）
    'claudeai',    // claude.ai 连接器
    'managed',     // 企业 managed settings
  ]),
)
```

#### 每种传输的精确Schema

每种传输方式有独立的Zod schema：

```typescript
// stdio：本地进程
export const McpStdioServerConfigSchema = lazySchema(() =>
  z.object({
    type: z.literal('stdio').optional(),  // 可选，向后兼容
    command: z.string().min(1, 'Command cannot be empty'),
    args: z.array(z.string()).default([]),
    env: z.record(z.string(), z.string()).optional(),
  }),
)

// SSE：远程Server-Sent Events
export const McpSSEServerConfigSchema = lazySchema(() =>
  z.object({
    type: z.literal('sse'),
    url: z.string(),
    headers: z.record(z.string(), z.string()).optional(),
    headersHelper: z.string().optional(),   // 动态header脚本
    oauth: McpOAuthConfigSchema().optional(),
  }),
)

// HTTP：Streamable HTTP（MCP规范推荐）
export const McpHTTPServerConfigSchema = lazySchema(() =>
  z.object({
    type: z.literal('http'),
    url: z.string(),
    headers: z.record(z.string(), z.string()).optional(),
    headersHelper: z.string().optional(),
    oauth: McpOAuthConfigSchema().optional(),
  }),
)

// SDK：进程内SDK传输
export const McpSdkServerConfigSchema = lazySchema(() =>
  z.object({
    type: z.literal('sdk'),
    name: z.string(),
  }),
)
```

所有配置通过union统一：

```typescript
export const McpServerConfigSchema = lazySchema(() =>
  z.union([
    McpStdioServerConfigSchema(),
    McpSSEServerConfigSchema(),
    McpSSEIDEServerConfigSchema(),
    McpWebSocketIDEServerConfigSchema(),
    McpHTTPServerConfigSchema(),
    McpWebSocketServerConfigSchema(),
    McpSdkServerConfigSchema(),
    McpClaudeAIProxyServerConfigSchema(),
  ]),
)
```

#### 8种传输协议的选型

| 协议 | 传输方式 | 延迟 | 适用场景 |
|------|---------|------|---------|
| `stdio` | 标准输入/输出管道 | 最低 | **首选**。本地开发工具、CLI封装 |
| `sse` | Server-Sent Events | 网络延迟 | 远程HTTP服务 |
| `sse-ide` | SSE + IDE元数据 | 本地网络 | IDE扩展专用 |
| `http` | HTTP Streamable | 网络延迟 | MCP规范新协议，支持流式 |
| `ws` | WebSocket全双工 | 网络延迟 | 需要双向实时通信 |
| `ws-ide` | WebSocket + IDE | 本地网络 | IDE扩展，低延迟双向 |
| `sdk` | 进程内函数调用 | 近零 | SDK内部调用 |
| `claudeai-proxy` | Claude.ai代理 | 网络延迟 | Claude.ai平台 |

### 3.2 连接状态建模

服务器连接使用TypeScript的discriminated union精确建模5种状态：

```typescript
export type MCPServerConnection =
  | ConnectedMCPServer    // 已连接，工具可用
  | FailedMCPServer       // 连接失败
  | NeedsAuthMCPServer    // 需要认证
  | PendingMCPServer      // 等待重连（指数退避）
  | DisabledMCPServer     // 已禁用

// Connected状态包含完整信息
export type ConnectedMCPServer = {
  client: Client                      // MCP SDK客户端实例
  name: string
  type: 'connected'
  capabilities: ServerCapabilities    // 服务器能力声明
  instructions?: string              // 使用指南
  config: ScopedMcpServerConfig
  cleanup: () => Promise<void>        // 清理函数
}
```

### 3.3 CC如何区分MCP工具和内置Tool？

**关键设计：MCP工具被映射为与内置工具相同的`Tool`接口，但通过标记字段区分。**

映射后的MCP工具包含以下**MCP专属属性**：

| 属性 | 来源 | 作用 |
|------|------|------|
| `isMcp: true` | 固定标记 | **区分MCP工具与内置工具的核心标识** |
| `mcpInfo` | 服务器配置 | 包含`serverName`和`toolName`的元信息 |
| `isConcurrencySafe()` | MCP注解`readOnlyHint` | 桥接为并发安全性判断 |
| `isDestructive()` | MCP注解`destructiveHint` | 桥接为破坏性判断 |
| `alwaysLoad` | `_meta.anthropic/alwaysLoad` | 控制是否跳过延迟加载 |
| `inputJSONSchema` | MCP返回的JSON Schema | **MCP工具直接用JSON Schema而非Zod** |

内置工具使用Zod定义`inputSchema`，而MCP工具直接使用MCP服务器返回的JSON Schema作为`inputJSONSchema`。这是两者在Schema层面的主要区别。

### 3.4 MCP是如何注册的？

#### 两阶段配置加载

```
Phase 1：快速加载（仅本地文件读取，毫秒级）
  ├── getClaudeCodeMcpConfigs() → plugin < user < project < local
  ├── dynamicMcpConfig（--mcp-config参数覆盖）
  └── 开始连接（fire-and-forget）

Phase 2：延迟补充（需要网络请求，与Phase 1并行发起）
  ├── fetchClaudeAIMcpConfigsIfEligible()
  ├── filterMcpServersByPolicy() → 策略过滤
  ├── dedupClaudeAiMcpServers() → URL签名去重
  └── 追加连接claude.ai服务器
```

#### 配置优先级

| 优先级 | 来源 | 加载阶段 |
|--------|------|---------|
| 最低 | claude.ai连接器 | Phase 2（网络请求） |
| ↓ | plugin服务器 | Phase 1（缓存读取） |
| ↓ | user配置 | Phase 1（本地文件） |
| ↓ | project配置（需审批） | Phase 1（本地文件） |
| ↓ | local配置 | Phase 1（本地文件） |
| 最高 | dynamic（--mcp-config） | Phase 1（调用方覆盖） |
| 独占 | enterprise（managed-mcp.json） | 独占模式，跳过其他所有 |

#### 工具发现→映射→注册的三阶段

```
阶段1：工具发现
  MCP服务器Connected → tools/list请求 → 获取工具名称/描述/Schema

阶段2：工具映射
  Unicode清理 → 前缀决策(mcp__server__tool) → Tool对象构造（注解桥接）

阶段3：工具注册
  权限检查 → alwaysLoad？
    是 → 直接注入System Prompt
    否 → 延迟加载（ToolSearch首次调用时加载）
```

### 3.5 如何让Agent知道有哪些MCP可以调用？

**并非把所有MCP工具都放入system prompt。** 采用与内置工具相同的延迟加载机制：

1. **标记为`alwaysLoad: true`的MCP工具**：直接注入system prompt的tools数组，模型始终可见
2. **其他MCP工具（默认）**：仅以名称列表形式出现在prompt中，模型通过`ToolSearchTool`按需加载完整Schema

```xml
<!-- 延迟的MCP工具只展示名称 -->
<available-deferred-tools>
mcp__slack__slack_send_message
mcp__github__create_pull_request
...
</available-deferred-tools>
```

当模型需要使用时，调用`ToolSearchTool`搜索，结果以`tool_reference`块返回，API自动展开为完整工具定义。

---

## 4. 深入调研：内置MCP桥接工具

Claude Code内置了4个专门用于MCP交互的**桥接工具**：

### 4.1 桥接工具清单

| 工具 | 作用 | 并发安全 | 场景 |
|------|------|---------|------|
| **MCPTool** | 调用单个MCP工具（核心代理） | 取决于注解 | 所有MCP工具调用 |
| **ListMcpResourcesTool** | 列出MCP资源 | 是 | 资源发现 |
| **ReadMcpResourceTool** | 读取MCP资源内容 | 是 | 资源消费 |
| **createMcpAuthTool()** | OAuth认证处理 | - | needs-auth状态时自动注入 |

### 4.2 MCPTool——核心代理工具

MCPTool是所有MCP工具调用的核心代理。每个MCP工具被映射后，其`call()`方法实际上会通过MCPTool的基础实现，将调用转发到MCP服务器：

```typescript
// 每个MCP工具的call方法本质上是代理
async call(args, context, _canUseTool, parentMessage, onProgress) {
  // 确保连接仍然有效
  const connectedClient = await ensureConnectedClient(client)
  // 通过MCP协议调用远程工具
  const mcpResult = await callMCPToolWithUrlElicitationRetry({
    client: connectedClient,
    tool: tool.name,     // 原始工具名（不带前缀）
    args,
    signal: context.abortController.signal,
  })
  return { data: mcpResult.content }
}
```

**亮点：** 描述截断防御——防止OpenAPI生成的MCP服务器倾倒15-60KB的文档：

```typescript
async prompt() {
  const desc = tool.description ?? ''
  return desc.length > MAX_MCP_DESCRIPTION_LENGTH  // 2048字符
    ? desc.slice(0, MAX_MCP_DESCRIPTION_LENGTH) + '… [truncated]'
    : desc
}
```

### 4.3 MCP Prompts → 斜杠命令

MCP服务器还可以提供Prompts（提示模板），Claude Code将它们自动映射为斜杠命令：

```typescript
// MCP prompt → 斜杠命令
{
  name: 'mcp__github__code_review',  // 用户输入 /mcp__github__code_review
  description: prompt.description ?? '',
  isMcp: true,
  source: 'mcp',
  async getPromptForCommand(args: string) {
    const result = await connectedClient.client.getPrompt({
      name: prompt.name,
      arguments: zipObject(argNames, argsArray),
    })
    return result.messages.map(...)
  },
}
```

### 4.4 IDE专用白名单工具

对于IDE集成的MCP服务器，仅允许两个工具：

| 工具名 | 功能 | 安全考虑 |
|---------|------|---------|
| `mcp__ide__executeCode` | 在IDE沙箱中执行代码 | 限制在IDE上下文运行 |
| `mcp__ide__getDiagnostics` | 获取编译错误/类型错误 | 只读操作 |

**设计哲学：** 最小权限原则——IDE集成只需这两个核心能力，不在白名单中的工具根本不会注册，模型甚至不知道它们存在。

---

## 5. 深入调研：MCP调用全流程

### 5.1 模型如何判断用Tool还是MCP？

**模型本身不区分内置Tool和MCP工具。** 从模型的角度看，所有工具（无论内置还是MCP）都以相同的格式出现在API的`tools`数组中。模型根据工具名称、描述和参数Schema来选择最合适的工具。

MCP工具通过`mcp__`前缀在名称上天然可辨，但这只是命名约定，不影响模型的选择逻辑。

### 5.2 MCP工具调用完整流程

```
[模型输出 tool_use block]
     │ { name: "mcp__github__create_issue", input: {...} }
     ▼
[Stage 1] 工具查找
     │ 按name在工具池中匹配 → 找到isMcp:true的Tool对象
     ▼
[Stage 2] 输入验证
     │ MCP工具使用inputJSONSchema（非Zod）进行验证
     ▼
[Stage 3] 并行启动
     │ Pre-Tool Hook ∥ Bash分类器（MCP工具不触发Bash分类器）
     ▼
[Stage 4] 权限检查
     │ MCP工具默认返回passthrough → 每次需要用户确认
     │ 除非用户配置了allow规则：mcp__github__*
     ▼
[Stage 5] MCP工具执行
     │ ensureConnectedClient() → 确保连接仍有效
     │ callMCPToolWithUrlElicitationRetry() → JSON-RPC调用
     │ MCP服务器执行实际操作 → 返回结果
     ▼
[Stage 6] 结果处理
     │ 二进制blob > 25KB → 自动保存到.claude/mcp-outputs/
     │ 文本结果 → mapToolResult处理
     ▼
[Stage 7] Post-Tool Hook
     │ postToolUse / postToolFail
     ▼
[Stage 8] 消息发射
     │ tool_result block → 返回给模型
```

### 5.3 示例模拟全流程

**用户请求：** `"在GitHub上给my-project仓库创建一个关于登录bug的issue"`

**Step 1 - 工具查找：**
模型输出：
```json
{
  "type": "tool_use",
  "name": "mcp__github__create_issue",
  "input": {
    "repo": "my-project",
    "title": "Login bug",
    "body": "Users cannot login with email..."
  }
}
```
系统在工具池中按name匹配，找到`isMcp: true`的Tool对象。

**Step 2 - 输入验证：**
使用MCP服务器提供的JSON Schema验证input结构。

**Step 3 - 权限检查：**
- 检查用户是否配置了`allow: ["mcp__github__*"]` → 如果有，自动允许
- 如果没有 → 弹出确认弹窗，用户选择"允许"/"拒绝"

**Step 4 - MCP工具执行：**
```typescript
// 确保GitHub MCP服务器仍然连接
const connectedClient = await ensureConnectedClient(githubServer)

// 通过JSON-RPC发送tools/call请求
const result = await connectedClient.client.request({
  method: 'tools/call',
  params: {
    name: 'create_issue',  // 原始工具名，不带前缀
    arguments: { repo: "my-project", title: "Login bug", body: "..." }
  }
})
```

**Step 5 - 结果处理：**
MCP服务器返回：
```json
{
  "content": [
    { "type": "text", "text": "Issue #42 created successfully" }
  ]
}
```
结果通过`mapToolResultToToolResultBlockParam()`转换为API格式。

**Step 6 - 消息发射：**
tool_result block返回给模型，模型向用户报告：*"已在my-project仓库创建了Issue #42：Login bug"*

### 5.4 连接断开时的处理

如果在调用MCP工具时连接已断开：

```typescript
async function ensureConnectedClient(client) {
  if (client.type !== 'connected') {
    // 尝试重连
    const reconnected = await connectToServer(client.name, client.config)
    if (reconnected.type !== 'connected') {
      throw new McpToolCallError('MCP server is not connected')
    }
    return reconnected
  }
  return client
}
```

错误会被转换为`tool_result`（带`is_error: true`）返回给模型，模型可以自我纠正。

---

## 6. 深入调研：MCP权限校验与安全审查

### 6.1 四层权限模型

```
┌─────────────────────────────────────────────────┐
│ 第一层：企业策略 Enterprise Policy                  │
│   deniedMcpServers（黑名单，绝对拒绝）              │
│   allowedMcpServers（白名单，不在名单中则拒绝）      │
├─────────────────────────────────────────────────┤
│ 第二层：IDE工具白名单                               │
│   仅允许 executeCode 和 getDiagnostics             │
├─────────────────────────────────────────────────┤
│ 第三层：用户权限配置                                 │
│   allow规则 → 自动允许匹配的工具                     │
│   deny规则 → 自动拒绝匹配的工具                      │
├─────────────────────────────────────────────────┤
│ 第四层：运行时确认                                   │
│   未被任何规则覆盖 → 每次调用弹窗确认                 │
└─────────────────────────────────────────────────┘
```

### 6.2 服务器级安全——连接前拦截

**黑名单（绝对优先级）** 支持三种匹配：

| 匹配方式 | 适用于 | 示例 |
|---------|--------|------|
| 按服务器名称 | 所有类型 | `{ serverName: "dangerous-server" }` |
| 按命令数组 | stdio | `{ serverCommand: ["npx", "mcp-server-evil"] }` |
| 按URL通配符 | 远程服务器 | `{ serverUrl: "https://evil.com/*" }` |

```typescript
// 策略过滤核心逻辑
function filterMcpServersByPolicy(configs) {
  for (const [name, config] of configs) {
    // SDK类型豁免策略检查（进程内，安全由宿主保证）
    if (config.type === 'sdk') { allow; continue }
    
    // 黑名单检查（绝对拒绝）
    if (isMcpServerDenied(name, config)) { block; continue }
    
    // 白名单检查（不在名单中则拒绝）
    if (allowedMcpServers && !isInAllowlist(name, config)) { block; continue }
    
    allow
  }
}
```

### 6.3 工具级安全——调用时检查

MCP工具的权限检查**默认返回passthrough**（每次需要用户确认），这与内置工具的默认行为不同。

用户可以通过配置预授权：
```json
{
  "permissions": {
    "allow": [
      "mcp__github__create_issue",     // 精确匹配
      "mcp__github__*",                // 服务器通配
      "mcp__*"                         // 所有MCP（危险！）
    ]
  }
}
```

### 6.4 签名去重安全

去重基于内容签名而非名称，防止通过换名称绕过安全策略：

```typescript
export function getMcpServerSignature(config): string | null {
  const cmd = getServerCommandArray(config)
  if (cmd) return `stdio:${JSON.stringify(cmd)}`   // 本地：命令+参数
  const url = getServerUrl(config)
  if (url) return `url:${unwrapCcrProxyUrl(url)}`  // 远程：URL
  return null  // SDK不去重
}
```

### 6.5 认证体系

| 认证方式 | 场景 | 特点 |
|---------|------|------|
| **OAuth 2.0 + PKCE** | 远程MCP服务器 | S256 Code Challenge，自动Token刷新 |
| **XAA（Cross-App Access）** | 企业免浏览器 | 两步Token交换，适合CI/CD |
| **headersHelper** | 自定义认证 | Shell脚本返回JSON headers |
| **macOS Keychain** | Token存储 | 安全存储OAuth tokens |

---

## 7. Tool与MCP全流程对比

### 7.1 核心异同对比表

| 维度 | 内置Tool | MCP工具 |
|------|---------|---------|
| **接口** | `Tool<Input,Output,P>` | **相同**——映射为`Tool`接口 |
| **Schema** | Zod inputSchema | inputJSONSchema（MCP返回的JSON Schema） |
| **执行** | 直接调用`call()` | 通过JSON-RPC代理到MCP服务器 |
| **权限默认** | 部分自动允许（如只读工具） | **默认passthrough（每次确认）** |
| **并发标记** | 工具自己声明 | 通过MCP annotations桥接 |
| **命名** | 单一名称（如`FileReadTool`） | 三段式`mcp__server__tool` |
| **发现** | 编译时注册 | 运行时通过`tools/list`动态发现 |
| **可用性** | 始终可用 | **依赖连接状态**（5种状态） |
| **错误处理** | 进程内异常 | 需处理网络错误、认证过期、连接断开 |
| **结果大小** | maxResultSizeChars | 额外处理：二进制blob>25KB自动保存 |
| **延迟加载** | shouldDefer标记 | **MCP工具默认延迟加载** |
| **UI渲染** | 工具自带render方法 | 使用MCPTool的通用渲染 |
| **输入验证** | Zod safeParse + validateInput | JSON Schema验证（无业务验证层） |
| **工具池排序** | 内置工具区（前缀块） | MCP工具区（后缀块，缓存友好） |

### 7.2 执行流水线对比

```
               内置Tool                    MCP工具
               ─────────                    ──────
Stage 1   工具查找(name/alias)          工具查找(mcp__前缀名)
Stage 2   Zod Schema验证              JSON Schema验证
          + validateInput()            (无业务验证层)
Stage 3   Pre-Tool Hook ∥             Pre-Tool Hook ∥
          Bash分类器(仅BashTool)       (无Bash分类器)
Stage 4   权限检查(7源规则)            权限检查(默认passthrough)
Stage 5   tool.call()(进程内)          ensureConnectedClient()
                                       → JSON-RPC tools/call
                                       → 网络/进程间通信
Stage 6   mapToolResult               mapToolResult
                                       + 二进制blob处理
Stage 7   Post-Tool Hook              Post-Tool Hook
Stage 8   消息发射                     消息发射
```

### 7.3 关键差异的设计原因

**为什么MCP默认passthrough而非allow？**
内置工具由Claude Code团队开发和审核，行为可预测。MCP工具来自第三方，行为不可预测、不可控制，必须让用户知情并同意。

**为什么MCP工具用JSON Schema而非Zod？**
MCP协议标准使用JSON Schema描述工具参数。如果要求MCP服务器提供Zod Schema，会破坏协议的语言无关性（Zod是TypeScript库）。

**为什么MCP工具默认延迟加载？**
一个用户可能连接了几十个MCP服务器，每个提供多个工具。如果全部注入system prompt，会消耗大量token。延迟加载只在模型需要时加载，显著节省token。

---

## 8. Agent系统开发的MCP设计参考

### 参考1：统一接口适配——协议差异在桥接层消化

将外部协议（MCP JSON-RPC）适配为内部接口（Tool），在桥接层消化所有差异，上层执行逻辑完全统一。

```typescript
// 桥接模式核心
const mcpTool: Tool = {
  ...MCPTool,                    // 继承基础实现
  name: buildMcpToolName(...),   // 统一命名
  isMcp: true,                   // 标记区分
  async call(args) {
    // 代理到MCP协议
    return await mcpClient.request({ method: 'tools/call', ... })
  },
}
```

### 参考2：两阶段配置加载

将配置加载分为快速本地阶段和慢速网络阶段，两者并行执行，确保启动不被网络请求阻塞。

### 参考3：签名去重

用内容签名（命令行或URL）而非名称判断配置是否重复，解决多来源配置冲突。

### 参考4：本地/远程分治并发

按资源消耗特性分组：本地进程spawn低并发（3），远程网络请求高并发（20），各自使用滑动窗口调度。

### 参考5：Discriminated Union建模连接状态

用`type`字段区分5种连接状态，编译器强制完整处理每种状态，防止遗漏边界情况。

### 参考6：三段式命名空间隔离

`mcp__server__tool`格式在权限检查时提供独立命名空间，防止跨服务器/跨系统的权限混淆。

### 参考7：InProcess传输优化

对内置MCP服务器使用进程内直连（`createLinkedTransportPair`），避免子进程内存开销。

### 参考8：优雅退出的三级信号升级

```
SIGINT → (等100ms) → SIGTERM → (等400ms) → SIGKILL
```
总超时500ms，保持CLI响应性同时给MCP服务器足够清理时间。

### 参考9：needs-auth缓存

对需要认证的服务器维护15分钟TTL缓存，避免每次连接都发起HTTP 401 + OAuth发现的网络往返。

### 参考10：环境变量展开

支持`${VAR}`和`${VAR:-default}`语法，在配置中引用环境变量，避免硬编码敏感信息。

---

## 9. 总结速记表

| 维度 | 要点 | 关键设计 |
|------|------|---------|
| **MCP本质** | AI世界的"USB-C接口" | 标准化协议解决N×M集成问题 |
| **三大原则** | 协议即契约/传输无关/安全内嵌 | 贯穿Claude Code整个MCP实现 |
| **传输协议** | 8种，按场景选择 | stdio首选；远程用SSE/HTTP/WS；SDK零开销 |
| **配置作用域** | 7层，就近覆盖 | enterprise独占；dynamic最高；claudeai最低 |
| **两阶段加载** | Phase1本地+Phase2网络 | 并行执行，启动性能隔离 |
| **统一接口** | MCP工具映射为`Tool`接口 | `isMcp:true`标记区分，共享执行流水线 |
| **三段式命名** | `mcp__server__tool` | 命名空间隔离，权限独立 |
| **权限模型** | 四层深度防御 | 企业策略→IDE白名单→用户配置→运行时确认 |
| **MCP默认权限** | passthrough（每次确认） | 比内置工具更严格，因为第三方不可信 |
| **签名去重** | 基于命令/URL内容 | 防止通过换名称绕过安全 |
| **并发连接** | 本地低并发(3)/远程高并发(20) | pMap滑动窗口替代固定批次 |
| **工具发现** | `tools/list` JSON-RPC | 动态发现+延迟加载+LRU缓存 |
| **行为注解桥接** | Hint→Decision | readOnlyHint→isConcurrencySafe |
| **连接状态** | 5种discriminated union | Connected/Failed/NeedsAuth/Pending/Disabled |
| **错误恢复** | 指数退避自动重连 | 1s→2s→4s...最多30s，最多5次 |
| **认证** | OAuth+PKCE / XAA / headersHelper | Keychain存储，自动刷新 |
| **IDE集成** | sse-ide/ws-ide + 工具白名单 | 仅允许executeCode/getDiagnostics |
| **InProcess传输** | 进程内直连 | 避免325MB子进程开销 |
| **大结果处理** | 二进制blob>25KB自动保存 | `.claude/mcp-outputs/`目录 |
| **延迟加载** | MCP工具默认延迟 | 名称列表→ToolSearch按需加载 |
| **Prompt映射** | MCP Prompts→斜杠命令 | `/mcp__github__code_review` |

---

**一句话总结：** Claude Code的MCP集成通过**统一接口桥接 + 两阶段配置加载 + 8种传输适配 + 四层权限防御 + 签名去重 + 分治并发调度**的组合设计，将外部MCP工具无缝融入内置工具系统，实现了"深度集成+广度扩展"的完美平衡。对于自研Agent系统，最值得借鉴的是：统一接口适配模式、签名去重策略、本地/远程分治并发、以及"默认不信任"的MCP权限哲学。