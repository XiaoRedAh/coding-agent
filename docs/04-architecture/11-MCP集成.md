# MCP 集成

> 讲解 `services/mcp.py`（约 400 行），即项目如何作为 **MCP 客户端** 接入外部 MCP 服务器、把外部工具无缝注入主 Agent 工具池。
> 本文是 `docs/01-research/MCP深度解读.md`（协议原理）与 `cc源码调研/04-cc-MCP集成-v2.md`（CC 设计）在**本项目实现**上的落地对照。

## 目录

- [业界调研：共识、问题与方案](#业界调研)
- [MCP 协议基础：N×M、角色、能力、JSON-RPC、传输方式](#mcp-协议基础)
- [整体架构：两层抽象](#整体架构)
- [工具命名的算法推导](#工具命名)
- [启动命令解析：Windows shim 适配](#命令解析)
- [连接握手的完整流程](#连接握手)
- [通信层的并发设计：超时与防死锁](#通信层并发)
- [工具转换：MCP Tool → Anthropic Tool](#工具转换)
- [handler 闭包与晚绑定规避](#handler闭包)
- [完整模拟：一次 MCP 工具调用](#完整模拟)
- [当前实现的成熟度评估](#成熟度评估)
- [不足与进一步优化方向](#不足与优化方向)
- [附录 · 变更历史](#附录)

## 业界调研

### MCP 在 Agent 领域的定位

**MCP（Model Context Protocol，模型上下文协议）** 是 Anthropic 于 2024-11 发布的开放协议，定义 AI 应用（Client/Host）与外部能力提供者（Server）之间的标准化通信方式。它的核心动机是解决 **N×M 集成问题**：N 个 AI Agent × M 个外部服务，若无标准协议，需要 N×M 套专用集成代码；有了 MCP，每个 Agent 只实现一次 Client、每个服务只实现一次 Server，集成量降为 N+M。

最精确的类比是 **LSP（Language Server Protocol）**——LSP 解决了"N 个 IDE × M 种语言"的问题，MCP 对 AI Agent 做了同样的事：**AI 世界的"USB 接口"**。

### 业界主流共识

以 Claude Code 为标杆（见 `cc源码调研/04-cc-MCP集成-v2.md`），业界对 MCP 集成已形成共识：

1. **统一接口桥接**：MCP 工具被映射为与内置工具相同的接口，共享执行流水线（验证 → 权限 → 执行 → 结果处理）。从模型视角看，`mcp__github__create_issue` 与内置 `read_file` 在 `tools` 数组里并列，无本质区别。
2. **三段式命名**：`mcp__<server>__<tool>`，提供命名空间隔离（不与内置工具冲突）与独立权限粒度（`mcp__github__*` 匹配整个服务器）。
3. **默认不信任第三方**：内置工具由自家团队审核，行为可预测；MCP 工具来自第三方，默认需用户确认（passthrough），而非直接放行。
4. **延迟加载防 token 膨胀**：MCP 可能引入 200+ 工具定义，全量注入 tools 参数消耗数万 token；CC 默认延迟加载（只发名称，`ToolSearch` 按需加载完整 schema），节省约 95%。
5. **协议自描述 + 运行时发现**：Server 通过 `tools/list` 主动告诉 Client"我能做什么"，Agent 无需预知，支持热更新。

### 主要问题与解决方案

| 问题 | 表现 | 业界方案 |
|------|------|----------|
| 工具定义撑爆上下文 | 200+ 工具定义数万 token | 延迟加载 + `ToolSearch` 按需加载 |
| 第三方工具不可信 | MCP 工具可能执行危险操作 | 默认 passthrough + 权限规则 + 运行时确认 |
| 大结果吞掉窗口 | 数据库查询返回大量行 | 截断 + 二进制 blob >25KB 自动落盘 |
| 传输协议碎片化 | 本地/远程/IDE 场景各异 | 7+ 种传输适配（stdio 首选） |
| 配置来源冲突 | 多级配置同名服务器 | 签名去重（按命令/URL 内容，而非名称） |
| 连接失败级联 | Server 崩溃拖垮主循环 | 连接状态机 + 指数退避重连 + 超时 |
| 认证 | 远程 Server 需身份验证 | OAuth 2.1 + PKCE + token 自动刷新 |

### 跨产品视角（超越 CC）

MCP 的特殊之处在于：它本是 Anthropic 提出的协议，却迅速成为**跨厂商事实标准**——这正是"业界共识"最有力的证据：

| 产品/框架 | MCP 支持方式 | 备注 |
|-----------|-------------|------|
| **Claude Code** | 原生深度集成（7+ 传输、4 层权限、延迟加载、OAuth） | 标杆实现 |
| **OpenAI Agents SDK** | 内置 `MCPServerStdio` / `MCPServerSSE` / `MCPServerHTTP`，`session.add_mcp_server()` 一行接入 | 与 CC 相反，走"轻量原语"哲学 |
| **LangChain / LangGraph** | 通过 `langchain-mcp-adapters` 将 MCP 工具转为 LangChain Tool | 桥接到图编排生态 |
| **Cursor / Windsurf** | IDE 内置 MCP 客户端 | 面向终端用户可视化配置 |
| **Aider** | 不内置 MCP，用自研 repomap + 工具 | 少数不跟进的流派 |

**关键洞察**：OpenAI Agents SDK 的 MCP 接入只有三行代码（创建 `MCPServerStdio` → `session.add_mcp_server()` → SDK 自动发现工具），与 CC 的"配置层 + 传输层 + 客户端层 + 权限层"重实现形成鲜明对比。这揭示了 MCP 集成的**两种哲学**：CC 追求"生产级全面控制"（自研 stdio 传输、连接状态机、延迟加载），OpenAI 追求"协议复用"（直接用官方 MCP SDK，自己不造轮子）。本项目走的是 **CC 路线的精简版**（自研 stdio 通信，见下）。

## MCP 协议基础

在深入本项目实现前，先把 MCP 协议本身讲透——它解决了什么问题、由哪些部分组成、有哪些连接方式。这些是理解后续"本项目只实现 stdio 传输 + Tools 能力"的前提。

### N×M 集成问题详解

**问题定义**：设市场上有 N 个 AI Agent（Claude Code、Cursor、Windsurf、自定义 Agent……），M 个外部服务（GitHub、Slack、PostgreSQL、Jira……）。每个 Agent 都想调用这些服务，而每个服务的 API 格式、认证方式、数据结构都不一样。

**引入 MCP 之前**：每个 Agent 团队要为每个外部服务写一套**专用集成代码**。一套集成要处理五件事——API 端点封装、认证（token 管理）、参数校验、错误处理、结果解析。总集成量 = N × M：

```
         GitHub    Slack     PostgreSQL   Jira
Claude   集成 1    集成 2     集成 3      集成 4
Cursor   集成 5    集成 6     集成 7      集成 8
Windsurf 集成 9    集成 10    集成 11     集成 12
自定义    集成 13   集成 14    集成 15     集成 16
```

4 个 Agent × 4 个服务 = **16 套重复的集成代码**。每新增一个 Agent 或服务，集成量线性增长。更糟的是这些代码**互不通用**——Claude Code 的 GitHub 集成对 Cursor 毫无用处，反之亦然，只能各自重写。

**引入 MCP 之后**：协议定义了一个标准中间层。每个 Agent 只实现一次 **MCP Client**，每个服务只实现一次 **MCP Server**，两边通过 MCP 协议互通：

```
Claude   ──┐                          ┌── GitHub Server
Cursor   ──┤                          ├── Slack Server
Windsurf ──┼──→  MCP 协议层  ←────────┼── PostgreSQL Server
自定义    ──┘                          └── Jira Server

       N 个 Client                M 个 Server
       （每个 Agent 实现 1 次）     （每个服务实现 1 次）
```

集成量从 N × M 降为 **N + M**（4 + 4 = 8 次实现，而非 16 次）。更关键的是**边际成本**：

- 新增一个 Agent → 只需实现一次 Client，**立即获得所有已有 Server 的能力**；
- 新增一个服务 → 只需实现一次 Server，**立即被所有已有 Agent 使用**。

**引入前 vs 引入后的逐维度对比**：

| 维度 | 引入 MCP 之前 | 引入 MCP 之后 |
|------|--------------|--------------|
| 集成代码量 | N × M 套 | N + M 套 |
| 新增 Agent 成本 | 为 M 个服务各写一套集成 | 实现 1 次 Client |
| 新增服务成本 | N 个 Agent 各写一套集成 | 实现 1 次 Server |
| 工具发现 | 硬编码工具列表，需读文档 | `tools/list` 运行时自动发现 |
| 认证 | 每个集成自行实现 | 协议内置 OAuth 2.1 |
| 参数校验 | 各自约定 | JSON Schema 统一校验 |
| 错误格式 | 各自定义 | JSON-RPC 统一错误 |
| 代码复用 | 几乎为零（跨 Agent 不可复用） | Server 一次实现，全网复用 |

**一个关键澄清：为什么"对同一个服务"的集成代码不能直接复用？**

你可能会问：GitHub 的 API 格式、认证方式、数据结构是**固定的**（`POST /repos/{owner}/{repo}/issues` 对所有调用者都一样），那 Claude Code 和 Cursor 给 GitHub 写的集成代码，不应该一样吗？

答案是：**"调用 GitHub API"这层逻辑确实一样（甚至能共用官方 SDK），但"把这个能力接入各自 Agent"这层逻辑完全不一样，无法复用。** 一套完整的集成代码实际包含两层：

| 层 | 内容 | 是否可复用 |
|----|------|-----------|
| **服务访问层** | 调 `POST /repos/{owner}/{repo}/issues`、token 管理、结果解析 | ✅ 可复用（官方 SDK 已提供，如 octokit） |
| **Agent 适配层** | 把 create_issue 包装成自己 Agent 的工具、接入自己的权限系统、格式化成自己的返回结构 | ❌ **不可复用**，每个 Agent 各写一遍 |

重复的根源在 **"Agent 适配层"**：

- **编程语言/技术栈不同**：CC 用 TypeScript + Zod，Cursor 用 TypeScript（但内部框架不同），Aider 用 Python——同样的"调 GitHub API"，要用不同语言各写一遍。
- **工具抽象不同**：CC 的工具是 `Tool<Input, Output>` 接口，Cursor 有自己的工具注册机制，Aider 有自己的 dataclass——同一个 create_issue 要适配成各自框架的工具定义格式。
- **权限/安全集成不同**：CC 的权限系统（passthrough 确认）、Cursor 的、Aider 的各自不同——集成要分别接入各自的权限检查逻辑。
- **返回格式不同**：CC 返回 `ToolResult`，别的 Agent 返回字符串/JSON——同样的结果要格式化成各自约定。

所以 N×M 里的"集成"精确指的是**"把服务适配进 Agent"这层**，而非"调 API 的核心逻辑"（那层官方 SDK 已经统一了）。MCP 解决的正是"Agent 适配层"的重复——MCP Server 一次性把 create_issue 封装成**标准化的工具**（name + description + inputSchema + JSON-RPC），任何 Agent 只需实现一次"通用的 MCP Client"（如何把 MCP 工具接入自己的工具系统），就能使用所有 MCP Server 的工具。

**更直观的类比**：同一个插座（GitHub 服务），不同国家的电器（CC/Cursor/Aider）插头标准不同（TypeScript+Zod / 别的框架 / Python），所以每个电器都要配一个"转换器"（适配层）。MCP 相当于定义一个"万能插座标准"——电器端统一插头（实现一次 Client），插座端统一接口（实现一次 Server），于是 N 个电器 + M 个插座只需 N+M 个标准件，而非 N×M 个定制转换器。

**类比**：这正是 **LSP（Language Server Protocol）** 的翻版——LSP 解决了"N 个 IDE × M 种语言"的问题（VS Code、Neovim、Eclipse 各要为 Python、Java、Rust 写语言插件），MCP 把同样的思想搬到 AI Agent 与外部服务之间。所以 MCP 常被称作 **"AI 世界的 USB 接口"**：USB 统一了计算机与各种外设的接口，MCP 统一了 AI Agent 与各种服务的接口。

### MCP 的四大角色

MCP 的完整架构由四个角色组成，各有明确边界：

```
用户 ── Host（宿主应用）── Client1 ── Server1 ── Data Source1
                │           Client2 ── Server2 ── Data Source2
                │           Client3 ── Server3 ── Data Source3
```

| 角色 | 是什么 | 职责 | 类比 |
|------|--------|------|------|
| **Host** | 用户交互的 AI 应用（Claude Code、Cursor、本项目） | 提供 UI/CLI、管理 Client 生命周期、集成 LLM、合并工具、处理用户确认 | 浏览器 |
| **Client** | Host 内的 MCP 协议实现模块 | 与**一个** Server 保持 1:1 连接、握手、发现能力、转发 tool call | HTTP Client |
| **Server** | 提供具体能力的程序 | 实现协议服务器侧、暴露 Tools/Resources/Prompts、翻译协议 ↔ 数据源原生协议 | Web Server |
| **Data Source** | Server 连接的真实后端 | GitHub API、数据库、本地文件系统…… | 数据库/API |

**三个关键理解**：

1. **Client 是 Host 内部的组件**，不是独立程序——用户不与 Client 直接交互，用户面对的是 Host。本项目里 `McpManager` 就是 Host 侧的 Client 管理器，`McpConnection` 就是单个 Client。
2. **一个 Host 可以管理多个 Client**，每个 Client 对应一个 Server，1:1 连接（隔离性：一个崩溃不影响其他；安全性：不同 Server 的 env 彼此隔离）。
3. **Server 是"翻译层"**——它一侧说 MCP 协议（与 Client 通信），另一侧说具体服务的原生协议（REST API / SQL / 文件 I/O）。Server 不知道"是谁在调它"，也不关心。

### MCP 的三大能力

MCP Server 可以向 Client 暴露三种能力，本项目只实现了 Tools：

| 能力 | 是什么 | 触发方式 | 有无副作用 | 类比 |
|------|--------|----------|-----------|------|
| **Tools（工具）** | AI 可调用的函数，由 name + description + inputSchema 定义 | 模型自主决定调用 | 可能有 | 函数 / API 端点 |
| **Resources（资源）** | 只读数据，用 URI 标识 | 应用按需读取 | 无 | 文件 / 数据库记录 |
| **Prompts（提示模板）** | 可复用的交互模板 | 用户主动选择 | 无 | 操作手册 |

**三者的本质区别**：Tools 是"动作"（模型说"我要创建 issue"），Resources 是"数据"（模型说"我要读这个 schema"），Prompts 是"流程"（用户说"用代码审查模板"）。以官方 GitHub Server 为例：Tools = create_issue / list_pulls / merge_pr，Resources = repo 文件内容，Prompts = code_review 模板。

**为什么本项目只做 Tools**：绝大多数 MCP Server 的核心价值都在 Tools（让 Agent 能"动手做事"），Resources/Prompts 是增强能力。精简版先覆盖最常用的 Tools，Resources/Prompts 留作优化方向（见下文"不足与优化方向"第 4 条）。

### 底层协议：JSON-RPC 2.0

MCP 的消息格式基于 **JSON-RPC 2.0**（一个不到 3 页的极简规范，LSP 也用它）。选择它而非 REST/gRPC 的原因：**传输无关**（同一套消息可走 stdio/HTTP/WebSocket）、极简、JSON 原生、支持通知。

三种消息类型：

| 类型 | 特征 | 用途 | 示例 |
|------|------|------|------|
| **Request** | 有 `id` 字段，期望响应 | 需要结果的操作 | `initialize`、`tools/list`、`tools/call` |
| **Response** | 带相同的 `id`，含 `result` 或 `error` | 对 Request 的回复 | 工具执行结果 |
| **Notification** | **无 `id`** 字段，不期望响应 | 单向通知 | `notifications/initialized`、`notifications/tools/list_changed` |

```json
// Request（有 id）
{ "jsonrpc": "2.0", "id": 1, "method": "tools/call",
  "params": { "name": "get_sum", "arguments": { "a": 2, "b": 3 } } }

// Response（成功，带相同 id + result）
{ "jsonrpc": "2.0", "id": 1,
  "result": { "content": [{ "type": "text", "text": "The sum of 2 and 3 is 5." }] } }

// Response（失败，带相同 id + error）
{ "jsonrpc": "2.0", "id": 1,
  "error": { "code": -32602, "message": "Invalid params" } }

// Notification（无 id，无响应）
{ "jsonrpc": "2.0", "method": "notifications/initialized", "params": {} }
```

**关键洞察**：`id` 是"请求-响应匹配"的唯一依据——Client 发出带 id 的请求后，在响应流里找 `id` 相同的那条。这正是本项目 `_send_request` 里 `if response.get("id") == self.request_id` 那一行的协议根源。而**没有 `id` 的消息是通知，跳过不响应**——`_send_request` 里 `if "id" not in response: continue` 就是这个语义。

### 传输方式的详解与对比

MCP 的"连接方式"指的是协议消息通过什么物理通道传输。协议本身传输无关，规范定义了多种传输，本项目只实现了 stdio。

**传输一：stdio（标准输入输出）**

Server 作为**子进程**被 Client 启动，双方通过进程的 stdin/stdout 交换 JSON-RPC 消息（一行一条，`\n` 分隔）：

```
Client 进程                 Server 子进程
  │ 写 stdin ────────────────→ 读 stdin
  │ 读 stdout ←─────────────── 写 stdout
  │ 读 stderr ←─────────────── 写日志/进度（stderr 不进协议）
```

工作流程：

```
1. Client 启动 Server 子进程（如 npx -y @modelcontextprotocol/server-github）
2. Client 写 initialize 请求 → stdin
3. Server 读 stdin，写 initialize 响应 → stdout
4. Client 写 notifications/initialized 通知 → stdin
5. Client 写 tools/list → stdin，Server 回工具列表 → stdout
6. Client 写 tools/call → stdin，Server 执行 → 结果回 stdout
```

这是本项目唯一实现的传输，也是最简单、最可靠的——基于操作系统管道，不涉及网络，每个 Server 是独立进程（崩溃不影响 Host）。代价是**只能本地运行**（Server 必须在本地，依赖本地装好 Node/Python 等运行环境）。

**传输二：Streamable HTTP（HTTP + SSE）**

Server 作为 **HTTP 服务**运行，Client 通过 HTTP POST 发送请求，通过 Server-Sent Events（SSE）接收流式响应和服务器推送：

```
Client ── POST /mcp（JSON-RPC 请求）──→ Server（HTTP 服务）
Client ←── SSE 流（响应 + 服务器推送）── Server
```

工作流程：

```
1. Client GET /mcp（Accept: text/event-stream）建立 SSE 连接（用于接收推送）
2. Client POST /mcp 发 initialize 请求 → Server 回 200 + result
3. Client POST /mcp 发 tools/list → Server 回工具列表
4. Client POST /mcp 发 tools/call → Server 通过 SSE 流式返回进度 → 最终 result
5. Server 可随时通过 SSE 主动推送 notifications/tools/list_changed
```

支持远程部署、多用户共享、流式响应，但需要 HTTP 基础设施（域名/TLS/负载均衡）、有网络延迟、需要额外认证（OAuth 2.1）。适合远程 MCP 服务、SaaS 集成、企业多用户部署。

**传输三：WebSocket**

通过 WebSocket 建立全双工持久连接，Client 和 Server 可随时互发消息。适合需要高频双向通信的场景（如实时协作），但需要 WebSocket 基础设施、连接管理复杂（心跳/重连）。

**传输四：SDK（进程内直连）**

MCP Server 不是独立进程，而是**同一进程内的函数**，通过内存管道直连。零额外开销（对比 stdio 每个 Server 一个子进程约 325MB Node 运行时），但 Server 代码与 Host 同进程（隔离性最弱）。适合内置服务器（如 CC 的 Chrome MCP）。

**四种传输的对比总结**：

| 维度 | stdio | Streamable HTTP | WebSocket | SDK |
|------|-------|-----------------|-----------|-----|
| Server 运行位置 | 本地子进程 | 远程 HTTP 服务 | 远程/本地 | 进程内 |
| 复杂度 | 最低 | 中 | 中高 | 最低 |
| 延迟 | 最低（无网络） | 网络延迟 | 网络延迟 | 近零 |
| 隔离性 | 好（独立进程） | 中 | 中 | 弱（同进程） |
| 远程访问 | ✗ | ✓ | ✓ | ✗ |
| 多用户共享 | ✗ | ✓ | ✓ | ✗ |
| 流式响应 | ✗ | ✓（SSE） | ✓ | ✓ |
| 认证需求 | 无（本地） | OAuth | OAuth | 无 |
| 适用场景 | 本地工具、CLI Agent | SaaS 集成、企业部署 | 实时协作 | 内置服务器 |

**决策树**：本地工具 → stdio；远程服务 → Streamable HTTP；需要双向实时 → WebSocket；内置服务器 → SDK。

**本项目为何只做 stdio**：`mcp.json.example` 里的 filesystem/github 服务器都是本地 `npx` 启动，stdio 覆盖了"本地开发工具"这个最常用场景。远程传输（Streamable HTTP）留作优化方向（见"不足与优化方向"第 2 条）。

## 整体架构

`services/mcp.py` 采用**两层抽象**，与 CC 的"配置-传输-客户端三层"相比，把"传输"与"客户端"合并进了 `McpConnection`：

```
McpManager（管理器：管理所有服务器连接）
├── load_and_connect()      # 读配置 → 逐个建立连接
├── get_tool_definitions()  # 所有 MCP 工具 → Anthropic Tool 格式
├── get_tool_handlers()     # 所有 MCP 工具 → 处理函数映射
├── get_instructions()      # 收集 instructions → system prompt 片段
└── close_all()             # 优雅关闭所有连接

McpConnection（单连接：与一个 MCP 服务器 1:1）
├── connect()               # 启动子进程 + initialize 握手 + tools/list
├── call_tool()             # tools/call 转发
├── _send_request()         # JSON-RPC 请求（带超时）
├── _send_notification()    # JSON-RPC 通知（无响应）
├── _read_stdout_loop()     # 后台线程读 stdout → 响应队列
├── _read_stderr_loop()     # 后台线程消费 stderr（防死锁）
└── close()                 # 终止子进程
```

**为什么 1:1 连接而非 1:N**：每个 `McpConnection` 对应一个服务器子进程，隔离性（一个崩溃不影响其他）、简单性（每个连接只维护一个状态）、安全性（不同服务器的 env 彼此隔离）。

## 工具命名

MCP 工具的全名是三段式 `mcp__<server>__<tool>`。核心在 `_normalize_name`：

```python
def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")

def build_mcp_tool_name(server_name, tool_name):
    return f"mcp__{_normalize_name(server_name)}__{_normalize_name(tool_name)}"

def parse_mcp_tool_name(full_name):
    if not full_name.startswith("mcp__"):
        return None
    parts = full_name[5:].split("__", 1)   # 只按第一个 __ 切分
    ...
```

**推导关键点**：

1. **为什么正则用 `[^a-zA-Z0-9]+`（含下划线折叠）而非 `[^a-zA-Z0-9_]`**：`parse_mcp_tool_name` 用 `__` 做分隔符。如果 `_normalize_name` 保留下划线，那么服务器名 `my__server` 会被原样保留，`build` 后得到 `mcp__my__server__tool`，`parse` 用 `split("__", 1)` 会错误切成 `("my", "server__tool")`。用 `[^a-zA-Z0-9]+` 把**连续的非字母数字字符（含下划线）折叠成单个下划线**，从源头消除双下划线歧义。这正是 CC 的 `sanitizeForToolName` 思路，本项目补上了"下划线折叠"这个 CC 里也容易踩的细节。

2. **为什么 `split("__", 1)` 限制为 1 次**：工具名本身可能含单下划线（如 `get_sum`），`split("__", 1)` 只在第一个 `__` 处切一次，`parts[1]` 是剩余全部（含下划线），不会被切碎。

## 命令解析

MCP 服务器通常用 `npx` 启动（如 `npx -y @modelcontextprotocol/server-github`）。`_build_command` 处理一个 Windows 特有的坑：

```python
def _build_command(self):
    if os.name == "nt":
        resolved = shutil.which(self.command)
        if resolved and resolved.lower().endswith((".cmd", ".bat")):
            return subprocess.list2cmdline([resolved] + self.args), True
    return [self.command] + self.args, False
```

**推导为什么需要这个分支**：Windows 下 `npx`/`npm`/`yarn` 是 `.cmd`/`.bat` shim（真正执行的是 `node.exe`）。`subprocess.Popen(["npx", ...])` 走 `CreateProcess`，无法直接执行 `.cmd` 文件，会报 `WinError 2: 系统找不到指定的文件`。所以检测到命令解析为 `.cmd`/`.bat` 时，改用 `shell=True` 交给 `cmd.exe` 解析；而 `python.exe`、`node.exe` 这类真实可执行文件保持 `shell=False`，避免 shell 注入与转义问题。`list2cmdline` 负责把列表转成 `cmd.exe` 能正确解析的引用串（含空格路径如 `C:\Program Files\nodejs\npx.cmd`）。

## 连接握手

`connect()` 的完整流程（MCP 协议的标准生命周期）：

```text
步骤 1  启动子进程：Popen([command]+args, stdin/stdout/stderr=PIPE,
                        encoding="utf-8", errors="replace")
步骤 2  启动两个后台线程：
        stdout 读取线程 → 持续 readline 投递到响应队列
        stderr 消费线程 → 持续 readline 丢弃（防管道死锁）
步骤 3  initialize 请求（timeout=connect_timeout）
        失败 → close() + return False
步骤 4  提取 instructions（init_result["instructions"]）
步骤 5  notifications/initialized 通知（无响应）
步骤 6  tools/list 请求（timeout=connect_timeout）
        失败或无 "tools" 字段 → close() + return False
步骤 7  保存 self.tools → return True
```

**推导三个关键设计**：

1. **`encoding="utf-8", errors="replace"`**：MCP JSON-RPC 是 UTF-8，但中文 Windows 的 `Popen(text=True)` 默认用 GBK 解码子进程输出。若服务器返回含 UTF-8 特殊字符（如 `server-everything` 的响应），GBK 解码直接抛 `UnicodeDecodeError`，stdout 读取线程崩溃，客户端永远收不到响应（表现为"超时"）。显式指定 `utf-8` + `replace` 兜底。

2. **`tools/list` 失败即连接失败**：如果服务器握手成功但 `tools/list` 返回 None（不支持或出错），旧实现仍 `return True`，会注册一个**零工具的空连接**——模型看不到任何工具，但进程和连接资源仍被占用。改为失败即 `close() + return False`。

3. **失败路径自清理**：`connect()` 的每个失败分支（`init_result is None`、`tools_result is None`、异常）都统一 `self.close()` 再返回，不再依赖外层 `load_and_connect` 的 `else: conn.close()` 兜底——"失败自清理"是连接的自身契约，而非调用方的责任。

## 通信层并发

这是本项目 MCP 实现里最值得讲的部分——它解决了两个会让**整个主循环卡死**的隐患。详细原理见 `10-并发与消息传递.md`，这里聚焦"为什么这么设计"。

### 超时：stdout 读取线程 + 队列

`_send_request` 不能再阻塞 `readline()`（MCP 挂起会永久卡死主循环），改为：

```python
def _send_request(self, method, params, timeout=None):
    with self._lock:
        ...写请求到 stdin...
        timeout = MCP_TOOL_TIMEOUT if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None           # 超时返回 None，不阻塞
            try:
                line = self._response_queue.get(timeout=remaining)
            except queue.Empty:
                return None           # 超时返回 None
            ...解析 line，按 request_id 匹配...
```

**推导为什么需要独立 stdout 读取线程**：`readline()` 是阻塞的，无法给它加超时（Windows 下 `select` 不适用于管道）。所以让一个**后台线程**专做阻塞的 `readline()`，把读到的行投进 `queue.Queue`；主线程在 `queue.get(timeout=...)` 上等，就能实现超时。这是"**阻塞读下沉到线程 + 队列中转 + 带超时的消费**"三段式，把"不能超时的阻塞 IO"转化成"能超时的队列等待"。

**推导超时语义**：连接阶段用 `MCP_CONNECT_TIMEOUT`（30s），调用阶段用 `MCP_TOOL_TIMEOUT`（120s）。超时返回 `None` → `call_tool` 转成 `{"isError": True, ...}` → handler 转成 `ToolResult.failure` → 循环层按"工具错误"处理，模型看到错误后可自行换策略。

### 防死锁：stderr 消费线程

```python
def _read_stderr_loop(self):
    stream = self.process.stderr
    while True:
        chunk = stream.readline()
        if not chunk:
            break
    # 静默丢弃（stderr 是日志，不进协议）
```

**推导为什么 stderr 不消费会死锁**：`Popen(stderr=PIPE)` 分配了一个 64KB 的管道缓冲区。MCP 服务器（尤其 `npx` 首次下载）会往 stderr 写日志/进度；若客户端从不读 stderr，写满 64KB 后子进程的 `write` 阻塞 → 服务器卡住 → 反过来触发上面的超时。这是经典的**管道死锁**。启动一个 daemon 线程持续 `readline()` 消费，管道永远不会写满。

## 工具转换

`get_tool_definitions()` 把 MCP 工具转成 Anthropic Tool 格式：

```python
def get_tool_definitions(self):
    defs = []
    for server_name, conn in self.connections.items():
        for tool in conn.tools:
            full_name = build_mcp_tool_name(server_name, tool["name"])
            desc = tool.get("description", "")
            if len(desc) > 2048:
                desc = desc[:2045] + "..."
            defs.append({
                "name": full_name,
                "description": f"[MCP: {server_name}] {desc}",
                "input_schema": tool.get("inputSchema", {...}),
            })
    return defs
```

**推导两个细节**：

1. **描述截断 2048 字符**：防止 OpenAPI 自动生成的 MCP 服务器倾倒 15-60KB 的 API 文档（CC 同样的 `MAX_MCP_DESCRIPTION_LENGTH = 2048`）。截断后附 `...`。

2. **描述加 `[MCP: server]` 前缀**：模型在 tools 数组里看到大量工具时，前缀让它一眼识别"这个工具来自哪个 MCP 服务器"，降低混淆。

## handler 闭包

`get_tool_handlers()` 用**工厂函数 + 默认参数**规避 Python 闭包晚绑定：

```python
def get_tool_handlers(self):
    handlers = {}
    for server_name, conn in self.connections.items():
        for tool in conn.tools:
            full_name = build_mcp_tool_name(server_name, tool["name"])
            def make_handler(c, tn):
                def handler(**kwargs):
                    result = c.call_tool(tn, kwargs)
                    ...
                return handler
            handlers[full_name] = make_handler(conn, tool["name"])
    return handlers
```

**推导为什么必须用 `make_handler(c, tn)` 工厂**：如果直接写 `lambda **kw: conn.call_tool(tool["name"], kw)`，闭包捕获的是**循环变量 `conn` 和 `tool`**，循环结束后它们指向最后一次迭代的值——所有 handler 都会错误地调用最后一个服务器的最后一个工具。`make_handler(c, tn)` 的形参 `c`/`tn` 在每次调用时创建新的局部作用域，把当前值"冻结"进闭包，规避晚绑定。这与 08 文档子 Agent 的 handler 工厂是同一个设计决策。

## 完整模拟

设 `mcp.json` 配置了一个官方服务器：

```json
{ "mcpServers": { "everything": {
    "command": "npx", "args": ["-y", "@modelcontextprotocol/server-everything"] } } }
```

启动时 `load_and_connect()` 的完整流转（真实可复现，`server-everything` 提供 13 个工具）：

```
[启动]
  load_and_connect()
    → 读 mcp.json → 遍历 mcpServers
    → McpConnection("everything", "npx", ["-y", "@modelcontextprotocol/server-everything"])

  conn.connect()
    → _build_command(): Windows 下 which("npx") = "...\npx.CMD" → shell=True
    → Popen(...) 启动子进程（stderr 打印 "Starting default (STDIO) server..."）
    → 启动 stdout/stderr 两个 daemon 线程
    → _send_request("initialize", {...}, timeout=30)
        → 写 {"jsonrpc":"2.0","id":1,"method":"initialize",...}
        → 响应队列取出 {"id":1,"result":{serverInfo, capabilities}}
    → 提取 instructions（若服务器提供）
    → _send_notification("notifications/initialized", {})
    → _send_request("tools/list", {}, timeout=30)
        → 响应 {"id":2,"result":{"tools":[echo, get-sum, ...13 个]}}
    → print "[mcp:everything] connected, 13 tools available"
    → 存入 mgr.connections["everything"]

[工具注入]
  context/builder.py 合并：
    get_tool_definitions() → 13 个工具转 Anthropic 格式
      mcp__everything__echo / mcp__everything__get_sum / ...
    get_instructions() → "# MCP Server Instructions\n\n## everything\n..."

[用户请求：帮我算 2+3]
  主循环调 LLM（tools 含 mcp__everything__get_sum）
  模型返回 tool_use: mcp__everything__get_sum {a: 2, b: 3}
  循环层查 handler → make_handler(everything_conn, "get_sum")
    → conn.call_tool("get_sum", {a:2, b:3})
      → _send_request("tools/call", {name:"get_sum", arguments:{a:2,b:3}}, timeout=120)
        → 写 {"id":3,"method":"tools/call",...}
        → 响应 {"id":3,"result":{"content":[{"type":"text","text":"The sum of 2 and 3 is 5."}]}}
    → handler 提取 text → "The sum of 2 and 3 is 5."
  循环层把结果作为 tool_result 回填给 LLM
  模型："2+3 等于 5。"

[关闭]
  main.py finally → close_all() → 每个 conn.close()（关 stdin → terminate → wait）
```

**超时场景的模拟**：若 `get_sum` 是个永不响应的工具（如自包含测试服务器的 `hang` 工具），`_send_request` 在 120s 后 `queue.Empty` 返回 `None` → `call_tool` 返回 `{"isError": True, ...}` → handler 返回 `ToolResult.failure(..., "mcp_error")` → 循环层按工具错误计数处理，模型看到 `<error>` 后可换策略。**关键：不再永久卡死主循环。**

## 成熟度评估

对照业界共识与 CC 能力，逐条评估：

| 能力 | 本项目 | 成熟度 |
|------|--------|--------|
| stdio 传输 | ✅ 自研（启动子进程 + JSON-RPC over stdin/stdout） | 高 |
| 统一接口桥接（MCP 工具 → 工具池） | ✅ get_tool_definitions/handlers 与内置工具并列 | 高 |
| 三段式命名 `mcp__server__tool` | ✅ + 下划线折叠防歧义 | 高 |
| 工具发现 `tools/list` | ✅ | 高 |
| 描述截断 2048 | ✅ | 高（对齐 CC） |
| instructions 注入 | ✅ 拼进 system prompt 动态区 | 高 |
| 调用超时 + stderr 防死锁 | ✅（2026-09-07 修复） | 高（对齐项目其它模块标准） |
| Windows 兼容（.cmd shim + UTF-8） | ✅（2026-09-07 修复） | 高 |
| 失败自清理 | ✅（2026-09-07 修复） | 高 |
| 可测试性（真实服务器 + 自包含服务器） | ✅ 集成测试 9 项 | 高 |
| 延迟加载（ToolSearch） | ❌ 无，全量注入 | 低 |
| 多传输协议（SSE/HTTP/WS） | ❌ 仅 stdio | 低 |
| OAuth 认证 | ❌ 无 | - |
| 自动重连/重试 | ❌ 无（超时即失败） | 低 |
| Resources / Prompts 支持 | ❌ 仅 Tools | 低 |
| 多配置来源 + 签名去重 | ❌ 单层 mcp.json | 低 |
| MCP 专属权限分级 | ⚠️ 走统一权限层（无 passthrough 默认） | 中 |

**总体判断**：核心"stdio 传输 + 工具发现 + 工具转换 + 命名 + instructions 注入"已完整实现并对齐 CC 精简版，且经过 2026-09-07 的 bug 修复补齐了"超时/死锁/Windows 兼容/自清理"四块健壮性短板，**通信层的成熟度已对齐项目其它模块**；差距集中在"高级能力"（延迟加载、多传输、OAuth、Resources/Prompts、重连）——这些是 CC 生产级的深水区，本项目作为精简版暂未覆盖。

## 不足与优化方向

1. **无延迟加载（最优先）**：所有 MCP 工具定义全量注入 `tools` 参数。CC 实测：200 工具全量 ≈ 40K token，延迟加载 ≈ 1K token（节省 95%）。工具少时无感，接入多个服务器后 system prompt 会显著膨胀。可引入 `shouldDefer` + `ToolSearch` 元工具，或至少"只发名称 + 按需加载 schema"。

2. **仅支持 stdio 传输**：CC 支持 7 种（stdio/sse/http/ws/sdk 等），本项目只有 stdio。stdio 覆盖了最常用的本地场景，但远程 MCP 服务（SaaS 集成、企业部署）需要 HTTP/SSE。可先补 Streamable HTTP 传输。

3. **无自动重连与重试**：MCP 工具调用失败（超时/断连）直接返回 error，无重试。对比 LLM 层有分类重试、指数退避，MCP 层裸奔。可复用 09 文档的退避算法，对"连接断开"类错误做指数退避重连。

4. **无 Resources / Prompts 支持**：MCP 三大能力只做了 Tools。Resources（只读数据）和 Prompts（交互模板）暂缺。CC 用 `ListMcpResourcesTool`/`ReadMcpResourceTool` 桥接 Resources、把 Prompts 映射为斜杠命令。对"数据库 schema 注入"这类场景有价值。

5. **无 OAuth 认证**：远程 MCP 服务器需要 OAuth 2.1 认证，本项目只有 API key 模式的 stdio 本地服务器。若未来支持远程传输，需补 OAuth 流程。

6. **配置来源单一**：只有 `PROJECT_DIR/mcp.json` 一层，无 CC 的 6 层来源 + 企业策略 + 签名去重。多租户/企业场景需要"禁用某些服务器"的管控能力。

7. **MCP 工具权限未走"默认确认"**：CC 对 MCP 工具默认 passthrough（第三方不可信，每次确认），本项目 MCP 工具走统一权限层，但 `load_skill`/工具调用默认无 MCP 专属的"来源信任分级"。可给 MCP 工具默认加一层"首次使用确认"。

## 附录

### 变更历史（2026-09-07：MCP 模块 bug 修复）

本轮对 `services/mcp.py` 做了 7 处修复（前 5 个是审查发现，后 2 个是"找真实服务器测试"时暴露），并补齐了真实服务器测试：

| # | 问题 | 修复 |
|---|------|------|
| 1 | 超时配置完全失效（`readline()` 无超时，MCP 挂起永久卡死主循环） | 独立 stdout 读取线程 + `queue.get(timeout)`，连接/调用分别用 `connect_timeout`/`tool_timeout` |
| 2 | stderr 管道死锁（`stderr=PIPE` 从不读） | 增加 stderr 消费 daemon 线程 |
| 3 | `tools/list` 失败仍算连接成功（注册零工具空连接） | 失败即 `close() + return False` |
| 4 | 双下划线解析冲突（`my__server` 与分隔符混淆） | `_normalize_name` 折叠连续非字母数字字符 |
| 5 | `connect()` 失败进程残留 | 所有失败路径统一自清理 |
| 6 | Windows npx `.cmd` shim 无法执行（`WinError 2`） | `_build_command` 检测 `.cmd/.bat` 用 `shell=True` |
| 7 | UTF-8 解码崩溃（GBK 默认解码 → 读取线程崩溃 → 表现为超时） | `Popen(encoding="utf-8", errors="replace")` |

**测试资产**（`tests/integration/test_mcp_live.py` + `tests/fixtures/mcp_echo_server.py`）：
- 官方 `@modelcontextprotocol/server-everything`：连接 + 13 工具发现 + `echo`/`get-sum` 端到端
- 自包含 Python MCP 服务器：`echo`/`add`/`hang`（超时）/`flood_stderr`（死锁防护）
- 9 项集成测试 + 24 项单元测试 + `eval_mcp.py` 36/36 全部通过

### 对应代码

- `services/mcp.py` — MCP 集成全部实现（本模块）
- `mcp.json.example` — 配置示例（filesystem/github/disabled-example）
- `config/defaults.yaml` 的 `mcp` 节 — `tool_timeout`/`connect_timeout`
- `context/builder.py` — 将 MCP 工具定义/instructions 合并进上下文
- `tests/integration/test_mcp_live.py` — 真实服务器集成测试
- `tests/fixtures/mcp_echo_server.py` — 自包含测试服务器
