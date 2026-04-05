# MCP（Model Context Protocol）深度解读

> 本文档是对 MCP 协议的全面深度解析，面向希望深入理解 AI Agent 与外部服务通信机制的开发者。
> 撰写日期：2026 年 4 月

---

## 目录

1. [MCP 诞生的背景与动机](#1-mcp-诞生的背景与动机)
2. [MCP 架构详解](#2-mcp-架构详解)
3. [底层协议：JSON-RPC 2.0](#3-底层协议json-rpc-20)
4. [传输方式详解](#4-传输方式详解)
5. [MCP 三大核心能力](#5-mcp-三大核心能力)
6. [协议生命周期与状态机](#6-协议生命周期与状态机)
7. [如何开发 MCP Server](#7-如何开发-mcp-server)
8. [作为 Agent 开发者如何集成 MCP](#8-作为-agent-开发者如何集成-mcp)
9. [安全模型与认证机制](#9-安全模型与认证机制)
10. [MCP 实际落地的挑战与解决方案](#10-mcp-实际落地的挑战与解决方案)
11. [常见疑惑深度解答](#11-常见疑惑深度解答)
12. [MCP 生态全景](#12-mcp-生态全景)
13. [MCP 与其他协议的对比](#13-mcp-与其他协议的对比)
14. [实战案例：从零构建完整 MCP 系统](#14-实战案例从零构建完整-mcp-系统)
15. [总结与展望](#15-总结与展望)

---

## 1. MCP 诞生的背景与动机

### 1.1 AI Agent 面临的"连接问题"

当代 AI Agent（如 Claude Code、Cursor、Windsurf、GitHub Copilot）不再是简单的"聊天机器人"。它们需要**与真实世界交互**——读写文件、查询数据库、调用 API、发送消息、管理项目。

然而，每个 Agent 要访问的外部服务种类繁多：

- **代码托管**：GitHub、GitLab、Bitbucket
- **项目管理**：Jira、Linear、Notion
- **通信工具**：Slack、Discord、Email
- **数据库**：PostgreSQL、MySQL、MongoDB、Redis
- **云服务**：AWS、GCP、Azure
- **文件系统**：本地文件、Google Drive、S3
- **搜索引擎**：Brave Search、Google Search
- **监控系统**：Sentry、Datadog、PagerDuty

**没有 MCP 之前**，开发者面临三种不理想的方案：

**方案 A：在 Agent 内硬编码 API 调用**

每个 Agent 团队为每个外部服务编写专用的集成代码。Claude Code 要用 GitHub？写一套 GitHub API 封装。Cursor 也要用 GitHub？再写一套。这导致了严重的重复开发。

**方案 B：让 LLM 通过 Shell 命令调用 API**

直接让 AI 生成 `curl` 命令去调用 API。这种方式不安全（API 密钥可能暴露在命令中）、不可靠（缺乏类型校验）、不标准（每次调用格式不同）。

**方案 C：构建自定义插件系统**

如 ChatGPT Plugins、GPTs 的 Actions。每个 AI 平台定义自己的插件规范，服务提供者需要为每个平台适配，本质上只是把问题换了一个层面。

### 1.2 N×M 问题

这是理解 MCP 动机的关键。假设有 N 个 AI Agent，M 个外部服务：

```mermaid
graph TB
    subgraph "N×M 问题（没有 MCP）"
        A1[Claude Code] -->|专用集成| S1[GitHub]
        A1 -->|专用集成| S2[Slack]
        A1 -->|专用集成| S3[PostgreSQL]
        A1 -->|专用集成| S4[Jira]
        
        A2[Cursor] -->|专用集成| S1
        A2 -->|专用集成| S2
        A2 -->|专用集成| S3
        A2 -->|专用集成| S4
        
        A3[Windsurf] -->|专用集成| S1
        A3 -->|专用集成| S2
        A3 -->|专用集成| S3
        A3 -->|专用集成| S4
        
        A4[自定义 Agent] -->|专用集成| S1
        A4 -->|专用集成| S2
        A4 -->|专用集成| S3
        A4 -->|专用集成| S4
    end
    
    style A1 fill:#e1f5fe
    style A2 fill:#e1f5fe
    style A3 fill:#e1f5fe
    style A4 fill:#e1f5fe
    style S1 fill:#fff3e0
    style S2 fill:#fff3e0
    style S3 fill:#fff3e0
    style S4 fill:#fff3e0
```

4 个 Agent × 4 个服务 = **16 个专用集成**。每增加一个 Agent 或服务，集成数量线性增长。

**各方案的问题总览**：

| 方案 | 问题 |
|------|------|
| 硬编码 API | 每个 Agent 重复开发，维护成本 O(N×M)，代码不可复用 |
| curl/HTTP | 不安全（密钥暴露）、无类型校验、无发现机制、依赖 Shell 环境 |
| 自定义插件 | 每个 Agent 的插件格式不同，服务提供者需要为每个 Agent 适配，碎片化严重 |

### 1.3 MCP 的 N+M 解决方案

MCP 引入了一个**标准化的中间协议层**，将 N×M 问题降维为 N+M：

```mermaid
graph TB
    subgraph "N+M 解决方案（有 MCP）"
        A1[Claude Code] -->|MCP 协议| MCP((MCP 协议层))
        A2[Cursor] -->|MCP 协议| MCP
        A3[Windsurf] -->|MCP 协议| MCP
        A4[自定义 Agent] -->|MCP 协议| MCP
        
        MCP -->|MCP 协议| S1[GitHub Server]
        MCP -->|MCP 协议| S2[Slack Server]
        MCP -->|MCP 协议| S3[PostgreSQL Server]
        MCP -->|MCP 协议| S4[Jira Server]
    end
    
    style A1 fill:#e1f5fe
    style A2 fill:#e1f5fe
    style A3 fill:#e1f5fe
    style A4 fill:#e1f5fe
    style MCP fill:#c8e6c9
    style S1 fill:#fff3e0
    style S2 fill:#fff3e0
    style S3 fill:#fff3e0
    style S4 fill:#fff3e0
```

- 每个 Agent 只需实现一次 MCP Client 协议
- 每个服务只需实现一次 MCP Server 协议
- 4 个 Agent + 4 个服务 = **8 次实现**（而非 16 次）
- 新增一个 Agent？只需实现 MCP Client，立即获得所有 MCP Server 的能力
- 新增一个服务？只需实现 MCP Server，立即被所有 MCP Client 使用

### 1.4 MCP 是什么？

**MCP = Model Context Protocol**（模型上下文协议）

由 Anthropic 于 **2024 年 11 月**公开发布的开放协议。它定义了 AI 应用（Host/Client）与外部能力提供者（Server）之间的标准化通信方式。

**核心类比**：

| 类比对象 | 统一了什么 | MCP 类比 |
|----------|-----------|----------|
| **HTTP** | 浏览器与服务器的通信 | MCP 统一了 AI Agent 与数据服务的通信 |
| **USB** | 计算机与外设的接口 | MCP 统一了 AI 的"外设"接口 |
| **LSP** | IDE 与语言分析工具 | MCP 统一了 AI 与工具提供者 |
| **ODBC/JDBC** | 应用程序与数据库 | MCP 统一了 AI 与数据源 |

其中 **LSP（Language Server Protocol）** 的类比最为精确。LSP 由微软提出，解决了"N 个 IDE × M 种编程语言 = N×M 个语言插件"的问题。任何 IDE 实现 LSP Client，任何语言实现 LSP Server，两者即可互通。MCP 对 AI Agent 做了完全相同的事情。

### 1.5 MCP 解决的五个核心问题

| # | 核心问题 | 具体说明 |
|---|---------|---------|
| 1 | **标准化** | 一次实现 MCP 协议，所有支持 MCP 的 Agent/Server 都能互通 |
| 2 | **自描述** | Server 主动告诉 Client "我能做什么"（tools/list），Agent 无需预知 |
| 3 | **安全性** | 协议内置认证（OAuth 2.1）、权限控制、用户确认机制 |
| 4 | **可发现性** | Agent 运行时动态发现可用工具和资源，支持热更新 |
| 5 | **类型安全** | 每个 Tool 的输入输出都有 JSON Schema 定义，支持校验 |

### 1.6 MCP 的发展时间线

```
2024-11  Anthropic 发布 MCP 规范 v0.1（初始版本）
         同时发布 TypeScript SDK 和 Python SDK
         Claude Desktop 首个支持 MCP 的版本发布
         
2024-12  社区开始贡献 MCP Server（GitHub, Slack, Postgres 等）
         Cursor 宣布支持 MCP
         
2025-01  MCP 规范 v0.2 发布（新增 Streamable HTTP 传输）
         Windsurf 支持 MCP
         
2025-03  MCP 规范 v1.0 标准化进程启动
         远程 MCP Server 认证规范发布（OAuth 2.1）
         MCP Server 注册表项目启动
         
2025-06  多家 IDE 和 AI 工具宣布支持 MCP
         企业级 MCP 部署方案出现
         
2026-    MCP 持续演进，成为 AI Agent 生态的事实标准
```

---

## 2. MCP 架构详解

### 2.1 四大角色

MCP 的架构由四个核心角色组成，它们之间有明确的分工和边界：

```mermaid
graph LR
    subgraph "用户侧"
        User((用户))
    end
    
    subgraph "Host 应用"
        Host[Host 宿主应用<br/>Claude Desktop / Cursor / Claude Code]
        Client1[MCP Client 1]
        Client2[MCP Client 2]
        Client3[MCP Client 3]
        Host --> Client1
        Host --> Client2
        Host --> Client3
    end
    
    subgraph "MCP Server 层"
        Server1[MCP Server<br/>GitHub]
        Server2[MCP Server<br/>PostgreSQL]
        Server3[MCP Server<br/>文件系统]
    end
    
    subgraph "数据源层"
        DS1[(GitHub API)]
        DS2[(PostgreSQL 数据库)]
        DS3[(本地文件系统)]
    end
    
    User <-->|交互| Host
    Client1 <-->|MCP 协议| Server1
    Client2 <-->|MCP 协议| Server2
    Client3 <-->|MCP 协议| Server3
    Server1 <-->|API 调用| DS1
    Server2 <-->|SQL 查询| DS2
    Server3 <-->|文件 I/O| DS3
    
    style Host fill:#e1f5fe,stroke:#0288d1
    style Client1 fill:#b3e5fc
    style Client2 fill:#b3e5fc
    style Client3 fill:#b3e5fc
    style Server1 fill:#c8e6c9,stroke:#388e3c
    style Server2 fill:#c8e6c9,stroke:#388e3c
    style Server3 fill:#c8e6c9,stroke:#388e3c
    style DS1 fill:#fff3e0,stroke:#f57c00
    style DS2 fill:#fff3e0,stroke:#f57c00
    style DS3 fill:#fff3e0,stroke:#f57c00
```

#### 2.1.1 Host（宿主应用）

**定义**：用户直接交互的 AI 应用程序。

**职责**：
- 提供用户界面（GUI 或 CLI）
- 管理 MCP Client 的生命周期（创建、销毁）
- 集成 LLM（调用 AI 模型的 API）
- 将 MCP 工具和内置工具合并后传给 LLM
- 处理用户确认（"是否允许执行此操作？"）
- 管理配置文件（MCP Server 列表、认证信息等）

**常见 Host 实例**：
| Host | 类型 | 特点 |
|------|------|------|
| Claude Desktop | GUI 桌面应用 | Anthropic 官方，图形界面 |
| Claude Code (cc) | CLI 工具 | Anthropic 官方，终端内使用 |
| Cursor | IDE | VS Code fork，集成 AI 编程 |
| Windsurf | IDE | 新兴 AI IDE |
| 自定义 Agent | 任意 | 开发者自行构建的 Agent |

**关键点**：一个 Host 内部可以同时管理**多个 MCP Client**，每个 Client 对应一个 MCP Server。

#### 2.1.2 Client（客户端）

**定义**：Host 内部的 MCP 协议实现模块。

**职责**：
- 与**一个** MCP Server 保持 1:1 的连接
- 实现 MCP 协议的客户端侧（发送请求、接收响应）
- 处理协议握手（initialize → initialized）
- 发现 Server 的能力（tools/list、resources/list 等）
- 转发 LLM 的 tool call 到对应的 Server
- 管理连接状态（重连、超时等）

**关键点**：Client 是 Host 内部的**组件**，而非独立程序。用户不会直接与 Client 交互。

**1:1 连接模型**：

```
Host（如 Claude Code）
├── MCP Client A ←──1:1──→ GitHub MCP Server
├── MCP Client B ←──1:1──→ PostgreSQL MCP Server
├── MCP Client C ←──1:1──→ Slack MCP Server
└── MCP Client D ←──1:1──→ 文件系统 MCP Server
```

为什么是 1:1 而非 1:N？
- **隔离性**：一个 Server 崩溃不影响其他连接
- **简单性**：每个 Client 只需维护一个连接的状态
- **安全性**：不同 Server 的认证信息彼此隔离

#### 2.1.3 Server（服务器）

**定义**：提供具体能力的程序，通过 MCP 协议对外暴露。

**职责**：
- 实现 MCP 协议的服务器侧
- 暴露 Tools（工具）、Resources（资源）、Prompts（提示模板）
- 接收并执行 tool call 请求
- 连接真实的后端数据源或 API
- 返回执行结果

**Server 的运行形式**：
| 运行方式 | 传输协议 | 示例 |
|----------|---------|------|
| 本地子进程 | stdio | `npx @modelcontextprotocol/server-github` |
| 本地 HTTP 服务 | HTTP+SSE | `localhost:8080/mcp` |
| 远程 HTTP 服务 | HTTP+SSE | `https://mcp.example.com/github` |
| Docker 容器 | stdio 或 HTTP | `docker run mcp-server-postgres` |

**关键理解**：MCP Server 是一个"翻译层"。它一侧说 MCP 协议（与 Client 通信），另一侧说具体服务的原生协议（与数据源通信）。

#### 2.1.4 Data Source（数据源）

**定义**：Server 实际连接的后端数据或服务。

**示例**：
- GitHub REST/GraphQL API
- PostgreSQL 数据库实例
- 本地文件系统
- Slack Web API
- AWS S3 存储桶
- 第三方 SaaS API

Data Source 本身不知道 MCP 协议的存在。Server 负责在 MCP 协议和 Data Source 的原生接口之间进行翻译。

### 2.2 完整数据流

从用户提问到获得答案，数据经过以下完整路径：

```mermaid
sequenceDiagram
    participant User as 用户
    participant Host as Host（Claude Code）
    participant LLM as LLM（Claude API）
    participant Client as MCP Client
    participant Server as MCP Server
    participant DS as 数据源（GitHub API）
    
    User->>Host: "帮我查看 repo 的最近 PR"
    Host->>LLM: messages + tools 定义
    LLM-->>Host: tool_use: mcp__github__list_prs
    Host->>Host: 识别 mcp__ 前缀，路由到 MCP Client
    Host->>Client: call_tool("list_prs", {repo: "..."})
    Client->>Server: JSON-RPC: tools/call
    Server->>DS: GET /repos/.../pulls
    DS-->>Server: HTTP 200 + PR 列表 JSON
    Server-->>Client: JSON-RPC Response（PR 数据）
    Client-->>Host: ToolResult
    Host->>LLM: tool_result 内容
    LLM-->>Host: "这个仓库最近有 3 个 PR：..."
    Host-->>User: 展示 AI 回答
```

### 2.3 Host 的内部结构详解

以 Claude Code 为例，Host 内部的模块协作：

```mermaid
graph TB
    subgraph "Claude Code Host 内部结构"
        UI[用户界面 CLI]
        Config[配置管理器<br/>读取 mcp.json]
        MCPMgr[MCP 管理器<br/>管理所有 Client]
        BuiltIn[内置工具<br/>Read/Edit/Bash/Grep 等]
        ToolMerge[工具合并器<br/>内置工具 + MCP 工具]
        LLMClient[LLM API Client<br/>调用 Anthropic API]
        Router[Tool Call 路由器<br/>根据前缀分发]
        Perm[权限系统<br/>检查是否需要用户确认]
        
        UI --> Config
        Config --> MCPMgr
        MCPMgr --> C1[Client: GitHub]
        MCPMgr --> C2[Client: Postgres]
        MCPMgr --> C3[Client: Slack]
        
        BuiltIn --> ToolMerge
        MCPMgr -->|MCP 工具定义| ToolMerge
        ToolMerge --> LLMClient
        
        LLMClient -->|tool_use| Router
        Router -->|内置工具| BuiltIn
        Router -->|mcp__ 前缀| MCPMgr
        Router -->|执行前| Perm
    end
    
    style UI fill:#e1f5fe
    style Config fill:#f3e5f5
    style MCPMgr fill:#c8e6c9
    style BuiltIn fill:#fff3e0
    style ToolMerge fill:#fce4ec
    style LLMClient fill:#e8eaf6
    style Router fill:#fff9c4
    style Perm fill:#ffccbc
```

### 2.4 工具合并与路由机制

Host 需要将**内置工具**和**MCP 工具**合并后一起传给 LLM。LLM 返回 tool_use 时，Host 需要判断是内置工具还是 MCP 工具，并路由到正确的执行器。

**合并策略**：

```
内置工具：
  - Read（读文件）
  - Edit（编辑文件）
  - Bash（执行命令）
  - Grep（搜索内容）
  - Glob（文件匹配）
  - Write（写文件）

MCP 工具（来自 GitHub Server）：
  - mcp__github__create_issue
  - mcp__github__list_pulls
  - mcp__github__get_file_contents

MCP 工具（来自 PostgreSQL Server）：
  - mcp__postgres__query
  - mcp__postgres__list_tables

合并后传给 LLM 的 tools 参数：
  [Read, Edit, Bash, Grep, Glob, Write,
   mcp__github__create_issue, mcp__github__list_pulls, ...
   mcp__postgres__query, mcp__postgres__list_tables, ...]
```

**命名规则**：MCP 工具通常添加前缀以区分来源。常见格式：`mcp__{server_name}__{tool_name}`

**路由逻辑**（伪代码）：

```python
def route_tool_call(tool_name: str, arguments: dict):
    if tool_name.startswith("mcp__"):
        # MCP 工具：解析 server_name 和 tool_name
        parts = tool_name.split("__", 2)
        server_name = parts[1]
        original_tool_name = parts[2]
        # 找到对应的 MCP Client
        client = mcp_manager.get_client(server_name)
        return client.call_tool(original_tool_name, arguments)
    else:
        # 内置工具：直接执行
        return builtin_tools.execute(tool_name, arguments)
```

---

## 3. 底层协议：JSON-RPC 2.0

### 3.1 为什么选择 JSON-RPC？

MCP 的底层消息格式基于 **JSON-RPC 2.0** 规范。这是一个经过深思熟虑的选择：

| 候选方案 | 优势 | 劣势 | 为什么不选 |
|----------|------|------|-----------|
| REST API | 成熟、广泛使用、有丰富工具链 | 面向资源（CRUD），不适合 RPC 语义 | MCP 是"调用工具"而非"操作资源" |
| gRPC | 高性能、强类型、双向流 | 需要 protobuf 编译、不易调试、生态限制 | 门槛高，不利于社区采用 |
| GraphQL | 灵活查询、减少过度获取 | 复杂度高、学习曲线陡 | 过于复杂，MCP 不需要灵活查询 |
| 自定义协议 | 完全定制 | 缺乏工具、需要从零教育 | 不利于生态发展 |
| **JSON-RPC 2.0** | **简单、轻量、传输无关** | 功能简单 | **功能简单正是优势** |

JSON-RPC 2.0 的**核心优势**：

1. **传输无关（Transport-agnostic）**：同一套消息格式可以走 stdio、HTTP、WebSocket——协议只关心消息内容，不关心传输方式
2. **极简设计**：整个规范不到 3 页，开发者 10 分钟就能看完
3. **成熟稳定**：2010 年发布，被大量项目采用（LSP 也用 JSON-RPC）
4. **JSON 原生**：直接使用 JSON，无需额外的序列化步骤
5. **支持通知**：可以发送无需响应的消息（notification）

### 3.2 三种消息类型

JSON-RPC 2.0 定义了三种消息类型，MCP 完全遵循：

#### 3.2.1 Request（请求）

客户端或服务器发送的带有唯一 ID 的请求，期望对方回复。

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/list",
    "params": {}
}
```

字段说明：
| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `jsonrpc` | string | 是 | 固定为 `"2.0"` |
| `id` | number/string | 是 | 请求的唯一标识符，用于匹配响应 |
| `method` | string | 是 | 要调用的方法名 |
| `params` | object/array | 否 | 方法的参数 |

#### 3.2.2 Response（响应）

对 Request 的回复，通过 `id` 匹配。

**成功响应**：
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "tools": [
            {
                "name": "query_database",
                "description": "Execute a read-only SQL query against the database",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "The SQL query to execute"
                        }
                    },
                    "required": ["sql"]
                }
            }
        ]
    }
}
```

**错误响应**：
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": -32601,
        "message": "Method not found",
        "data": {
            "detail": "The method 'tools/unknown' is not supported"
        }
    }
}
```

标准错误码：
| 错误码 | 含义 | 说明 |
|--------|------|------|
| -32700 | Parse error | JSON 解析失败 |
| -32600 | Invalid Request | 请求格式无效 |
| -32601 | Method not found | 方法不存在 |
| -32602 | Invalid params | 参数错误 |
| -32603 | Internal error | 服务器内部错误 |

#### 3.2.3 Notification（通知）

**没有 `id` 字段**的消息，发送方不期望收到响应。用于单向通知。

```json
{
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {}
}
```

**通知 vs 请求的区别**：
| 特征 | Request | Notification |
|------|---------|-------------|
| 有 `id` 字段 | 是 | 否 |
| 期望响应 | 是 | 否 |
| 用于 | 需要结果的操作 | 状态通知、事件推送 |
| 示例 | tools/list, tools/call | notifications/initialized, notifications/tools/list_changed |

### 3.3 MCP 定义的方法

MCP 在 JSON-RPC 2.0 之上定义了一组标准方法：

**协议生命周期方法**：
| 方法 | 方向 | 类型 | 说明 |
|------|------|------|------|
| `initialize` | Client → Server | Request | 协议握手，交换能力 |
| `notifications/initialized` | Client → Server | Notification | 确认握手完成 |
| `ping` | 双向 | Request | 心跳检测 |

**工具相关方法**：
| 方法 | 方向 | 类型 | 说明 |
|------|------|------|------|
| `tools/list` | Client → Server | Request | 列出所有可用工具 |
| `tools/call` | Client → Server | Request | 调用一个工具 |
| `notifications/tools/list_changed` | Server → Client | Notification | 工具列表变更通知 |

**资源相关方法**：
| 方法 | 方向 | 类型 | 说明 |
|------|------|------|------|
| `resources/list` | Client → Server | Request | 列出所有可用资源 |
| `resources/read` | Client → Server | Request | 读取资源内容 |
| `resources/subscribe` | Client → Server | Request | 订阅资源变更 |
| `notifications/resources/updated` | Server → Client | Notification | 资源变更通知 |
| `notifications/resources/list_changed` | Server → Client | Notification | 资源列表变更通知 |

**提示模板相关方法**：
| 方法 | 方向 | 类型 | 说明 |
|------|------|------|------|
| `prompts/list` | Client → Server | Request | 列出所有提示模板 |
| `prompts/get` | Client → Server | Request | 获取特定提示模板 |
| `notifications/prompts/list_changed` | Server → Client | Notification | 提示模板列表变更通知 |

**补全相关方法**：
| 方法 | 方向 | 类型 | 说明 |
|------|------|------|------|
| `completion/complete` | Client → Server | Request | 请求参数自动补全 |

**日志方法**：
| 方法 | 方向 | 类型 | 说明 |
|------|------|------|------|
| `logging/setLevel` | Client → Server | Request | 设置日志级别 |
| `notifications/message` | Server → Client | Notification | 发送日志消息 |

### 3.4 完整握手流程

```mermaid
sequenceDiagram
    participant C as MCP Client
    participant S as MCP Server
    
    Note over C,S: 阶段 1：协议握手
    C->>S: initialize {protocolVersion, capabilities, clientInfo}
    S-->>C: {protocolVersion, capabilities, serverInfo}
    C->>S: notifications/initialized {}
    
    Note over C,S: 阶段 2：能力发现
    C->>S: tools/list {}
    S-->>C: {tools: [{name, description, inputSchema}, ...]}
    C->>S: resources/list {}
    S-->>C: {resources: [{uri, name, mimeType}, ...]}
    C->>S: prompts/list {}
    S-->>C: {prompts: [{name, description, arguments}, ...]}
    
    Note over C,S: 阶段 3：正常使用
    C->>S: tools/call {name: "query_db", arguments: {sql: "SELECT ..."}}
    S-->>C: {content: [{type: "text", text: "...结果..."}]}
    
    C->>S: resources/read {uri: "file:///path/to/file"}
    S-->>C: {contents: [{uri, mimeType, text}]}
    
    Note over C,S: 阶段 4：动态变更通知
    S->>C: notifications/tools/list_changed {}
    C->>S: tools/list {}
    S-->>C: {tools: [...更新后的工具列表...]}
```

### 3.5 initialize 请求的完整示例

**Client 发送的 initialize 请求**：

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "roots": {
                "listChanged": true
            },
            "sampling": {}
        },
        "clientInfo": {
            "name": "claude-code",
            "version": "1.0.0"
        }
    }
}
```

**Server 返回的 initialize 响应**：

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "tools": {
                "listChanged": true
            },
            "resources": {
                "subscribe": true,
                "listChanged": true
            },
            "prompts": {
                "listChanged": true
            },
            "logging": {}
        },
        "serverInfo": {
            "name": "github-mcp-server",
            "version": "0.5.0"
        }
    }
}
```

**capabilities 字段**是关键——它让双方知道对方支持哪些特性：
- Client 告诉 Server：我支持 `roots` 和 `sampling`
- Server 告诉 Client：我支持 `tools`、`resources`、`prompts`、`logging`
- `listChanged: true` 表示支持动态变更通知

---

## 4. 传输方式详解

MCP 的一大设计优势是**传输无关性**——协议消息（JSON-RPC）与传输方式（如何发送消息）完全分离。目前规范定义了三种传输方式。

### 4.1 Stdio 传输

#### 4.1.1 原理

Client 将 MCP Server 作为**子进程**启动，通过进程的标准输入（stdin）和标准输出（stdout）进行通信。

```mermaid
graph LR
    subgraph "Host 进程（如 Claude Code）"
        Client[MCP Client]
    end
    
    subgraph "Server 子进程"
        Server[MCP Server<br/>如 GitHub Server]
    end
    
    Client -->|"写入 stdin<br/>JSON-RPC 请求"| Server
    Server -->|"写入 stdout<br/>JSON-RPC 响应"| Client
    Server -.->|"stderr<br/>调试日志"| Log[日志输出]
    
    style Client fill:#e1f5fe
    style Server fill:#c8e6c9
    style Log fill:#f5f5f5
```

#### 4.1.2 消息分隔

每条 JSON-RPC 消息占一行，以 `\n` 分隔。不允许消息内包含换行符（JSON 内的换行需要转义为 `\n`）。

```
→ stdin:  {"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}\n
← stdout: {"jsonrpc":"2.0","id":1,"result":{...}}\n
→ stdin:  {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n
← stdout: {"jsonrpc":"2.0","id":2,"result":{"tools":[...]}}\n
```

#### 4.1.3 启动流程

1. Host 读取配置文件（如 `mcp.json`）
2. 对于每个 stdio 类型的 Server，Host 执行其配置的命令
3. 例如：`npx -y @modelcontextprotocol/server-github` 启动 GitHub MCP Server
4. Server 进程启动后，在 stdout 上等待消息
5. Client 通过 stdin 发送 initialize 请求
6. 握手完成后，连接建立

#### 4.1.4 配置示例

```json
{
    "mcpServers": {
        "github": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {
                "GITHUB_TOKEN": "ghp_xxxxxxxxxxxx"
            }
        },
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"],
            "env": {}
        },
        "postgres": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-postgres"],
            "env": {
                "DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb"
            }
        }
    }
}
```

#### 4.1.5 优劣分析

| 维度 | 评价 |
|------|------|
| **简单性** | 极简——只需能启动子进程和读写 stdin/stdout |
| **可靠性** | 高——基于操作系统管道，不涉及网络 |
| **隔离性** | 好——每个 Server 是独立进程，崩溃不影响 Host |
| **安全性** | 好——Server 在本地运行，环境变量传递敏感信息 |
| **部署** | 需要本地安装 Server 的运行环境（Node.js/Python 等） |
| **网络** | 不支持远程访问（Server 必须在本地） |
| **多用户** | 不支持（每个 Host 启动独立的 Server 进程） |

**最佳场景**：本地开发工具、CLI Agent、桌面应用。

### 4.2 HTTP + SSE 传输（Streamable HTTP）

#### 4.2.1 原理

Server 作为 HTTP 服务运行，Client 通过 HTTP POST 发送请求，通过 Server-Sent Events (SSE) 接收流式响应和服务器推送。

```mermaid
graph LR
    subgraph "Client 侧"
        Client[MCP Client]
    end
    
    subgraph "Server 侧（HTTP 服务）"
        HTTP[HTTP 端点<br/>POST /mcp]
        SSE[SSE 端点<br/>GET /mcp/sse]
        Server[MCP Server 逻辑]
        HTTP --> Server
        Server --> SSE
    end
    
    Client -->|"HTTP POST<br/>JSON-RPC 请求"| HTTP
    SSE -->|"SSE 流<br/>JSON-RPC 响应 + 通知"| Client
    
    style Client fill:#e1f5fe
    style HTTP fill:#c8e6c9
    style SSE fill:#c8e6c9
    style Server fill:#c8e6c9
```

#### 4.2.2 两种 HTTP 传输模式

MCP 规范实际定义了两种 HTTP 传输模式：

**旧模式：HTTP + SSE（已弃用）**

- Client 先 GET `/sse` 建立 SSE 连接
- Server 通过 SSE 推送一个 `endpoint` 事件，告诉 Client POST 的 URL
- Client 向该 URL POST JSON-RPC 消息
- Server 通过 SSE 流返回响应

**新模式：Streamable HTTP（推荐）**

- 单一端点（如 `/mcp`）同时支持 POST 和 GET
- POST 请求直接发送 JSON-RPC 消息
- 响应可以是普通 JSON（非流式）或 SSE 流（流式）
- GET 请求建立 SSE 连接接收服务器推送
- 更简洁、更灵活

#### 4.2.3 Streamable HTTP 交互流程

```mermaid
sequenceDiagram
    participant C as MCP Client
    participant S as HTTP MCP Server
    
    Note over C,S: 建立 SSE 连接（可选，用于接收服务器推送）
    C->>S: GET /mcp (Accept: text/event-stream)
    S-->>C: SSE 流建立
    
    Note over C,S: 发送请求
    C->>S: POST /mcp {initialize...}
    S-->>C: 200 OK {result: ...}
    
    C->>S: POST /mcp {tools/list...}
    S-->>C: 200 OK {result: {tools: [...]}}
    
    Note over C,S: 流式响应示例
    C->>S: POST /mcp {tools/call: long_running_task}
    S-->>C: SSE: {progress: 30%}
    S-->>C: SSE: {progress: 60%}
    S-->>C: SSE: {progress: 100%}
    S-->>C: SSE: {result: ...}
    
    Note over C,S: 服务器主动推送
    S-->>C: SSE: notifications/tools/list_changed
```

#### 4.2.4 配置示例

```json
{
    "mcpServers": {
        "remote-github": {
            "type": "sse",
            "url": "https://mcp.example.com/github",
            "headers": {
                "Authorization": "Bearer eyJhbGciOiJSUzI1NiIs..."
            }
        }
    }
}
```

#### 4.2.5 优劣分析

| 维度 | 评价 |
|------|------|
| **远程访问** | 支持——Server 可以部署在任何可访问的地方 |
| **多用户** | 支持——多个 Client 可以连接同一个 Server |
| **流式响应** | 支持——通过 SSE 实现实时数据推送 |
| **部署** | 需要 HTTP 服务基础设施（域名、TLS、负载均衡等） |
| **延迟** | 有网络延迟 |
| **复杂度** | 比 stdio 复杂（需要处理 HTTP、SSE、连接管理等） |
| **安全性** | 需要额外的认证机制（OAuth 2.1） |

**最佳场景**：远程 MCP 服务、SaaS 集成、企业多用户部署。

### 4.3 WebSocket 传输

#### 4.3.1 原理

通过 WebSocket 建立全双工连接，Client 和 Server 可以随时互发消息。

**优势**：
- 真正的全双工通信
- 低延迟（持久连接）
- Server 可以随时主动推送

**劣势**：
- 需要 WebSocket 基础设施
- 连接管理复杂（心跳、重连）
- 部分环境不支持（如某些企业代理）

**适用场景**：需要高频双向通信的场景（如实时协作工具）。

### 4.4 传输方式对比总结

```mermaid
graph TB
    subgraph "选择传输方式的决策树"
        Q1{Server 在本地还是远程？}
        Q1 -->|本地| Q2{需要多用户共享吗？}
        Q1 -->|远程| HTTP[选择 HTTP+SSE<br/>Streamable HTTP]
        
        Q2 -->|不需要| STDIO[选择 Stdio<br/>最简单可靠]
        Q2 -->|需要| Q3{需要高频双向通信吗？}
        
        Q3 -->|不需要| HTTP_LOCAL[选择 HTTP+SSE<br/>本地 HTTP 服务]
        Q3 -->|需要| WS[选择 WebSocket<br/>全双工通信]
    end
    
    style STDIO fill:#c8e6c9
    style HTTP fill:#bbdefb
    style HTTP_LOCAL fill:#bbdefb
    style WS fill:#fff9c4
    style Q1 fill:#f5f5f5
    style Q2 fill:#f5f5f5
    style Q3 fill:#f5f5f5
```

### 4.5 解答困惑：stdio 模式需要下载 Server 到本地？

**是的，stdio 模式的 MCP Server 确实在本地运行。** 但这不意味着"数据也在本地"。

```
┌─────────────────────────────────────────────┐
│              你的本地机器                      │
│                                              │
│  [Claude Code] ←──stdio──→ [MCP Server]      │
│                              │               │
└──────────────────────────────│───────────────┘
                               │ 网络请求
                               ▼
                    ┌──────────────────┐
                    │   远程服务        │
                    │  GitHub API      │
                    │  Slack API       │
                    │  数据库服务       │
                    └──────────────────┘
```

MCP Server 是一个"翻译层"（或称"适配器"）：
- **输入侧**：通过 stdin/stdout 与 MCP Client 说 MCP 协议
- **输出侧**：通过网络与远程服务说它们的原生协议（REST API、GraphQL、SQL 等）

**类比**：你本地安装的**浏览器**也是本地程序，但它访问的是远程网站。MCP Server 类似——本地进程，远程数据。

**"占空间"问题**：
- 大多数 MCP Server 是 **npm 包**，通过 `npx -y` 临时下载运行
- 包的大小通常很小（几 MB 以内）
- 运行环境（Node.js/Python）开发者通常已安装
- `npx` 有缓存机制，不会每次重新下载
- 如果不想在本地安装，可以使用 **HTTP 模式**连接远程部署的 Server

---

## 5. MCP 三大核心能力

MCP Server 可以向 Client 暴露三种类型的能力：**Tools（工具）**、**Resources（资源）**、**Prompts（提示模板）**。

### 5.1 Tools（工具）——AI 可调用的函数

#### 5.1.1 概念

Tool 是 MCP 最核心、最常用的能力。一个 Tool 代表一个 AI 模型可以调用的**函数**。

每个 Tool 由三部分定义：
- `name`：工具的唯一标识符
- `description`：工具的自然语言描述（LLM 根据这个决定是否调用）
- `inputSchema`：输入参数的 JSON Schema 定义

#### 5.1.2 Tool 定义示例

```json
{
    "name": "create_github_issue",
    "description": "Create a new issue in a GitHub repository. Use this when the user wants to report a bug, request a feature, or create a task in a GitHub repository.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "owner": {
                "type": "string",
                "description": "The owner (user or organization) of the repository"
            },
            "repo": {
                "type": "string",
                "description": "The name of the repository"
            },
            "title": {
                "type": "string",
                "description": "The title of the issue"
            },
            "body": {
                "type": "string",
                "description": "The body/description of the issue (supports Markdown)"
            },
            "labels": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Labels to apply to the issue"
            }
        },
        "required": ["owner", "repo", "title"]
    }
}
```

#### 5.1.3 Tool 调用流程

```mermaid
sequenceDiagram
    participant LLM as LLM（Claude）
    participant Host as Host（Agent）
    participant Client as MCP Client
    participant Server as MCP Server
    participant API as GitHub API
    
    Note over LLM: 分析用户意图后决定调用工具
    LLM-->>Host: tool_use: create_github_issue<br/>{owner: "anthropics", repo: "mcp", title: "Bug report"}
    
    Host->>Host: 解析工具名，识别为 MCP 工具
    Host->>Host: 权限检查 / 用户确认
    
    Host->>Client: call_tool("create_github_issue", {...})
    Client->>Server: {"method": "tools/call", "params": {"name": "create_github_issue", "arguments": {...}}}
    
    Server->>API: POST /repos/anthropics/mcp/issues<br/>Authorization: Bearer ghp_xxx
    API-->>Server: 201 Created {number: 42, html_url: "..."}
    
    Server-->>Client: {"result": {"content": [{"type": "text", "text": "Created issue #42: ..."}]}}
    Client-->>Host: ToolResult
    
    Host->>LLM: tool_result: "Created issue #42: ..."
    Note over LLM: 根据工具结果生成回答
    LLM-->>Host: "我已经在 anthropics/mcp 仓库创建了 Issue #42。"
```

#### 5.1.4 Tool 返回值格式

Tool 调用的返回值统一为 `content` 数组，每个元素可以是：

```json
{
    "content": [
        {
            "type": "text",
            "text": "查询结果：共 42 条记录\n\n| id | name | email |\n|---|------|-------|\n| 1 | Alice | alice@example.com |"
        }
    ]
}
```

支持的 content 类型：
| type | 说明 | 用途 |
|------|------|------|
| `text` | 纯文本 | 大部分场景 |
| `image` | Base64 编码的图片 | 截图、图表 |
| `resource` | 嵌入的资源引用 | 文件内容等 |

#### 5.1.5 Tool 的注解（Annotations）

MCP 规范支持为 Tool 添加注解，帮助 Host 做出更好的决策：

```json
{
    "name": "delete_repository",
    "description": "Delete a GitHub repository permanently",
    "inputSchema": {...},
    "annotations": {
        "destructive": true,
        "requiresConfirmation": true,
        "readOnly": false,
        "idempotent": false,
        "openWorld": true
    }
}
```

| 注解 | 含义 | Host 的处理 |
|------|------|-----------|
| `destructive` | 操作是破坏性的 | 显示警告，要求强确认 |
| `requiresConfirmation` | 需要用户确认 | 执行前弹出确认对话框 |
| `readOnly` | 只读操作 | 可以自动执行，无需确认 |
| `idempotent` | 幂等操作 | 重试安全 |
| `openWorld` | 涉及外部世界 | 需要网络访问 |

### 5.2 Resources（资源）——AI 可读取的数据

#### 5.2.1 概念

Resource 是 Server 暴露的**只读数据**，通过 URI 标识。与 Tool 的区别：

| 维度 | Tool | Resource |
|------|------|----------|
| 性质 | 动作（执行操作） | 数据（提供信息） |
| 触发方 | AI 模型自主决定 | 通常由用户或应用触发 |
| 副作用 | 可能有（创建、修改、删除） | 无（只读） |
| 类比 | 函数/API | 文件/数据库记录 |

#### 5.2.2 Resource 定义示例

```json
{
    "resources": [
        {
            "uri": "file:///home/user/project/README.md",
            "name": "Project README",
            "description": "The main README file of the project",
            "mimeType": "text/markdown"
        },
        {
            "uri": "postgres://localhost/mydb/tables/users",
            "name": "Users Table Schema",
            "description": "Schema definition of the users table",
            "mimeType": "application/json"
        },
        {
            "uri": "github://anthropics/mcp/issues",
            "name": "MCP Issues",
            "description": "Open issues in the MCP repository",
            "mimeType": "application/json"
        }
    ]
}
```

#### 5.2.3 Resource 读取

```json
// 请求
{
    "method": "resources/read",
    "params": {
        "uri": "file:///home/user/project/README.md"
    }
}

// 响应
{
    "contents": [
        {
            "uri": "file:///home/user/project/README.md",
            "mimeType": "text/markdown",
            "text": "# My Project\n\nThis is a sample project..."
        }
    ]
}
```

#### 5.2.4 Resource Template

Resource 还支持**URI 模板**（RFC 6570），允许动态生成 URI：

```json
{
    "resourceTemplates": [
        {
            "uriTemplate": "github:///{owner}/{repo}/issues/{issue_number}",
            "name": "GitHub Issue",
            "description": "A specific GitHub issue",
            "mimeType": "application/json"
        }
    ]
}
```

Client 可以填充模板参数来读取特定资源：
```
github:///anthropics/mcp/issues/42
```

#### 5.2.5 Resource 订阅

Client 可以订阅 Resource 的变更通知：

```json
// Client 订阅
{"method": "resources/subscribe", "params": {"uri": "file:///path/to/config.json"}}

// Server 通知变更（当文件被修改时）
{"method": "notifications/resources/updated", "params": {"uri": "file:///path/to/config.json"}}

// Client 重新读取
{"method": "resources/read", "params": {"uri": "file:///path/to/config.json"}}
```

### 5.3 Prompts（提示模板）——可复用的交互模式

#### 5.3.1 概念

Prompt 是 Server 提供的**可复用提示模板**。它不同于 Tool（AI 自主调用）和 Resource（被动数据），Prompt 通常由**用户主动选择**使用。

**类比**：如果 Tool 是"遥控器上的按钮"，Prompt 就是"操作手册中的常见场景指南"。

#### 5.3.2 Prompt 定义示例

```json
{
    "prompts": [
        {
            "name": "code_review",
            "description": "Review code changes and provide feedback",
            "arguments": [
                {
                    "name": "pr_url",
                    "description": "The URL of the pull request to review",
                    "required": true
                },
                {
                    "name": "focus",
                    "description": "What to focus on: security, performance, style, or all",
                    "required": false
                }
            ]
        },
        {
            "name": "explain_error",
            "description": "Explain an error message and suggest fixes",
            "arguments": [
                {
                    "name": "error_message",
                    "description": "The error message to explain",
                    "required": true
                },
                {
                    "name": "language",
                    "description": "The programming language context",
                    "required": false
                }
            ]
        }
    ]
}
```

#### 5.3.3 获取 Prompt 内容

```json
// 请求
{
    "method": "prompts/get",
    "params": {
        "name": "code_review",
        "arguments": {
            "pr_url": "https://github.com/anthropics/mcp/pull/123",
            "focus": "security"
        }
    }
}

// 响应
{
    "description": "Code review for PR #123",
    "messages": [
        {
            "role": "user",
            "content": {
                "type": "text",
                "text": "Please review the following pull request with a focus on security:\nhttps://github.com/anthropics/mcp/pull/123\n\nAnalyze the changes for:\n1. SQL injection vulnerabilities\n2. XSS vulnerabilities\n3. Authentication/authorization issues\n4. Sensitive data exposure\n5. Input validation\n\nProvide specific line-by-line feedback."
            }
        }
    ]
}
```

Host 收到 Prompt 的 messages 后，可以将它们注入到与 LLM 的对话中。

### 5.4 三大能力的协作关系

```mermaid
graph TB
    subgraph "MCP Server 的三大能力"
        T[Tools 工具<br/>AI 可调用的函数]
        R[Resources 资源<br/>AI 可读取的数据]
        P[Prompts 提示模板<br/>用户可选择的交互模式]
    end
    
    subgraph "触发方式"
        AI((AI 模型)) -->|自主决定调用| T
        User((用户)) -->|主动选择| P
        App((应用逻辑)) -->|按需加载| R
        AI -.->|请求读取| R
    end
    
    subgraph "使用场景示例"
        T1[create_issue<br/>创建 GitHub Issue]
        T2[query_database<br/>查询数据库]
        R1[project://README.md<br/>项目说明]
        R2[db://schema/users<br/>表结构]
        P1[code_review<br/>代码审查模板]
        P2[debug_error<br/>错误排查模板]
    end
    
    T --- T1
    T --- T2
    R --- R1
    R --- R2
    P --- P1
    P --- P2
    
    style T fill:#e1f5fe
    style R fill:#c8e6c9
    style P fill:#fff3e0
```

### 5.5 实际中的能力分布

不同的 MCP Server 侧重不同的能力：

| MCP Server | Tools | Resources | Prompts |
|-----------|-------|-----------|---------|
| GitHub Server | create_issue, list_pulls, merge_pr 等 | repo 文件内容 | code_review 模板 |
| PostgreSQL Server | query, list_tables | 表结构 schema | 查询优化模板 |
| 文件系统 Server | read_file, write_file, list_dir | 文件内容 | - |
| Slack Server | send_message, list_channels | 频道历史消息 | - |
| Sentry Server | get_issue, list_events | 错误详情 | 错误排查模板 |

---

## 6. 协议生命周期与状态机

### 6.1 连接状态机

一个 MCP 连接经历明确的状态转换：

```mermaid
stateDiagram-v2
    [*] --> Disconnected: 初始状态
    
    Disconnected --> Connecting: Client 发起连接<br/>（启动 Server 进程 / 建立 HTTP 连接）
    
    Connecting --> Initializing: 传输层连接建立
    
    Initializing --> Ready: initialize 完成<br/>+ notifications/initialized
    
    Ready --> Ready: 正常交互<br/>tools/call, resources/read 等
    
    Ready --> Disconnected: 连接断开<br/>Server 崩溃 / 网络中断
    
    Initializing --> Disconnected: 握手失败<br/>版本不兼容 / 超时
    
    Connecting --> Disconnected: 连接失败<br/>Server 启动失败 / 网络不可达
    
    Ready --> ShuttingDown: Client 发送关闭信号
    ShuttingDown --> Disconnected: 优雅关闭
```

### 6.2 各状态的详细说明

**Disconnected（断开）**：
- 初始状态，无活跃连接
- Client 可以尝试连接或重连

**Connecting（连接中）**：
- stdio：正在启动 Server 子进程
- HTTP：正在建立 HTTP/SSE 连接
- WebSocket：正在进行 WebSocket 握手

**Initializing（初始化中）**：
- 传输层已连接，正在进行 MCP 协议握手
- Client 发送 `initialize` 请求
- Server 返回能力信息
- Client 发送 `notifications/initialized` 确认
- **此阶段不能调用任何工具**

**Ready（就绪）**：
- 连接完全建立，可以正常交互
- 可以调用 tools/list、tools/call、resources/read 等所有方法
- Server 可以发送通知（如 tools/list_changed）

**ShuttingDown（关闭中）**：
- Client 通知 Server 即将关闭
- 等待进行中的请求完成
- 清理资源

### 6.3 错误处理与重连

MCP 连接可能因各种原因断开，Host 需要处理这些情况：

```python
# 重连策略示例（伪代码）
class MCPConnectionManager:
    def __init__(self, server_config):
        self.config = server_config
        self.max_retries = 3
        self.retry_delay = 1.0  # 秒
        self.backoff_factor = 2.0
    
    async def connect_with_retry(self):
        for attempt in range(self.max_retries):
            try:
                await self.connect()
                await self.initialize()
                return  # 连接成功
            except ConnectionError as e:
                delay = self.retry_delay * (self.backoff_factor ** attempt)
                log.warning(f"连接失败 (第 {attempt+1} 次)，{delay}s 后重试: {e}")
                await asyncio.sleep(delay)
        
        raise MaxRetriesExceeded(f"经过 {self.max_retries} 次尝试仍无法连接")
    
    async def handle_disconnect(self):
        """连接意外断开时的处理"""
        log.warning("MCP Server 连接断开，尝试重连")
        await self.connect_with_retry()
        # 重连后需要重新发现工具
        await self.refresh_tools()
```

### 6.4 能力协商（Capability Negotiation）

初始化阶段的**能力协商**是 MCP 的重要机制。它让 Client 和 Server 知道对方支持哪些特性，从而实现版本兼容。

**Client 可以声明的能力**：
| 能力 | 说明 |
|------|------|
| `roots` | 支持工作区根目录 |
| `roots.listChanged` | 支持根目录变更通知 |
| `sampling` | 支持 Server 请求 LLM 采样 |
| `experimental` | 支持实验性特性 |

**Server 可以声明的能力**：
| 能力 | 说明 |
|------|------|
| `tools` | 提供工具 |
| `tools.listChanged` | 支持工具列表变更通知 |
| `resources` | 提供资源 |
| `resources.subscribe` | 支持资源订阅 |
| `resources.listChanged` | 支持资源列表变更通知 |
| `prompts` | 提供提示模板 |
| `prompts.listChanged` | 支持提示模板列表变更通知 |
| `logging` | 支持日志 |
| `experimental` | 支持实验性特性 |

**能力协商的意义**：
- Client 只会调用 Server 声明支持的方法
- Server 只会发送 Client 声明支持的通知
- 新旧版本可以安全互通（不支持的特性不会被调用）

---

## 7. 如何开发 MCP Server

### 7.1 SDK 生态

MCP 社区提供了多种语言的 SDK：

| 语言 | 包名 | 维护者 | 成熟度 |
|------|------|--------|--------|
| TypeScript | `@modelcontextprotocol/sdk` | Anthropic 官方 | 最成熟 |
| Python | `mcp` (PyPI) | Anthropic 官方 | 成熟 |
| Kotlin | `mcp-kotlin-sdk` | JetBrains | 稳定 |
| C# | `ModelContextProtocol` | Microsoft | 稳定 |
| Go | `mcp-go` | 社区 (mark3labs) | 活跃 |
| Rust | `mcp-rust-sdk` | 社区 | 早期 |
| Java | `mcp-java-sdk` | Spring 社区 | 活跃 |
| Swift | `mcp-swift-sdk` | 社区 | 早期 |

### 7.2 Python SDK 开发指南

#### 7.2.1 安装

```bash
pip install mcp
# 或使用 uv（推荐）
uv add mcp
```

#### 7.2.2 极简示例：天气查询 Server

```python
"""
一个极简的 MCP Server 示例：天气查询。
运行方式：python weather_server.py
"""
import asyncio
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 创建 MCP Server 实例
server = Server("weather-server")

# 模拟天气数据
WEATHER_DATA = {
    "beijing": {"temp": 22, "condition": "晴", "humidity": 45},
    "shanghai": {"temp": 26, "condition": "多云", "humidity": 72},
    "guangzhou": {"temp": 30, "condition": "雷阵雨", "humidity": 85},
    "shenzhen": {"temp": 29, "condition": "阴", "humidity": 78},
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    """列出所有可用工具"""
    return [
        Tool(
            name="get_weather",
            description="获取指定城市的当前天气信息。支持的城市：北京、上海、广州、深圳。",
            inputSchema={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名称（拼音小写），如 beijing, shanghai",
                        "enum": ["beijing", "shanghai", "guangzhou", "shenzhen"],
                    }
                },
                "required": ["city"],
            },
        ),
        Tool(
            name="compare_weather",
            description="比较两个城市的天气",
            inputSchema={
                "type": "object",
                "properties": {
                    "city1": {
                        "type": "string",
                        "description": "第一个城市",
                        "enum": ["beijing", "shanghai", "guangzhou", "shenzhen"],
                    },
                    "city2": {
                        "type": "string",
                        "description": "第二个城市",
                        "enum": ["beijing", "shanghai", "guangzhou", "shenzhen"],
                    },
                },
                "required": ["city1", "city2"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """处理工具调用"""
    if name == "get_weather":
        city = arguments["city"]
        data = WEATHER_DATA.get(city)
        if not data:
            return [TextContent(type="text", text=f"未找到城市 {city} 的天气数据")]
        return [
            TextContent(
                type="text",
                text=f"{city} 天气：{data['condition']}，温度 {data['temp']}°C，湿度 {data['humidity']}%",
            )
        ]

    elif name == "compare_weather":
        city1 = arguments["city1"]
        city2 = arguments["city2"]
        d1 = WEATHER_DATA.get(city1)
        d2 = WEATHER_DATA.get(city2)
        if not d1 or not d2:
            return [TextContent(type="text", text="城市数据不完整")]

        diff = d1["temp"] - d2["temp"]
        warmer = city1 if diff > 0 else city2
        return [
            TextContent(
                type="text",
                text=(
                    f"天气对比：\n"
                    f"  {city1}: {d1['condition']}, {d1['temp']}°C\n"
                    f"  {city2}: {d2['condition']}, {d2['temp']}°C\n"
                    f"  {warmer} 更暖，温差 {abs(diff)}°C"
                ),
            )
        ]

    else:
        return [TextContent(type="text", text=f"未知工具: {name}")]


async def main():
    """启动 MCP Server（stdio 模式）"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
```

#### 7.2.3 带 Resources 和 Prompts 的完整示例

```python
"""
完整的 MCP Server 示例：数据库助手
包含 Tools、Resources、Prompts 三大能力
"""
import asyncio
import sqlite3
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool, TextContent, Resource, ResourceTemplate,
    Prompt, PromptArgument, PromptMessage, GetPromptResult,
)

server = Server("database-assistant")

# 模拟数据库连接
DB_PATH = ":memory:"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # 创建示例表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        INSERT OR IGNORE INTO users (id, name, email) VALUES
        (1, 'Alice', 'alice@example.com'),
        (2, 'Bob', 'bob@example.com'),
        (3, 'Charlie', 'charlie@example.com')
    """)
    conn.commit()
    return conn


# ========== Tools ==========

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="query",
            description="执行只读 SQL 查询（仅支持 SELECT）",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "要执行的 SELECT SQL 语句",
                    }
                },
                "required": ["sql"],
            },
        ),
        Tool(
            name="list_tables",
            description="列出数据库中所有表",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="describe_table",
            description="查看表的结构（列名、类型）",
            inputSchema={
                "type": "object",
                "properties": {
                    "table_name": {
                        "type": "string",
                        "description": "表名",
                    }
                },
                "required": ["table_name"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    conn = get_db()
    try:
        if name == "query":
            sql = arguments["sql"].strip()
            if not sql.upper().startswith("SELECT"):
                return [TextContent(type="text", text="错误：只允许 SELECT 查询")]
            cursor = conn.execute(sql)
            rows = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            result = {"columns": columns, "rows": [dict(row) for row in rows], "count": len(rows)}
            import json
            return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        elif name == "list_tables":
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row["name"] for row in cursor.fetchall()]
            return [TextContent(type="text", text=f"数据库中的表：{', '.join(tables)}")]

        elif name == "describe_table":
            table = arguments["table_name"]
            cursor = conn.execute(f"PRAGMA table_info({table})")
            columns = cursor.fetchall()
            desc = f"表 {table} 的结构：\n"
            for col in columns:
                desc += f"  - {col['name']} ({col['type']})"
                if col["pk"]:
                    desc += " PRIMARY KEY"
                if col["notnull"]:
                    desc += " NOT NULL"
                desc += "\n"
            return [TextContent(type="text", text=desc)]

        return [TextContent(type="text", text=f"未知工具: {name}")]
    finally:
        conn.close()


# ========== Resources ==========

@server.list_resources()
async def list_resources() -> list[Resource]:
    return [
        Resource(
            uri="db://schema/all",
            name="Complete Database Schema",
            description="所有表的完整结构信息",
            mimeType="application/json",
        ),
    ]


@server.list_resource_templates()
async def list_resource_templates() -> list[ResourceTemplate]:
    return [
        ResourceTemplate(
            uriTemplate="db://table/{table_name}/schema",
            name="Table Schema",
            description="指定表的结构信息",
            mimeType="application/json",
        ),
        ResourceTemplate(
            uriTemplate="db://table/{table_name}/sample",
            name="Table Sample Data",
            description="指定表的示例数据（前 5 行）",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def read_resource(uri: str) -> str:
    import json
    conn = get_db()
    try:
        if uri == "db://schema/all":
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row["name"] for row in cursor.fetchall()]
            schema = {}
            for table in tables:
                cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
                schema[table] = [{"name": c["name"], "type": c["type"]} for c in cols]
            return json.dumps(schema, indent=2, ensure_ascii=False)

        if uri.startswith("db://table/") and uri.endswith("/schema"):
            table = uri.split("/")[3]
            cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
            schema = [{"name": c["name"], "type": c["type"], "pk": bool(c["pk"])} for c in cols]
            return json.dumps(schema, indent=2, ensure_ascii=False)

        if uri.startswith("db://table/") and uri.endswith("/sample"):
            table = uri.split("/")[3]
            rows = conn.execute(f"SELECT * FROM {table} LIMIT 5").fetchall()
            columns = [desc[0] for desc in conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
            data = [dict(row) for row in rows]
            return json.dumps({"columns": columns, "data": data}, indent=2, ensure_ascii=False)

        return json.dumps({"error": f"Unknown resource: {uri}"})
    finally:
        conn.close()


# ========== Prompts ==========

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="optimize_query",
            description="分析并优化一条 SQL 查询",
            arguments=[
                PromptArgument(
                    name="sql",
                    description="要优化的 SQL 查询",
                    required=True,
                ),
            ],
        ),
        Prompt(
            name="data_analysis",
            description="对指定表进行数据分析",
            arguments=[
                PromptArgument(
                    name="table_name",
                    description="要分析的表名",
                    required=True,
                ),
                PromptArgument(
                    name="goal",
                    description="分析目标（如：用户增长趋势、异常检测等）",
                    required=False,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    if name == "optimize_query":
        sql = arguments.get("sql", "")
        return GetPromptResult(
            description=f"优化 SQL 查询",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            f"请分析以下 SQL 查询并提供优化建议：\n\n"
                            f"```sql\n{sql}\n```\n\n"
                            f"请从以下角度分析：\n"
                            f"1. 执行计划分析\n"
                            f"2. 索引使用建议\n"
                            f"3. 查询改写建议\n"
                            f"4. 性能预估\n"
                            f"\n请先使用 describe_table 工具了解相关表结构。"
                        ),
                    ),
                )
            ],
        )

    elif name == "data_analysis":
        table = arguments.get("table_name", "")
        goal = arguments.get("goal", "全面概览")
        return GetPromptResult(
            description=f"分析表 {table}",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            f"请对数据库表 `{table}` 进行数据分析。\n\n"
                            f"分析目标：{goal}\n\n"
                            f"请按以下步骤进行：\n"
                            f"1. 先使用 describe_table 了解表结构\n"
                            f"2. 使用 query 工具执行分析查询\n"
                            f"3. 给出分析结论和建议\n"
                        ),
                    ),
                )
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
```

### 7.3 TypeScript SDK 开发指南

#### 7.3.1 安装

```bash
npm install @modelcontextprotocol/sdk
```

#### 7.3.2 TypeScript 示例

```typescript
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";

// 创建 Server 实例
const server = new Server(
  {
    name: "example-server",
    version: "1.0.0",
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// 注册 tools/list 处理器
server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      {
        name: "calculate",
        description: "Perform basic arithmetic calculations",
        inputSchema: {
          type: "object" as const,
          properties: {
            expression: {
              type: "string",
              description: "Mathematical expression to evaluate (e.g., '2 + 3 * 4')",
            },
          },
          required: ["expression"],
        },
      },
    ],
  };
});

// 注册 tools/call 处理器
server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  if (name === "calculate") {
    try {
      // 注意：生产环境不要用 eval，这里仅作示例
      const result = Function(`"use strict"; return (${args?.expression})`)();
      return {
        content: [
          {
            type: "text",
            text: `计算结果: ${args?.expression} = ${result}`,
          },
        ],
      };
    } catch (error) {
      return {
        content: [
          {
            type: "text",
            text: `计算错误: ${error}`,
          },
        ],
        isError: true,
      };
    }
  }

  throw new Error(`Unknown tool: ${name}`);
});

