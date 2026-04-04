# 11. 架构对比与下一步

## 本章目标

全面对比 mini-claude 与 Claude Code 的架构差异，列出未实现的功能，并给出扩展方向。

## 完整架构对比

| 组件 | Claude Code | mini-claude | 差异 |
|------|------------|-------------|------|
| **Agent Loop** | async generator + 7 种 continue reason | while(true) + tool_use 检查 | 简化循环控制 |
| **工具数量** | 66+ 工具 | 8 个工具（6 核心 + skill + agent） | 去掉特化工具 |
| **工具架构** | 抽象类 + 注册表 + 并发执行 | 数组 + switch + 串行 | 去掉抽象层 |
| **API 后端** | Anthropic only | Anthropic + OpenAI 兼容 | 多了 OpenAI |
| **流式输出** | SSE → React/Ink | SDK stream / 手动累积 | 直接输出 |
| **System Prompt** | 代码常量 + 缓存优化 | Markdown 模板 | 去掉缓存 |
| **权限系统** | 7 层 + AST 分析 + 8 级规则源 | 5 模式 + 规则配置 + 正则 + 确认 | 层次对齐 |
| **上下文管理** | 4 级压缩流水线 | 4 层（budget + snip + microcompact + 摘要） | 架构对齐 |
| **记忆系统** | 4 类型 + 语义召回 + MEMORY.md 索引 | 4 类型 + 关键词召回 + MEMORY.md | 去掉语义匹配 |
| **技能系统** | 6 源 + 懒加载 + inline/fork | 2 源 + 预加载 + inline/fork | 去掉高级加载 |
| **多 Agent** | Sub-Agent + 自定义 + Coordinator + Swarm | Sub-Agent（3 内置 + 自定义） | 去掉 Coordinator/Swarm |
| **预算控制** | USD/轮次/abort 三维预算 | USD + 轮次限制 | 去掉 abort signal |
| **编辑验证** | 14 步流水线 | 引号容错 + 唯一性 + diff 输出 | 保留核心步骤 |
| **UI 框架** | React/Ink TUI | chalk + console | 去掉 React |
| **参数解析** | commander.js | 手写循环 | 零依赖 |
| **会话管理** | JSONL + 复杂索引 | JSON 文件 | 简化格式 |
| **总代码量** | ~50 万行 | ~3000 行 | 99.4% 减少 |

## 文件映射表

mini-claude 每个文件在 Claude Code 中的对应位置：

| mini-claude | Claude Code 源码 | 说明 |
|------------|-------------------|------|
| `src/agent.ts` | `src/query.ts` + `src/QueryEngine.ts` | Agent 循环 + 会话管理 |
| `src/tools.ts` | `src/Tool.ts` + `src/tools/` (66 个目录) | 工具定义与执行 |
| `src/prompt.ts` | `src/constants/prompts.ts` + `src/utils/claudemd.ts` | Prompt 构造 |
| `src/cli.ts` | `src/entrypoints/cli.tsx` + `src/commands/` | 入口与命令 |
| `src/ui.ts` | `src/components/` (React/Ink 组件) | UI 渲染 |
| `src/session.ts` | `src/utils/sessionStorage.ts` + `src/history.ts` | 会话持久化 |
| `src/memory.ts` | `src/utils/memory.ts` + 系统 prompt 注入 | 记忆系统 |
| `src/skills.ts` | `src/utils/skills.ts` + `src/tools/SkillTool/` | 技能系统 |
| `src/subagent.ts` | `src/tools/AgentTool/` (built-in types) | 子 Agent 类型配置 |
| `src/frontmatter.ts` | (内联解析) | YAML frontmatter 解析 |
| `src/system-prompt.md` | `src/constants/prompts.ts` (内联字符串) | Prompt 模板 |

## 我们没实现的

以下是 Claude Code 有但我们刻意省略的功能：

### Hooks（钩子系统）
Claude Code 有 25 种 hook 事件和 6 种 hook 类型（command, prompt, agent, HTTP, callback, function），可在工具执行前后插入自定义逻辑。实现在各 hook 运行器中。

### Coordinator / Swarm 多 Agent 模式
我们只实现了最基础的 Sub-Agent（fork-return）。Claude Code 还支持 Coordinator（编排器）和 Swarm Team（对等通信）模式。

### MCP（Model Context Protocol）
标准化的外部工具协议，允许接入数据库、API 等。Claude Code 通过 MCP 客户端动态加载工具。

### LSP 集成
与 IDE 的 Language Server Protocol 集成，提供代码补全、诊断等信息给 agent。

### Notebook 支持
Jupyter Notebook 的读写和编辑工具 (`NotebookEditTool`)。

### OAuth / 身份认证
Web 端的 OAuth 流程，支持在云端运行。

### Vim Mode
终端内的 Vim 键绑定支持。

### 并发工具执行
`StreamingToolExecutor` 让多个安全工具并发执行，利用 API 流式响应窗口。

### Prompt Caching
Anthropic API 的 prompt caching，复用 static prompt 部分，降低成本。