// 启动 Server
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("MCP Server running on stdio"); // stderr 用于日志
}

main().catch(console.error);
```

### 7.4 开发最佳实践

#### 7.4.1 Tool 设计原则

| 原则 | 说明 | 示例 |
|------|------|------|
| **原子性** | 每个 Tool 做一件事 | `create_issue` 而非 `manage_issues` |
| **描述清晰** | description 是 LLM 选择工具的依据 | 说明何时使用、输入输出是什么 |
| **Schema 严格** | 用 JSON Schema 精确定义输入 | 使用 enum、pattern、minLength 等约束 |
| **错误友好** | 返回有意义的错误信息 | 不要只返回 "error"，要说明原因 |
| **幂等安全** | 只读操作标记为 readOnly | 使用 annotations 标注 |
| **最小权限** | 只暴露必要的操作 | 不要暴露 DROP TABLE |

#### 7.4.2 常见陷阱

```python
# 陷阱 1：在 stdout 输出非 JSON-RPC 内容（会破坏协议）
print("Debug info")  # 错误！stdout 专用于协议消息
import sys
print("Debug info", file=sys.stderr)  # 正确！用 stderr 输出日志

# 陷阱 2：不处理参数校验
@server.call_tool()
async def call_tool(name, arguments):
    sql = arguments["sql"]  # 如果没传 sql 会 KeyError
    # 正确做法：校验参数
    sql = arguments.get("sql")
    if not sql:
        return [TextContent(type="text", text="错误：缺少 sql 参数")]

# 陷阱 3：阻塞异步事件循环
import time
time.sleep(5)  # 错误！阻塞整个事件循环
await asyncio.sleep(5)  # 正确！非阻塞等待

# 陷阱 4：不限制查询结果大小
rows = conn.execute("SELECT * FROM big_table").fetchall()  # 可能返回百万行
rows = conn.execute("SELECT * FROM big_table LIMIT 100").fetchall()  # 限制结果
```

### 7.5 测试 MCP Server

#### 7.5.1 使用 MCP Inspector

MCP Inspector 是官方提供的调试工具，可以可视化地测试 MCP Server：

```bash
# 安装并启动 Inspector
npx @modelcontextprotocol/inspector

# Inspector 会在浏览器中打开
# 你可以：
# 1. 连接到本地或远程 MCP Server
# 2. 查看 tools/list 的结果
# 3. 手动调用 tools/call
# 4. 查看原始 JSON-RPC 消息
```

#### 7.5.2 用 Python 编写单元测试

```python
import pytest
import asyncio
from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


@pytest.mark.asyncio
async def test_weather_server():
    """测试天气 MCP Server"""
    params = StdioServerParameters(
        command="python",
        args=["weather_server.py"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 测试初始化
            await session.initialize()

            # 测试 tools/list
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "get_weather" in tool_names
            assert "compare_weather" in tool_names

            # 测试 tools/call
            result = await session.call_tool("get_weather", {"city": "beijing"})
            assert len(result.content) > 0
            assert "beijing" in result.content[0].text.lower()
            assert "22" in result.content[0].text  # 预期温度

            # 测试错误输入
            result = await session.call_tool("get_weather", {"city": "invalid"})
            assert "未找到" in result.content[0].text
```

---

## 8. 作为 Agent 开发者如何集成 MCP

### 8.1 集成的完整生命周期

如果你正在开发一个 AI Agent，以下是集成 MCP 的完整流程：

```mermaid
sequenceDiagram
    participant Config as 配置文件
    participant Host as Agent Host
    participant MCPMgr as MCP 管理器
    participant Client as MCP Client
    participant Server as MCP Server
    participant LLM as LLM API
    participant User as 用户
    
    Note over Config,User: 阶段 1：启动与初始化
    Host->>Config: 读取 mcp.json 配置
    Config-->>Host: Server 列表 + 启动参数
    
    loop 对每个配置的 Server
        Host->>MCPMgr: 创建 MCP Client
        MCPMgr->>Server: 启动 Server 进程/连接
        MCPMgr->>Client: 协议握手 (initialize)
        Client->>Server: initialize
        Server-->>Client: capabilities + serverInfo
        Client->>Server: notifications/initialized
        Client->>Server: tools/list
        Server-->>Client: tools 定义列表
        Client-->>MCPMgr: 工具定义
    end
    
    MCPMgr-->>Host: 所有 MCP 工具定义
    
    Note over Config,User: 阶段 2：合并工具
    Host->>Host: 内置工具 + MCP 工具 → 合并工具列表
    
    Note over Config,User: 阶段 3：对话循环
    User->>Host: 用户输入消息
    Host->>LLM: messages + 合并后的 tools
    LLM-->>Host: response (可能包含 tool_use)
    
    alt LLM 调用了 MCP 工具
        Host->>Host: 识别 mcp__ 前缀
        Host->>Host: 权限检查/用户确认
        Host->>MCPMgr: 路由到对应 Client
        MCPMgr->>Client: call_tool(name, args)
        Client->>Server: tools/call
        Server-->>Client: result
        Client-->>MCPMgr: result
        MCPMgr-->>Host: result
        Host->>LLM: tool_result
        LLM-->>Host: 最终回答
    else LLM 调用了内置工具
        Host->>Host: 直接执行内置工具
        Host->>LLM: tool_result
        LLM-->>Host: 最终回答
    end
    
    Host-->>User: 展示回答
```

### 8.2 Python Client 完整代码示例

以下是一个**可运行的** Python Agent 示例，展示如何集成 MCP：

```python
"""
完整的 MCP Client 集成示例
演示一个简单的 AI Agent 如何使用 MCP 工具
"""
import asyncio
import json
from dataclasses import dataclass, field
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from anthropic import Anthropic


@dataclass
class MCPServerConfig:
    """MCP Server 配置"""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPTool:
    """MCP 工具（包含来源信息）"""
    server_name: str
    original_name: str
    prefixed_name: str  # mcp__{server}__{tool}
    description: str
    input_schema: dict


class MCPIntegratedAgent:
    """
    一个集成了 MCP 的 AI Agent 示例。
    
    核心流程：
    1. 启动时连接所有配置的 MCP Server
    2. 发现所有 MCP 工具
    3. 将 MCP 工具和内置工具合并后传给 LLM
    4. LLM 的 tool call 根据前缀路由到正确的执行器
    """

    def __init__(self, mcp_configs: list[MCPServerConfig]):
        self.mcp_configs = mcp_configs
        self.anthropic = Anthropic()
        self.mcp_tools: list[MCPTool] = []
        self.sessions: dict[str, ClientSession] = {}
        self.messages: list[dict] = []

    async def connect_mcp_servers(self):
        """连接所有 MCP Server 并发现工具"""
        for config in self.mcp_configs:
            print(f"[MCP] 连接 Server: {config.name}")
            
            params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env if config.env else None,
            )

            # 注意：实际使用中需要管理连接的生命周期
            # 这里简化处理，实际应使用 contextmanager
            read, write = await stdio_client(params).__aenter__()
            session = await ClientSession(read, write).__aenter__()
            
            # 协议握手
            await session.initialize()
            print(f"[MCP] {config.name} 已连接")
            
            # 发现工具
            tools_result = await session.list_tools()
            for tool in tools_result.tools:
                prefixed_name = f"mcp__{config.name}__{tool.name}"
                self.mcp_tools.append(MCPTool(
                    server_name=config.name,
                    original_name=tool.name,
                    prefixed_name=prefixed_name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                ))
                print(f"[MCP]   发现工具: {prefixed_name}")
            
            self.sessions[config.name] = session

    def _build_tools_for_llm(self) -> list[dict]:
        """
        构建传给 LLM 的 tools 参数。
        合并内置工具和 MCP 工具。
        """
        tools = []

        # 内置工具（示例）
        tools.append({
            "name": "get_current_time",
            "description": "获取当前时间",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        })

        # MCP 工具
        for mcp_tool in self.mcp_tools:
            tools.append({
                "name": mcp_tool.prefixed_name,
                "description": f"[{mcp_tool.server_name}] {mcp_tool.description}",
                "input_schema": mcp_tool.input_schema,
            })

        return tools

    async def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """
        执行工具调用。
        根据工具名前缀路由到内置执行器或 MCP Client。
        """
        if tool_name.startswith("mcp__"):
            # MCP 工具
            parts = tool_name.split("__", 2)
            server_name = parts[1]
            original_name = parts[2]

            session = self.sessions.get(server_name)
            if not session:
                return f"错误：MCP Server '{server_name}' 未连接"

            print(f"[MCP] 调用工具: {server_name}.{original_name}({json.dumps(arguments, ensure_ascii=False)})")
            result = await session.call_tool(original_name, arguments)

            # 提取文本内容
            texts = []
            for content in result.content:
                if hasattr(content, "text"):
                    texts.append(content.text)
            return "\n".join(texts) if texts else "（无返回内容）"

        elif tool_name == "get_current_time":
            from datetime import datetime
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        else:
            return f"未知工具: {tool_name}"

    async def chat(self, user_message: str) -> str:
        """
        处理一轮对话。
        包含完整的 tool use 循环。
        """
        self.messages.append({"role": "user", "content": user_message})

        tools = self._build_tools_for_llm()

        # Agentic loop：LLM 可能多次调用工具
        while True:
            response = self.anthropic.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=4096,
                system="你是一个有用的 AI 助手，可以使用各种工具帮助用户。",
                messages=self.messages,
                tools=tools,
            )

            # 检查是否有 tool_use
            has_tool_use = any(
                block.type == "tool_use" for block in response.content
            )

            if not has_tool_use:
                # 没有工具调用，提取文本回复
                assistant_text = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        assistant_text += block.text
                self.messages.append({"role": "assistant", "content": response.content})
                return assistant_text

            # 有工具调用：执行并继续
            self.messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result_text = await self._execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    })

            self.messages.append({"role": "user", "content": tool_results})
            # 循环继续，让 LLM 看到工具结果