### Bash AST 安全分析
使用 tree-sitter 解析 shell 命令的 AST，进行 23 项静态安全检查。我们用正则匹配替代，覆盖常见危险模式但无法处理复杂命令组合。

## 读者可以扩展的方向

### 1. 添加 Hooks 系统

在工具执行前后插入自定义逻辑，最简单的实现是 command hook：

```typescript
// .claude/settings.json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "run_shell", "command": "./hooks/pre-shell.sh" }
    ]
  }
}
```

在 `executeTool` 前 spawn shell 子进程，通过 stdin JSON 传入工具信息，解析 stdout JSON 决定 allow/deny。

### 2. 添加并发工具执行

标记 `read_file`、`list_files`、`grep_search` 为并发安全，使用 `Promise.all()` 并行执行：

```typescript
const SAFE = new Set(["read_file", "list_files", "grep_search"]);
const [safe, unsafe] = partition(toolCalls, tc => SAFE.has(tc.name));
const safeResults = await Promise.all(safe.map(tc => executeTool(tc.name, tc.input)));
const unsafeResults = [];
for (const tc of unsafe) unsafeResults.push(await executeTool(tc.name, tc.input));
```

### 3. 添加 MCP 工具支持

MCP 是一个标准协议，可以动态加载外部工具：

```typescript
import { MCPClient } from "@anthropic-ai/mcp";
const client = new MCPClient("npx @modelcontextprotocol/server-filesystem /tmp");
const mcpTools = await client.listTools();
toolDefinitions.push(...mcpTools.map(convertToToolDef));
```

### 4. 添加语义记忆召回

当前用关键词匹配召回记忆，替换为 LLM 语义匹配可大幅提升准确率：

```typescript
async function semanticRecall(query: string): Promise<MemoryEntry[]> {
  const manifest = memories.map(m => `${m.filename}: ${m.description}`).join("\n");
  const response = await sideQuery(`Which of these memories are relevant to: ${query}\n${manifest}`);
  return parseRelevantFilenames(response);
}
```

### 5. 用 Ink 替换 chalk 做 TUI

Ink 是 React 的终端渲染器，可以实现 spinner、进度条、分栏布局等高级 UI。

## 交叉引用

想深入了解 Claude Code 各模块的设计原理？参考兄弟项目的详细文档：

| 主题 | 本教程 | how-claude-code-works |
|------|--------|----------------------|
| Agent 循环 | [Ch1: Agent Loop](docs/01-agent-loop.md) | [系统主循环](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/02-agent-loop) |
| 工具系统 | [Ch2: 工具系统](docs/02-tools.md) | [工具系统](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/04-tool-system) |
| 上下文管理 | [Ch6: 上下文管理](docs/06-context.md) | [上下文工程](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/03-context-engineering) |
| 权限安全 | [Ch5: 权限与安全](docs/05-safety.md) | [权限与安全](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/10-permission-security) |
| 记忆系统 | [Ch8: 记忆与技能](docs/08-memory-skills.md) | [记忆系统](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/08-memory-system) |
| 技能系统 | [Ch8: 记忆与技能](docs/08-memory-skills.md) | [技能系统](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/09-skills-system) |
| 多 Agent | [Ch9: 多 Agent](docs/09-multi-agent.md) | [多 Agent 架构](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/07-multi-agent) |
| 权限规则 | [Ch10: 权限规则](docs/10-permission-rules.md) | [权限与安全](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/10-permission-security) |
| 代码编辑 | [Ch2: edit_file](docs/02-tools.md) | [代码编辑策略](https://windy3f3f3f3f.github.io/how-claude-code-works/#/docs/05-code-editing-strategy) |

---

## 结语

~3000 行代码，11 个文件，覆盖了一个 coding agent 的核心组件和进阶能力：

**核心组件：**
- **Agent Loop** — while 循环 + tool_use 检查
- **工具系统** — 8 个工具 + switch 分发 + 引号容错 + diff 输出
- **System Prompt** — Markdown 模板 + 环境注入 + Agent 类型描述
- **流式输出** — Anthropic + OpenAI 双后端支持
- **权限安全** — 5 种权限模式 + 规则配置 + 正则检测 + 确认
- **上下文管理** — 4 层压缩流水线（budget → snip → microcompact → auto-compact）
- **CLI / 会话** — REPL + JSON 持久化 + 预算控制

**进阶能力：**
- **记忆系统** — 4 类型 + 文件存储 + 关键词召回
- **技能系统** — 目录发现 + frontmatter 元数据 + inline/fork 双模式
- **多 Agent** — Sub-Agent fork-return + 3 内置类型 + 自定义 Agent + 上下文隔离
- **权限规则** — settings.json 配置 + allow/deny + 通配符匹配
- **预算控制** — USD 费用限制 + 轮次限制

Claude Code 的 50 万行代码中，有大量是在处理边缘情况、支持多种运行环境、提供企业级可靠性。但核心 agent 能力——理解用户意图 → 调用工具操作代码 → 迭代直到完成——就是这 ~3000 行的事。

现在你有了一个功能丰富的 coding agent，也理解了它背后每一行代码的设计意图。去扩展它吧。