async def main():
    """使用示例"""
    configs = [
        MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        ),
        # 可以添加更多 Server
        # MCPServerConfig(
        #     name="github",
        #     command="npx",
        #     args=["-y", "@modelcontextprotocol/server-github"],
        #     env={"GITHUB_TOKEN": "ghp_xxx"},
        # ),
    ]

    agent = MCPIntegratedAgent(configs)
    await agent.connect_mcp_servers()

    # 对话
    print("Agent 已就绪，输入消息开始对话（输入 'quit' 退出）")
    while True:
        user_input = input("\n你: ")
        if user_input.strip().lower() == "quit":
            break
        response = await agent.chat(user_input)
        print(f"\nAgent: {response}")


if __name__ == "__main__":
    asyncio.run(main())
```

### 8.3 工具延迟加载策略

当配置了大量 MCP Server 时，所有工具定义会占用大量 token（每个工具的 name + description + inputSchema 都消耗 token）。解决方案是**延迟加载**：

```python
class LazyToolLoader:
    """
    延迟加载策略：
    1. 初始时只加载工具的 name 和简短 description
    2. LLM 需要使用某个工具时，才加载完整的 inputSchema
    3. 类似 Claude Code 的 shouldDefer + ToolSearch 机制
    """

    def __init__(self):
        self.tool_summaries: list[dict] = []  # 精简信息
        self.tool_full_definitions: dict[str, dict] = {}  # 完整定义
        self.active_tools: set[str] = set()  # 当前激活的工具

    def register_tools(self, tools: list[MCPTool]):
        """注册工具，但只保留摘要"""
        for tool in tools:
            self.tool_summaries.append({
                "name": tool.prefixed_name,
                "summary": tool.description[:100],  # 截断描述
            })
            self.tool_full_definitions[tool.prefixed_name] = {
                "name": tool.prefixed_name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }

    def get_tools_for_llm(self, query: str = "") -> list[dict]:
        """
        根据当前上下文，返回相关工具的完整定义。
        使用简单的关键词匹配（实际可用向量检索）。
        """
        # 始终包含已激活的工具
        relevant = set(self.active_tools)

        # 根据 query 匹配相关工具
        if query:
            for summary in self.tool_summaries:
                if any(kw in summary["summary"].lower() for kw in query.lower().split()):
                    relevant.add(summary["name"])

        # 返回完整定义
        return [
            self.tool_full_definitions[name]
            for name in relevant
            if name in self.tool_full_definitions
        ]

    def activate_tool(self, tool_name: str):
        """激活一个工具（后续请求中会包含其完整定义）"""
        self.active_tools.add(tool_name)

    def get_tool_search_tool(self) -> dict:
        """
        提供一个特殊的 "搜索工具" 给 LLM。
        LLM 可以通过这个工具发现和激活其他工具。
        """
        return {
            "name": "search_available_tools",
            "description": (
                "Search for available tools by keyword. "
                "Use this when you need a capability that isn't in your current toolset. "
                f"Available tools: {', '.join(s['name'] + ': ' + s['summary'] for s in self.tool_summaries)}"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search for tools",
                    }
                },
                "required": ["query"],
            },
        }
```

### 8.4 权限系统集成

Agent 在执行 MCP 工具调用前，通常需要进行权限检查：

```python
class PermissionManager:
    """
    权限管理器
    决定是否需要用户确认才能执行工具调用
    """

    # 权限规则
    RULES = {
        # 只读操作：自动允许
        "auto_allow": [
            "mcp__filesystem__read_file",
            "mcp__filesystem__list_directory",
            "mcp__github__list_pulls",
            "mcp__github__get_issue",
            "mcp__postgres__query",  # 只读查询
        ],
        # 需要确认的操作
        "requires_confirmation": [
            "mcp__filesystem__write_file",
            "mcp__github__create_issue",
            "mcp__github__merge_pull",
            "mcp__slack__send_message",
        ],
        # 始终拒绝的操作
        "always_deny": [
            "mcp__filesystem__delete_file",
            "mcp__github__delete_repo",
        ],
    }

    @classmethod
    def check_permission(cls, tool_name: str, arguments: dict) -> str:
        """
        检查工具调用权限。
        返回: "allow", "confirm", "deny"
        """
        if tool_name in cls.RULES["always_deny"]:
            return "deny"
        if tool_name in cls.RULES["auto_allow"]:
            return "allow"
        if tool_name in cls.RULES["requires_confirmation"]:
            return "confirm"
        # 默认需要确认
        return "confirm"

    @classmethod
    async def request_user_confirmation(cls, tool_name: str, arguments: dict) -> bool:
        """请求用户确认"""
        print(f"\n[权限] 工具 '{tool_name}' 请求执行：")
        print(f"  参数: {json.dumps(arguments, indent=2, ensure_ascii=False)}")
        response = input("  允许执行？(y/n): ")
        return response.strip().lower() == "y"
```

---

## 9. 安全模型与认证机制

### 9.1 MCP 的安全层次

MCP 的安全设计分为多个层次：

```mermaid
graph TB
    subgraph "MCP 安全层次模型"
        L1[层次 1：传输安全<br/>TLS/mTLS 加密通信]
        L2[层次 2：认证<br/>OAuth 2.1 验证调用者身份]
        L3[层次 3：授权<br/>Server 端的权限控制]
        L4[层次 4：用户确认<br/>Host 端的操作审批]
        L5[层次 5：沙箱隔离<br/>Server 进程的运行限制]
        
        L1 --> L2
        L2 --> L3
        L3 --> L4
        L4 --> L5
    end
    
    style L1 fill:#ffcdd2
    style L2 fill:#f8bbd0
    style L3 fill:#e1bee7
    style L4 fill:#c5cae9
    style L5 fill:#bbdefb
```

### 9.2 传输安全

**Stdio 模式**：通过操作系统管道通信，天然安全（进程间通信，不经过网络）。

**HTTP 模式**：
- 生产环境必须使用 **HTTPS（TLS）**
- 可以使用 **mTLS（双向 TLS）** 进行客户端证书验证
- 禁止在非加密通道上传输敏感数据

### 9.3 OAuth 2.1 认证

#### 9.3.1 为什么需要认证？

**认证不是"不信任 MCP Server"——而是 MCP Server 不信任调用者。**

MCP Server 可能连接到敏感服务（GitHub 私有仓库、内部数据库）。Server 需要验证调用者的身份，确保只有授权用户才能访问。

举例：
- GitHub MCP Server 连接了你的 GitHub 账号
- 如果任何人都能调用这个 Server，就能操作你的私有仓库
- 认证确保只有经过授权的 Client 才能使用 Server

#### 9.3.2 认证流程

```mermaid
sequenceDiagram
    participant User as 用户
    participant Client as MCP Client
    participant Server as MCP Server
    participant OAuth as OAuth 提供者<br/>（如 GitHub OAuth）
    
    Client->>Server: initialize 请求
    Server-->>Client: 401 Unauthorized<br/>+ WWW-Authenticate header<br/>+ OAuth 元数据 URL
    
    Client->>OAuth: 获取 OAuth 元数据<br/>（authorization_endpoint, token_endpoint 等）
    OAuth-->>Client: OAuth 配置信息
    
    Client->>User: 打开浏览器，引导用户登录授权
    User->>OAuth: 登录并授权
    OAuth-->>User: 重定向到回调 URL（带 authorization_code）
    User-->>Client: 传递 authorization_code
    
    Client->>OAuth: 用 code 换取 access_token<br/>（POST /token）
    OAuth-->>Client: access_token + refresh_token
    
    Client->>Server: initialize 请求<br/>Authorization: Bearer {access_token}
    Server-->>Client: 200 OK {capabilities, serverInfo}
    
    Note over Client,Server: 后续所有请求都携带 token
    Client->>Server: tools/call<br/>Authorization: Bearer {access_token}
    Server-->>Client: 200 OK {result}
```

#### 9.3.3 关键理解

**认证是 Server 方实现的**（不是 Agent/Client 方）：

| 场景 | Server 是否需要认证 | 说明 |
|------|-------------------|------|
| 本地文件系统 Server | 不需要 | 访问的是本地用户自己的文件 |
| 连接本地数据库的 Server | 通常不需要 | 数据库自身有认证 |
| 连接 GitHub API 的 Server | 需要 | 需要确认用户的 GitHub 身份 |
| 公开部署的远程 Server | 必须 | 暴露在网络上，必须验证调用者 |

如果 Server 不需要认证（如本地 filesystem server），就不实现认证代码，Client 也不会触发认证流程。

### 9.4 授权与权限控制

Server 在收到 tool call 后，可以根据调用者的身份进行细粒度的权限控制：

```python
class AuthorizationMiddleware:
    """Server 端的授权中间件"""
    
    PERMISSIONS = {
        "read": ["query", "list_tables", "describe_table"],
        "write": ["insert_record", "update_record"],
        "admin": ["create_table", "drop_table", "grant_permission"],
    }
    
    def check_authorization(self, user_role: str, tool_name: str) -> bool:
        """检查用户角色是否有权限调用指定工具"""
        allowed_tools = set()
        
        if user_role in ("read", "write", "admin"):
            allowed_tools.update(self.PERMISSIONS["read"])
        if user_role in ("write", "admin"):
            allowed_tools.update(self.PERMISSIONS["write"])
        if user_role == "admin":
            allowed_tools.update(self.PERMISSIONS["admin"])
        
        return tool_name in allowed_tools
```

### 9.5 用户确认机制

Host 端在执行 MCP 工具调用前，可以要求用户确认：

```
[Agent] 我需要执行以下操作：
  工具: mcp__github__create_issue
  参数:
    repo: anthropics/mcp
    title: "Fix authentication bug"
    body: "..."

是否允许？[y/n/always allow]
```

这是 MCP 安全模型的**最后一道防线**——即使 Server 是恶意的，用户也可以拒绝可疑操作。

### 9.6 沙箱与隔离

对于 stdio 模式的 MCP Server：
- Server 作为**子进程**运行，与 Host 进程隔离
- 可以通过操作系统机制限制 Server 进程的权限（文件访问、网络访问等）
- Server 崩溃不会影响 Host
- 可以使用 Docker 容器进一步隔离

---

## 10. MCP 实际落地的挑战与解决方案

### 10.1 挑战总览

| # | 挑战 | 严重性 | 影响 |
|---|------|--------|------|
| 1 | 上下文膨胀 | 高 | 大量工具定义消耗 token，影响性能和成本 |
| 2 | 安全风险 | 高 | 恶意 MCP Server、权限泄漏 |
| 3 | 延迟问题 | 中 | 远程 Server 的网络延迟影响用户体验 |
| 4 | 发现性 | 中 | 用户不知道有哪些 MCP Server 可用 |
| 5 | 质量参差不齐 | 中 | 社区 Server 的质量和可靠性不一 |
| 6 | 调试困难 | 中 | JSON-RPC 消息不直观，问题定位困难 |
| 7 | 版本兼容 | 低 | 协议版本升级时的兼容性 |

### 10.2 挑战 1：上下文膨胀

**问题**：每个 MCP 工具的定义（name + description + inputSchema）都需要发送给 LLM。如果有 50 个 MCP 工具，光工具定义就可能占用数千 token。

**解决方案**：

**方案 A：延迟加载（Deferred Loading）**

Claude Code 的做法——将工具分为两类：
- **核心工具**：始终加载（如 Read、Edit、Bash）
- **可延迟工具**：仅在需要时加载

LLM 通过一个特殊的 `ToolSearch` 工具来发现和激活被延迟的工具。

**方案 B：动态工具选择**

根据用户消息的语义，动态选择最相关的工具子集：
```python
def select_relevant_tools(user_message: str, all_tools: list) -> list:
    """根据用户消息选择相关工具"""
    # 方法 1：关键词匹配
    # 方法 2：向量相似度
    # 方法 3：LLM 预筛选
    ...
```

**方案 C：工具分组**

将工具按功能分组，用户或 Agent 选择激活哪些组：
```json
{
    "tool_groups": {
        "code_management": ["github__create_issue", "github__list_pulls"],
        "database": ["postgres__query", "postgres__list_tables"],
        "communication": ["slack__send_message", "slack__list_channels"]
    }
}
```

### 10.3 挑战 2：安全风险

**威胁模型**：

| 威胁 | 描述 | 缓解措施 |
|------|------|---------|
| 恶意 Server | Server 返回诱导性内容 | 信任列表 + 用户确认 |
| 权限过大 | Server 暴露危险操作 | 最小权限原则 + 权限规则 |
| 数据泄漏 | 敏感数据通过 Server 泄漏 | 数据分类 + 审计日志 |
| 提示注入 | Server 结果包含恶意提示 | 输出过滤 + 隔离上下文 |

### 10.4 挑战 3：延迟优化

```python
# 策略 1：连接池
class MCPConnectionPool:
    """复用 MCP 连接，减少握手开销"""
    def __init__(self):
        self.pool: dict[str, ClientSession] = {}
    
    async def get_session(self, server_name: str) -> ClientSession:
        if server_name not in self.pool:
            self.pool[server_name] = await self._create_session(server_name)
        return self.pool[server_name]

# 策略 2：并行调用
async def parallel_tool_calls(calls: list[tuple[str, dict]]) -> list:
    """并行执行多个不相关的工具调用"""
    tasks = [
        execute_tool(name, args) for name, args in calls
    ]
    return await asyncio.gather(*tasks)

# 策略 3：结果缓存
from functools import lru_cache

class CachedMCPClient:
    """对只读工具的结果进行缓存"""
    def __init__(self, session: ClientSession, ttl: int = 60):
        self.session = session
        self.cache = {}
        self.ttl = ttl
    
    async def call_tool(self, name: str, args: dict) -> str:
        # 只缓存标记为 readOnly 的工具
        cache_key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if cache_key in self.cache:
            cached_time, result = self.cache[cache_key]
            if time.time() - cached_time < self.ttl:
                return result
        
        result = await self.session.call_tool(name, args)
        self.cache[cache_key] = (time.time(), result)
        return result
```

### 10.5 挑战 4：Server 发现

**当前方案**：

| 发现方式 | 说明 |
|----------|------|
| 官方仓库 | GitHub `modelcontextprotocol/servers` |
| 社区注册表 | mcp.run、smithery.ai 等 |
| 包管理器 | npm 搜索 `@modelcontextprotocol/` |
| AI 工具内置 | Claude Desktop 推荐列表 |

**未来方向**：
- 标准化的 MCP Server 注册表协议
- AI 工具内的 Server 商店
- 自动发现（DNS-SD、mDNS）

---

## 11. 常见疑惑深度解答

### 11.1 Q：Tool、Skill、MCP 之间是什么关系？

这是容易混淆的概念。让我们理清：

| 概念 | 定义 | 生命周期 | 示例 |
|------|------|---------|------|
| **Tool** | LLM 可以调用的函数 | 单次调用，同步返回结果 | Read、Edit、Bash、mcp__github__create_issue |
| **Skill** | 预定义的多步骤工作流模板 | 一次触发，可能包含多次 Tool 调用 | /commit（包含 git status → git diff → git add → git commit） |
| **MCP** | Agent 与外部服务的通信协议 | 持久连接，多次交互 | MCP Server for GitHub |

**关系图**：

```
MCP 协议
  └── 提供 Tools（通过 MCP Server 暴露）
        └── Agent 将 MCP Tools 和内置 Tools 统一呈现给 LLM
              └── LLM 调用 Tools 时，Agent 根据来源路由执行
                    └── Skill 可以编排多个 Tool 调用的流程
```

**关键理解**：
- MCP 是**协议**（通信规范）
- Tool 是**能力单元**（可以来自内置或 MCP）
- Skill 是**高层编排**（组合多个 Tool 完成复杂任务）
- MCP Server 通过 MCP 协议向 Agent 提供 Tool

### 11.2 Q：Tool 的"槽位"如何理解？

调用 LLM API 时有三个主要参数：

```python
response = client.messages.create(
    system="You are a helpful assistant.",    # 系统提示（槽位 1）
    messages=[{"role": "user", "content": "..."}],  # 对话消息（槽位 2）
    tools=[{"name": "...", "inputSchema": {...}}],    # 工具定义（槽位 3）
)
```

这三个参数（system、messages、tools）是 **API 层面的三个独立"槽位"**：

| 槽位 | 参数 | 内容 | Token 消耗 |
|------|------|------|-----------|
| 系统提示 | `system` | Agent 的身份、行为规则 | 是，每次请求都发送 |
| 对话消息 | `messages` | 用户和 AI 的对话历史 | 是，随对话增长 |
| 工具定义 | `tools` | 工具的 name、description、schema | **是，但格式经过 API 优化** |

**"槽位"这个词的意义**：

开发者不需要手动把工具描述写进 system prompt。API 提供了专门的 `tools` 参数——这是一个独立的"槽位"。LLM 提供商（如 Anthropic）会在内部高效地处理这个参数，通常比手写在 system prompt 里更省 token、效果更好。

**注意**：`tools` 参数确实消耗 token。模型需要"看到"工具定义才能决定是否调用。这就是为什么工具数量多时会导致"上下文膨胀"问题（参见 10.2 节）。

### 11.3 Q：MCP 就是提供工具给 Agent 作为能力补充？

**基本正确，但不完全。**

MCP 提供**三种**能力，Tool 只是其中之一：

| 能力 | 是否类似"给 Agent 补充工具" | 细微区别 |
|------|--------------------------|---------|
| **Tools** | 是。转换后与内置工具"一视同仁" | Agent（LLM）主动决定调用 |
| **Resources** | 不是。是被动的只读数据 | 类似"给 Agent 提供参考资料" |
| **Prompts** | 不是。是预设的交互模式 | 类似"给用户提供操作手册" |

如果一个 MCP Server 只提供 Tools（大多数 Server 目前如此），那么接入后确实和内置工具无异——LLM 看不出区别。但 Resources 和 Prompts 是 Tool 做不到的：

- **Resources** 提供结构化的只读数据（如数据库 schema），可以被 Host 嵌入上下文，而不需要 LLM 主动"调用"
- **Prompts** 提供标准化的交互模板（如代码审查流程），由用户选择触发，而非 LLM 自主决定

### 11.4 Q：MCP 和 Function Calling 有什么区别？

**Function Calling** 是 LLM API 的特性——让 LLM 能够输出结构化的"工具调用意图"。

**MCP** 是 Agent 与外部服务的通信协议——标准化地获取和执行工具。

它们处于**不同层次**，互相配合：

```
层次结构：

[LLM API 层]
    Function Calling
    ─────────────────
    LLM 输出 tool_use → "我想调用 create_issue(title=...)"
    
[Agent 层]
    Tool Routing
    ─────────────────
    Agent 判断：这是内置工具还是 MCP 工具？
    
[协议层]
    MCP Protocol
    ─────────────────
    Agent 通过 MCP 协议将 tool call 发送到对应 Server
    
[执行层]
    MCP Server
    ─────────────────
    Server 调用真实 API，返回结果
```

**简单类比**：
- Function Calling 像是"嘴巴"（LLM 说出想做什么）
- MCP 像是"手"（Agent 实际去做）
- 两者缺一不可

### 11.5 Q：为什么 MCP 不直接让 LLM 调用远程 API？

有人可能会问：为什么不直接把 REST API 的 OpenAPI Spec 给 LLM，让它生成 HTTP 请求？

原因：

1. **安全性**：LLM 不应持有 API 密钥。如果让 LLM 生成 curl 命令，密钥会出现在上下文中
2. **可靠性**：LLM 生成的 API 调用可能格式错误。MCP Server 的 inputSchema 提供严格校验
3. **抽象层**：MCP Server 可以将复杂的多步 API 操作封装为一个简单的 Tool
4. **状态管理**：MCP Server 可以维护会话状态（如数据库连接池）
5. **权限控制**：MCP Server 可以限制暴露的操作（如只允许 SELECT，不允许 DELETE）

### 11.6 Q：MCP Server 会不会太多，导致"工具爆炸"？

**确实是个问题。** 目前的缓解方案：

1. **按需配置**：用户只配置自己需要的 MCP Server
2. **延迟加载**：参见 8.3 节的 LazyToolLoader
3. **工具搜索**：提供 ToolSearch 元工具，让 LLM 动态发现
4. **智能选择**：根据用户消息语义自动选择相关工具

**长期解决方案**：
- MCP 可能会引入"工具命名空间"机制
- Agent 可以维护"工具使用频率"统计，优先加载常用工具
- 基于 embedding 的工具检索

### 11.7 Q：如果 MCP Server 返回恶意内容怎么办？

这是**提示注入**的一种形式。MCP Server 的返回结果会被送入 LLM，如果结果中包含恶意指令，LLM 可能被误导。

**缓解措施**：

| 层次 | 措施 | 说明 |
|------|------|------|
| 信任管理 | 只使用受信任的 Server | 优先使用官方/知名 Server |
| 输出校验 | 过滤 Server 返回的内容 | 检测并移除可疑的指令性文本 |
| 上下文隔离 | 将 tool result 与 system prompt 隔离 | LLM 层面的安全设计 |
| 用户确认 | 关键操作需要人工审核 | 最后一道防线 |
| 审计日志 | 记录所有 MCP 交互 | 事后追溯和分析 |

---

## 12. MCP 生态全景

### 12.1 官方 MCP Server

Anthropic 官方维护的 MCP Server（在 `modelcontextprotocol/servers` 仓库）：

| Server | 功能 | 传输方式 |
|--------|------|---------|
| `server-filesystem` | 文件读写、目录操作 | stdio |
| `server-github` | GitHub API（Issue、PR、文件等） | stdio |
| `server-postgres` | PostgreSQL 查询 | stdio |
| `server-slack` | Slack 消息、频道管理 | stdio |
| `server-brave-search` | Brave 搜索引擎 | stdio |
| `server-google-maps` | Google 地图 API | stdio |
| `server-memory` | 持久化的知识图谱 | stdio |
| `server-puppeteer` | 浏览器自动化 | stdio |
| `server-sqlite` | SQLite 数据库操作 | stdio |
| `server-everart` | AI 图像生成 | stdio |
| `server-sequential-thinking` | 结构化思维推理 | stdio |

### 12.2 社区 MCP Server

社区贡献了大量 MCP Server：

| 类别 | Server 示例 | 功能 |
|------|------------|------|
| **数据库** | MongoDB, MySQL, Redis, ElasticSearch | 各种数据库的查询和管理 |
| **云服务** | AWS, GCP, Azure, Cloudflare | 云资源管理 |
| **开发工具** | GitLab, Bitbucket, Linear, Sentry | 开发流程管理 |
| **通信** | Discord, Telegram, Email | 消息发送和管理 |
| **生产力** | Notion, Todoist, Google Calendar | 笔记和日程管理 |
| **数据** | Snowflake, BigQuery, Databricks | 大数据分析 |
| **AI/ML** | HuggingFace, Replicate | AI 模型和数据集 |

### 12.3 MCP 支持的 Host（AI 应用）

| Host | 类型 | MCP 支持程度 |
|------|------|-------------|
| Claude Desktop | 桌面 GUI | 完整支持（Anthropic 官方） |
| Claude Code | CLI | 完整支持（Anthropic 官方） |
| Cursor | IDE | 支持 Tools |
| Windsurf | IDE | 支持 Tools |
| Continue | IDE 插件 | 支持 Tools + Resources |
| Zed | 编辑器 | 支持 Tools |
| Sourcegraph Cody | AI 编程 | 支持 Tools |
| 自定义 Agent | 任意 | 使用 SDK 自行集成 |

### 12.4 生态系统关系图

```mermaid
graph TB
    subgraph "MCP 生态全景"
        subgraph "Host 层（AI 应用）"
            H1[Claude Desktop]
            H2[Claude Code]
            H3[Cursor]
            H4[Windsurf]
            H5[自定义 Agent]
        end
        
        subgraph "SDK 层"
            SDK1[TypeScript SDK]
            SDK2[Python SDK]
            SDK3[Kotlin SDK]
            SDK4[Go SDK]
        end
        
        subgraph "Server 层"
            subgraph "官方 Server"
                S1[GitHub]
                S2[PostgreSQL]
                S3[Filesystem]
                S4[Slack]
            end
            
            subgraph "社区 Server"
                S5[MongoDB]
                S6[Notion]
                S7[AWS]
                S8[Discord]
            end
        end
        
        subgraph "工具层"
            T1[MCP Inspector<br/>调试工具]
            T2[mcp.run<br/>Server 注册表]
            T3[smithery.ai<br/>Server 市场]
        end
        
        H1 & H2 & H3 & H4 & H5 ---|MCP 协议| S1 & S2 & S3 & S4 & S5 & S6 & S7 & S8
        SDK1 & SDK2 & SDK3 & SDK4 -.- S1 & S2 & S3 & S4 & S5 & S6 & S7 & S8
    end
```

---

## 13. MCP 与其他协议的对比

### 13.1 MCP vs ChatGPT Plugins/GPTs Actions

| 维度 | MCP | ChatGPT Plugins / GPTs Actions |
|------|-----|-------------------------------|
| 标准化 | 开放标准，任何 Agent 可用 | OpenAI 专有 |
| 运行模式 | 本地 + 远程 | 仅远程（HTTP） |
| 能力类型 | Tools + Resources + Prompts | 仅 Actions（类似 Tools） |
| 传输方式 | stdio / HTTP / WebSocket | 仅 HTTP |
| 安全性 | OAuth 2.1 + 用户确认 + 沙箱 | OAuth + 用户确认 |
| 生态 | 跨 Agent 通用 | 仅限 ChatGPT |
| 协议规范 | 基于 JSON-RPC 2.0 | 基于 OpenAPI Spec |

### 13.2 MCP vs LangChain Tools

| 维度 | MCP | LangChain Tools |
|------|-----|-----------------|
| 层次 | 通信协议 | 编程框架 |
| 语言 | 任何语言 | Python / TypeScript |
| 独立性 | Server 是独立进程/服务 | Tool 是函数/类 |
| 复用性 | 跨 Agent 复用 | 跨 Chain 复用，但限于 LangChain |
| 标准化 | 有明确的协议规范 | 框架内的接口约定 |

### 13.3 MCP vs OpenAI Agents SDK Tools

| 维度 | MCP | OpenAI Agents SDK |
|------|-----|-------------------|
| 定位 | 开放协议标准 | OpenAI 生态内的 SDK |
| 模型限制 | 任何 LLM | 主要面向 OpenAI 模型 |
| 工具共享 | 通过 MCP Server 跨 Agent 共享 | 在 Agent 间共享 Tool 定义 |
| 传输方式 | stdio / HTTP / WebSocket | 进程内调用 |

### 13.4 MCP vs LSP（Language Server Protocol）

MCP 的设计深受 LSP 启发，两者有很强的类比关系：

| 维度 | LSP | MCP |
|------|-----|-----|
| 发起者 | Microsoft | Anthropic |
| 解决的问题 | N 个 IDE × M 种语言 | N 个 Agent × M 种服务 |
| Client | IDE（VS Code、Neovim 等） | AI 应用（Claude、Cursor 等） |
| Server | 语言分析工具 | 数据/服务适配器 |
| 协议基础 | JSON-RPC 2.0 | JSON-RPC 2.0 |
| 传输方式 | stdio / TCP | stdio / HTTP / WebSocket |
| 核心能力 | 补全、跳转、诊断、格式化 | Tools、Resources、Prompts |
| 成熟度 | 非常成熟（2016 年） | 快速发展中（2024 年） |

---

## 14. 实战案例：从零构建完整 MCP 系统

### 14.1 项目概述

我们将构建一个完整的 MCP 系统，包含：
1. 一个自定义 MCP Server（笔记管理）
2. 一个简单的 AI Agent（集成 MCP）

### 14.2 MCP Server：笔记管理器

```python
"""
note_server.py - 一个完整的笔记管理 MCP Server
支持 Tools + Resources + Prompts
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool, TextContent, Resource, Prompt, PromptArgument,
    PromptMessage, GetPromptResult,
)

NOTES_DIR = Path("./notes")
NOTES_DIR.mkdir(exist_ok=True)

server = Server("note-manager")


# ========== Tools ==========

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="create_note",
            description="创建一条新笔记。笔记将保存为 Markdown 文件。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题"},
                    "content": {"type": "string", "description": "笔记内容（支持 Markdown）"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "标签列表",
                    },
                },
                "required": ["title", "content"],
            },
        ),
        Tool(
            name="search_notes",
            description="搜索笔记。支持按标题和内容关键词搜索。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="list_notes",
            description="列出所有笔记的标题和创建时间。",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="delete_note",
            description="删除指定笔记（不可恢复）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "要删除的笔记标题"},
                },
                "required": ["title"],
            },
            annotations={"destructive": True, "requiresConfirmation": True},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "create_note":
        title = arguments["title"]
        content = arguments["content"]
        tags = arguments.get("tags", [])
        
        # 生成文件名
        safe_title = title.replace(" ", "_").replace("/", "_")
        filepath = NOTES_DIR / f"{safe_title}.md"
        
        # 写入笔记
        metadata = {
            "title": title,
            "tags": tags,
            "created_at": datetime.now().isoformat(),
        }
        note_content = f"---\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n---\n\n{content}"
        filepath.write_text(note_content, encoding="utf-8")
        
        return [TextContent(type="text", text=f"笔记已创建：{title}\n路径：{filepath}")]

    elif name == "search_notes":
        query = arguments["query"].lower()
        results = []
        for filepath in NOTES_DIR.glob("*.md"):
            content = filepath.read_text(encoding="utf-8")
            if query in content.lower():
                # 提取标题
                try:
                    meta_start = content.index("---") + 3
                    meta_end = content.index("---", meta_start)
                    metadata = json.loads(content[meta_start:meta_end])
                    title = metadata.get("title", filepath.stem)
                except (ValueError, json.JSONDecodeError):
                    title = filepath.stem
                results.append(title)
        
        if results:
            return [TextContent(type="text", text=f"找到 {len(results)} 条匹配笔记：\n" + "\n".join(f"  - {r}" for r in results))]
        return [TextContent(type="text", text="未找到匹配的笔记。")]

    elif name == "list_notes":
        notes = []
        for filepath in sorted(NOTES_DIR.glob("*.md")):
            content = filepath.read_text(encoding="utf-8")
            try:
                meta_start = content.index("---") + 3
                meta_end = content.index("---", meta_start)
                metadata = json.loads(content[meta_start:meta_end])
                notes.append(f"  - {metadata.get('title', filepath.stem)} (创建于 {metadata.get('created_at', '未知')})")
            except (ValueError, json.JSONDecodeError):
                notes.append(f"  - {filepath.stem}")
        
        if notes:
            return [TextContent(type="text", text=f"共 {len(notes)} 条笔记：\n" + "\n".join(notes))]
        return [TextContent(type="text", text="暂无笔记。")]

    elif name == "delete_note":
        title = arguments["title"]
        safe_title = title.replace(" ", "_").replace("/", "_")
        filepath = NOTES_DIR / f"{safe_title}.md"
        
        if filepath.exists():
            filepath.unlink()
            return [TextContent(type="text", text=f"笔记已删除：{title}")]
        return [TextContent(type="text", text=f"未找到笔记：{title}")]

    return [TextContent(type="text", text=f"未知工具: {name}")]


# ========== Resources ==========

@server.list_resources()
async def list_resources() -> list[Resource]:
    resources = []
    for filepath in NOTES_DIR.glob("*.md"):
        resources.append(Resource(
            uri=f"note:///{filepath.stem}",
            name=filepath.stem,
            description=f"笔记文件: {filepath.name}",
            mimeType="text/markdown",
        ))
    return resources


@server.read_resource()
async def read_resource(uri: str) -> str:
    # note:///my_note -> my_note
    note_name = uri.replace("note:///", "")
    filepath = NOTES_DIR / f"{note_name}.md"
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return f"错误：未找到笔记 {note_name}"


# ========== Prompts ==========

@server.list_prompts()
async def list_prompts() -> list[Prompt]:
    return [
        Prompt(
            name="summarize_notes",
            description="总结所有笔记的内容",
            arguments=[],
        ),
        Prompt(
            name="write_note_from_topic",
            description="根据主题创建详细笔记",
            arguments=[
                PromptArgument(
                    name="topic",
                    description="笔记主题",
                    required=True,
                ),
                PromptArgument(
                    name="style",
                    description="写作风格：academic（学术）, casual（随意）, bullet_points（要点）",
                    required=False,
                ),
            ],
        ),
    ]


@server.get_prompt()
async def get_prompt(name: str, arguments: dict | None) -> GetPromptResult:
    if name == "summarize_notes":
        return GetPromptResult(
            description="总结所有笔记",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            "请先使用 list_notes 工具列出所有笔记，"
                            "然后逐一阅读每条笔记的内容，"
                            "最后给出一个综合总结，包括：\n"
                            "1. 笔记的主要主题\n"
                            "2. 关键要点\n"
                            "3. 可能的知识关联\n"
                        ),
                    ),
                ),
            ],
        )
    
    elif name == "write_note_from_topic":
        topic = (arguments or {}).get("topic", "未指定主题")
        style = (arguments or {}).get("style", "casual")
        
        style_instructions = {
            "academic": "使用学术写作风格，包含引用和严谨的论述。",
            "casual": "使用轻松随意的风格，通俗易懂。",
            "bullet_points": "使用要点列表格式，简洁明了。",
        }
        
        return GetPromptResult(
            description=f"撰写关于 {topic} 的笔记",
            messages=[
                PromptMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=(
                            f"请撰写一篇关于「{topic}」的详细笔记。\n\n"
                            f"写作要求：{style_instructions.get(style, style_instructions['casual'])}\n\n"
                            f"完成后，请使用 create_note 工具将笔记保存。\n"
                            f"标题建议使用主题关键词，并添加相关标签。"
                        ),
                    ),
                ),
            ],
        )

    raise ValueError(f"Unknown prompt: {name}")


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
```

### 14.3 配置文件

```json
{
    "mcpServers": {
        "notes": {
            "command": "python",
            "args": ["note_server.py"],
            "env": {}
        }
    }
}
```

### 14.4 完整的调用时序

用户说"帮我创建一条关于 MCP 协议的笔记"，完整的调用时序：

```mermaid
sequenceDiagram
    participant U as 用户
    participant A as Agent Host
    participant L as Claude API
    participant C as MCP Client
    participant S as Note MCP Server
    participant F as 文件系统
    
    U->>A: "帮我创建一条关于 MCP 协议的笔记"
    
    A->>L: messages + tools<br/>[get_current_time, mcp__notes__create_note,<br/>mcp__notes__search_notes, mcp__notes__list_notes, ...]
    
    L-->>A: tool_use: mcp__notes__create_note<br/>{title: "MCP协议概述", content: "...", tags: ["MCP", "协议"]}
    
    A->>A: 解析前缀 mcp__notes__ → server: notes, tool: create_note
    A->>A: 权限检查 → 需要确认（写操作）
    A->>U: "是否允许创建笔记 'MCP协议概述'？"
    U->>A: "允许"
    
    A->>C: call_tool("create_note", {...})
    C->>S: {"method": "tools/call", "params": {"name": "create_note", "arguments": {...}}}
    
    S->>F: 写入 notes/MCP协议概述.md
    F-->>S: 写入成功
    
    S-->>C: {"result": {"content": [{"type": "text", "text": "笔记已创建：MCP协议概述"}]}}
    C-->>A: ToolResult
    
    A->>L: tool_result: "笔记已创建：MCP协议概述"
    L-->>A: "我已经为你创建了一条关于 MCP 协议的笔记，标题是'MCP协议概述'，包含了协议的核心概念和架构说明。"
    
    A-->>U: 展示 AI 回答
```

---

## 15. 总结与展望

### 15.1 核心概念总结表

| 概念 | 定义 | 类比 | 关键点 |
|------|------|------|--------|
| **MCP** | AI Agent 与外部服务的通信协议 | HTTP 之于 Web | 开放标准，传输无关 |
| **Host** | 用户交互的 AI 应用 | 浏览器 | 管理 Client，集成 LLM |
| **Client** | Host 内的 MCP 协议实现 | HTTP Client | 与 Server 1:1 连接 |
| **Server** | 提供能力的适配器 | Web Server | 暴露 Tools/Resources/Prompts |
| **Tool** | AI 可调用的函数 | API 端点 | name + description + inputSchema |
| **Resource** | 只读数据 | 静态文件 | URI 标识，被动获取 |
| **Prompt** | 可复用交互模板 | HTML 模板 | 用户主动选择 |
| **JSON-RPC** | 底层消息格式 | HTTP 方法 | Request/Response/Notification |
| **stdio** | 本地传输方式 | 管道通信 | 简单可靠，本地运行 |
| **HTTP+SSE** | 远程传输方式 | HTTP/SSE | 支持远程，可共享 |
| **Capability** | 能力声明 | 协议版本协商 | 初始化时交换 |

### 15.2 MCP 的价值总结

```mermaid
graph TB
    subgraph "MCP 带来的核心价值"
        V1[标准化<br/>一次实现，到处可用]
        V2[生态化<br/>社区共建 Server 生态]
        V3[安全化<br/>内置认证和权限控制]
        V4[解耦化<br/>Agent 和 Service 独立演进]
        V5[智能化<br/>AI 自动发现和使用能力]
        
        V1 --> R1[降低开发成本]
        V2 --> R2[加速 AI 应用落地]
        V3 --> R3[企业级可信部署]
        V4 --> R4[灵活组合任意 Agent + Service]
        V5 --> R5[更自然的人机交互]
    end
    
    style V1 fill:#e1f5fe
    style V2 fill:#c8e6c9
    style V3 fill:#ffcdd2
    style V4 fill:#fff3e0
    style V5 fill:#e8eaf6
```

### 15.3 MCP 的未来展望

**短期（2025-2026）**：
- 协议版本稳定化（v1.0 正式版）
- Server 生态爆发式增长
- 主流 AI 工具全面支持 MCP
- 企业级部署方案成熟

**中期（2026-2027）**：
- 标准化 Server 注册表和市场
- 多 Agent 协作通过 MCP 互联
- 更丰富的能力类型（如 Sampling、Elicitation）
- 与其他 AI 标准（如 A2A Protocol）融合

**长期（2027+）**：
- MCP 成为 AI Agent 生态的基础设施
- "AI 应用商店"基于 MCP Server
- 物联网设备通过 MCP 接入 AI
- 去中心化的 MCP Server 网络

### 15.4 给开发者的建议

**如果你是 AI Agent 开发者**：
1. 尽早集成 MCP Client 支持
2. 参考 Claude Code 的实现（延迟加载、权限管理、工具路由）
3. 关注 MCP 规范的更新

**如果你是服务/平台提供者**：
1. 考虑为你的服务开发 MCP Server
2. 遵循 Tool 设计最佳实践（原子性、描述清晰、Schema 严格）
3. 发布到社区注册表，扩大影响

**如果你是 AI 应用用户**：
1. 了解你常用的 AI 工具是否支持 MCP
2. 尝试配置一些有用的 MCP Server（如 GitHub、文件系统）
3. 关注 MCP 生态的新 Server

### 15.5 学习资源

| 资源 | 链接 | 说明 |
|------|------|------|
| MCP 官方规范 | https://spec.modelcontextprotocol.io | 协议规范文档 |
| MCP 官方网站 | https://modelcontextprotocol.io | 入门教程和指南 |
| MCP GitHub | https://github.com/modelcontextprotocol | 规范、SDK、官方 Server |
| TypeScript SDK | https://github.com/modelcontextprotocol/typescript-sdk | 最成熟的 SDK |
| Python SDK | https://github.com/modelcontextprotocol/python-sdk | Python 开发者首选 |
| MCP Server 仓库 | https://github.com/modelcontextprotocol/servers | 官方 Server 合集 |
| MCP Inspector | npx @modelcontextprotocol/inspector | 调试工具 |

---

> **本文档完成于 2026 年 4 月。MCP 协议仍在快速演进中，部分细节可能随规范更新而变化。建议定期查阅官方规范获取最新信息。**
