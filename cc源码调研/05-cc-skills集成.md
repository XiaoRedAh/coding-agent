# Claude Code Skill集成 深度调研报告

## 目录

1. AI Agent中Skill的概念解析
2. Claude Code Skill集成设计亮点
3. 深入调研：Skill定义与注册机制
4. 深入调研：内置Skill分类与解析
5. 深入调研：Skill调用全流程
6. 深入调研：Tool、Skill、MCP全流程对比
7. Agent系统开发的Skill设计参考
8. 总结速记表

---

## 1. AI Agent中Skill的概念解析

### 1.1 什么是Skill？

**Skill（技能）是AI Agent的"标准操作规程"（SOP）**——将验证有效的prompt模板化，让Agent不必每次从头编写相同的思考和执行流程。

用一个类比来理解：如果Tool是Agent的"双手"（具体动作能力），那Skill就是Agent的"操作手册"（如何组合使用双手完成特定任务的指南）。

一个Skill本质上是：

```
Skill = 提示词模板 + 元数据(何时用/怎么用) + 执行上下文(隔离/共享) + 行为约束(工具白名单/模型)
```

### 1.2 Skill ≠ 多个Tool的简单组合调用

这是一个非常好的问题。表面上看，Skill似乎只是"让Agent按特定顺序调用多个Tool"，那为什么不让Agent自己判断该用哪些Tool呢？

**直觉上的理解没有错，但忽略了关键差异：**

| 维度 | 没有Skill（纯靠Agent判断） | 有Skill |
|------|--------------------------|--------|
| **一致性** | 每次执行同一任务，步骤和质量可能不同 | 标准化流程，每次执行一致 |
| **上下文效率** | 每次都要在prompt中重新描述完整流程 | 流程模板化，按需加载 |
| **安全约束** | Agent可使用所有工具，无法按任务限制 | 可限制工具白名单（如review只能读不能写） |
| **知识沉淀** | 经验只存在于对话中，会话结束即消失 | 经验固化为文件，跨会话复用 |
| **模型优化** | 所有任务用同一模型，浪费资源 | 可按任务指定模型（快速检查用haiku） |
| **可分享性** | 个人经验无法团队共享 | Skill文件可提交到Git，团队统一标准 |
| **调试能力** | 出错时难以定位是哪个步骤的问题 | 结构化步骤，可逐步调试 |

**核心洞察：** Skill不是"多个Tool的组合调用"，而是**"指导Agent如何思考和行动的专家知识模板"**。它解决的不是"能不能做"的问题（Agent确实可以自己判断用哪些Tool），而是"做得好不好"、"做得一致不一致"、"做得安全不安全"的问题。

### 1.3 为什么需要Skill？——五个核心动机

**动机1：消除重复的Prompt工程**

每次让Agent做代码审查，你可能需要输入："检查安全漏洞、检查错误处理、检查命名规范、输出结构化报告……"。Skill将这段prompt固化，输入`/review`即可。

**动机2：行为约束与安全隔离**

```yaml
# 一个只读的审查技能——即使Agent想写文件也不行
allowed-tools: [Bash(git diff:*), Read, Grep, Glob]
context: fork  # 隔离执行，不污染主对话
```

**动机3：团队知识标准化**

项目级Skill（`.claude/skills/`）提交到Git，整个团队共享同一套操作规程。新人加入项目，`/deploy`的行为和老手完全一致。

**动机4：Token预算优化**

Skill的完整prompt只在调用时加载——启动时只加载轻量的frontmatter（名称+描述）。一个注册了50个Skill的系统，启动时只消耗约1%的上下文窗口。

**动机5：双重调用模型**

Skill同时支持用户手动调用（`/verify`）和模型自动触发（用户说"帮我检查代码"，模型根据`whenToUse`自动调用verify技能）。这让技能成为Agent行为的有机组成部分。

### 1.4 Skill与Tool System、MCP的关系

| 维度 | Tool System（内置工具） | MCP（外部工具协议） | Skill（技能模板） |
|------|---------------------|-----------------|---------------|
| **本质** | 进程内函数调用 | 跨进程/跨网络的标准化协议 | Prompt模板 + 行为约束 |
| **抽象层级** | 原子操作（读文件、执行命令） | 原子操作（远程工具调用） | 组合流程（如何使用多个工具完成任务） |
| **定义方式** | TypeScript代码（`Tool<I,O,P>`接口） | JSON-RPC协议 | Markdown + YAML frontmatter |
| **通信开销** | 零（进程内） | 有（序列化/反序列化） | 零（Prompt层面） |
| **谁来编写** | 开发团队 | MCP服务器提供者 | 任何用户/团队 |
| **安全边界** | 共享进程权限 | 进程隔离/网络隔离 | 复用已有工具的安全机制 + 工具白名单 |
| **扩展方式** | 修改代码 | 实现MCP协议 | 创建Markdown文件 |

**关键洞察：** 在Claude Code中，Skill最终通过**SkillTool**（一个内置Tool）执行。也就是说，Skill是Tool System的一个"客户"——它通过SkillTool这个统一入口，将Prompt模板转化为对话消息注入Agent。三者形成了分层架构：

```
┌─────────────────────────────────────────────┐
│ Skill层（知识复用 + 行为约束）               │
│ Markdown + Frontmatter → SkillTool执行      │
├─────────────────────────────────────────────┤
│ Tool层（能力基座）                           │
│ 内置Tool + MCP Tool → 统一Tool<I,O,P>接口    │
├─────────────────────────────────────────────┤
│ LLM层（决策引擎）                           │
│ 模型判断用哪个Tool/Skill                     │
└─────────────────────────────────────────────┘
```

---

## 2. Claude Code Skill集成设计亮点

### 亮点1：Markdown-as-Config——零门槛的技能格式

用Markdown + YAML frontmatter定义Skill，正文就是prompt内容。不需要学任何编程语言，创建一个`SKILL.md`文件就是一个完整的技能。这个格式人类可读、版本控制友好、Git diff清晰。

### 亮点2：双重调用模型——用户手动 + 模型自动

Skill同时支持用户通过`/name`手动触发和模型根据`whenToUse`字段自动触发。用户不需要记住命令名，只需要表达意图，模型自行判断是否调用适合的Skill。

### 亮点3：Inline/Fork双模式执行

- **Inline模式**：Skill内容注入当前对话，共享上下文，适合快速操作
- **Fork模式**：创建隔离子Agent，独立token预算、独立工具池、独立对话历史，适合复杂任务

### 亮点4：六层来源的分层加载与优先级覆盖

managed（企业策略）> project（项目级）> user（用户级）> plugin > bundled > MCP，高优先级覆盖低优先级。企业可以强制统一标准，项目可以自定义流程，用户可以个人偏好。

### 亮点5：条件技能——按文件路径自动激活

通过`paths` frontmatter，技能只在操作匹配文件时才激活。Monorepo中前端子项目的组件生成技能不会在后端代码中出现。

### 亮点6：压缩后技能保留

当对话过长触发autocompact时，已调用的Skill内容通过`addInvokedSkill()`记录，压缩后通过`createSkillAttachmentIfNeeded()`重建并重新注入，确保长会话中技能行为一致。

### 亮点7：Token预算分配的三阶段算法

技能列表在system prompt中按预算分配：全量描述→分区截断（bundled保护）→极端降级（仅显示名称）。内置核心技能始终保留完整描述。

### 亮点8：MCP技能的信任边界隔离

MCP来源的技能禁用Shell命令内联执行、不替换`${CLAUDE_SKILL_DIR}`。安全策略根据来源信任等级递减：bundled > managed > skills > plugin > MCP。

### 亮点9：安全属性白名单的前向兼容设计

`SAFE_SKILL_PROPERTIES`白名单决定哪些技能可以自动允许执行。新增属性默认需要权限审批——"默认拒绝"比"默认允许"更安全。

---

## 3. 深入调研：Skill定义与注册机制

### 3.1 Skill是如何定义的？

Claude Code中的Skill在代码中表示为`PromptCommand`类型（定义在`src/types/command.ts`）：

```typescript
type PromptCommand = {
  type: 'prompt'
  name: string                    // 技能名称
  description: string             // 显示描述
  whenToUse?: string              // 模型据此判断何时自动触发
  allowedTools?: string[]         // 允许的工具白名单
  model?: string                  // 模型覆盖
  effort?: EffortValue            // 工作量级别
  context?: 'inline' | 'fork'    // 执行模式
  agent?: string                  // fork时的Agent类型
  source: 'bundled' | 'plugin' | 'skills' | 'mcp'  // 来源
  hooks?: HooksSettings           // 技能级Hook
  skillRoot?: string              // 技能资源基础目录
  paths?: string[]                // 可见性路径模式
  getPromptForCommand(args, context): Promise<ContentBlockParam[]>  // 内容加载器
}
```

### 3.2 为什么这么定义？——各字段的作用

| 字段 | 类型 | 必填 | 作用 | 设计意图 |
|------|------|------|------|---------|
| `name` | string | 否 | 显示名称，省略时使用目录名 | kebab-case命名，用户通过`/name`调用 |
| `description` | string | 是 | 技能描述 | 展示在帮助列表中，也用于模型判断 |
| `whenToUse` | string | 否 | 模型自动触发条件描述 | **关键字段**——让模型理解何时该主动调用此技能 |
| `arguments` | string | 否 | 命名参数列表 | 映射到`$foo`占位符，增强可读性 |
| `allowed-tools` | list | 否 | 允许的工具白名单 | 最小权限原则——review技能不需要写文件 |
| `model` | string | 否 | 模型覆盖 | 快速检查用haiku，深度分析用opus |
| `effort` | string/int | 否 | 工作量级别 | 控制模型思考深度，quick/standard/分钟数 |
| `context` | string | 否 | 执行上下文（inline/fork） | fork实现权限隔离、上下文隔离、模型隔离 |
| `paths` | list | 否 | 条件激活路径模式 | 按文件类型自动激活，减少选择负担 |
| `hooks` | object | 否 | 生命周期钩子 | pre/post命令用于自动化检查 |
| `user-invocable` | boolean | 否 | 是否用户可手动调用 | false则隐藏，仅限模型内部使用 |
| `disable-model-invocation` | boolean | 否 | 是否禁止模型自动触发 | true则只允许用户手动`/skill`调用 |
| `getPromptForCommand` | function | 是 | 内容加载器（延迟执行） | **懒加载核心**——仅在技能被调用时才运行 |

### 3.3 Skill的目录结构

每个Skill是一个目录，包含一个`SKILL.md`文件：

```
~/.claude/skills/
  my-code-review/
    SKILL.md              ← 技能定义文件（必须）
    review-checklist.md   ← 附属文件，模型可按需读取
    examples/
      good-pattern.md     ← 良好模式示例
      bad-pattern.md      ← 反模式示例
```

**为什么是目录格式而非单文件？** 目录格式允许技能附带资源文件（如模板、配置文件、示例代码），并通过`${CLAUDE_SKILL_DIR}`引用。这让技能可以携带"参考资料"。

`SKILL.md`的完整格式：

```markdown
---
name: gen-api
description: 生成REST API端点的完整代码骨架
when_to_use: 当用户需要创建新的API端点或CRUD操作时
arguments: method resource
argument-hint: "[GET|POST|PUT|DELETE] [resource-name]"
allowed-tools:
  - Read
  - Write
  - Grep
  - Glob
model: inherit
effort: high
context: fork
user-invocable: true
paths:
  - "src/api/**/*.ts"
hooks:
  pre:
    - command: npm run type-check
  post:
    - command: npm run test -- --related
---

# API端点生成器

为资源 $resource 创建 $method 方法的REST API实现。

## 上下文收集
1. 使用 Grep 查找现有的路由定义模式
2. 使用 Read 查看一个已有的路由文件作为参考
...

使用 ${CLAUDE_SKILL_DIR}/templates/ 中的模板文件。
```

### 3.4 Skill是如何注册的？

#### Tool、Skill、MCP的定义并未抽象在一起——它们各自有独立的定义体系

| 维度 | Tool | Skill | MCP工具 |
|------|------|-------|---------|
| **定义格式** | TypeScript（`Tool<I,O,P>`泛型接口） | Markdown + YAML frontmatter | JSON-RPC协议返回的JSON Schema |
| **定义位置** | `src/tools/XxxTool/` | `.claude/skills/` 或编译内置 | MCP服务器 |
| **代码内类型** | `Tool<Input, Output, P>` | `PromptCommand` | 映射为`Tool`接口（`isMcp: true`） |
| **如何区分** | `name`不带前缀 | `type: 'prompt'`，通过SkillTool执行 | `isMcp: true`，`mcp__`前缀 |

**关键区别：**
- **Tool**通过`buildTool()`工厂函数创建，编译时注册
- **Skill**通过`registerBundledSkill()`（内置）或`loadSkillsFromSkillsDir()`（文件系统）注册，统一表示为`PromptCommand`类型
- **MCP工具**通过`tools/list` JSON-RPC发现，映射为`Tool`接口

#### Skill的六层来源加载

```
Skill来源加载（按���先级从高到低）

Phase 1: 启动时并行加载5个来源
 ├── [1] managedSkillsDir     ← 企业管理策略（最高优先级）
 ├── [2] projectSkillsDirs    ← 项目级 .claude/skills/
 ├── [3] userSkillsDir        ← 用户级 ~/.claude/skills/
 ├── [4] pluginSkills         ← 插件提供的技能
 └── [5] bundledSkills        ← 内置编译的技能（通过initBundledSkills()）

Phase 2: 运行时动态发现
 └── [6] MCP技能              ← MCP服务器通过mcpSkillBuilders暴露

合并 + 按realpath去重 → 分离条件技能(paths) 和无条件技能
```

去重策略使用`realpath()`解析符号链接得到规范路径——防止同一技能通过不同路径被加载两次。

```typescript
// skills/loadSkillsDir.ts:424-445
const results = await Promise.all(
  entries.map(async (entry): Promise<SkillWithPath | null> => {
    // 只支持目录格式：skill-name/SKILL.md
    if (!entry.isDirectory() && !entry.isSymbolicLink()) {
      return null
    }
    const skillDirPath = join(basePath, entry.name)
    const skillFilePath = join(skillDirPath, 'SKILL.md')
    let content: string
    try {
      content = await fs.readFile(skillFilePath, { encoding: 'utf-8' })
    } catch (e: unknown) {
      if (!isENOENT(e)) {
        logForDebugging(`[skills] failed to read ${skillFilePath}: ${e}`)
      }
      return null
    }
    // ...parse frontmatter and create command
  }),
)
```

### 3.5 如何让Agent知道有哪些Skill可以调用？

**并非把所有Skill的完整prompt都放入system prompt。** Claude Code使用两层机制：

**第一层：技能列表展示（启动时）**

只加载frontmatter（name、description、whenToUse），在system prompt中展示可用技能列表。通过`formatCommandsWithinBudget()`三阶段预算分配算法控制：

```
总预算 = 1% × 上下文窗口 × 4 chars/token（~8KB for 200K context）

Phase 1: 所有技能完整描述 ≤ 预算？→ 直接使用
Phase 2: bundled技能保留完整描述 + 非bundled技能均分剩余预算
Phase 3: 每技能 < 20 chars？→ 非bundled技能仅显示名称
```

**第二层：技能内容加载（调用时）**

完整的Markdown内容只在用户实际调用或模型触发时才通过`getPromptForCommand()`读取。

```typescript
export function estimateSkillFrontmatterTokens(skill: Command): number {
  const frontmatterText = [skill.name, skill.description, skill.whenToUse]
    .filter(Boolean)
    .join(' ')
  return roughTokenCountEstimation(frontmatterText)
}
```

**模型如何自动触发Skill？**

SkillTool是一个内置Tool，它被注册到工具池中。当模型看到用户的意图与某个Skill的`whenToUse`描述匹配时，模型会输出一个`tool_use` block调用SkillTool：

```json
{
  "type": "tool_use",
  "name": "SkillTool",
  "input": {
    "skill": "verify",
    "args": ""
  }
}
```

---

## 4. 深入调研：内置Skill分类与解析

### 4.1 内置Skill清单

内置技能通过`initBundledSkills()`统一注册，分为核心技能（始终注册）和Feature-gated技能：

#### 代码质量层

| 技能 | 用途 | 执行模式 | 工作流程 | 亮点 |
|------|------|---------|---------|------|
| **verify** | 验证代码变更的正确性 | fork | 运行测试套件→检查编译→验证逻辑正确性 | 独立Agent执行，不污染主对话；限制工具为只读 |
| **simplify** | 代码简化与重构审查 | inline | 分析当前代码→识别复杂度→建议简化方案 | 共享对话上下文，可引用刚写的代码 |
| **debug** | 调试辅助，提供诊断思路 | inline | 分析错误信息→定位根因→提供修复方案 | 直接在主对话中提供建议，便于交互 |

#### 工作流层

| 技能 | 用途 | 执行模式 | 工作流程 | 亮点 |
|------|------|---------|---------|------|
| **batch** | 批量文件处理 | fork | 收集目标文件→并行处理→汇总结果 | fork隔离，大量工具调用不污染上下文 |
| **stuck** | 帮助模型走出困境 | inline | 分析当前状态→识别阻塞原因→建议替代方案 | 模型陷入循环时的"解围"指令 |
| **skillify** | 将prompt转换为可复用的技能 | inline | 分析用户prompt→提取模式→生成SKILL.md | 元技能——用技能创建技能 |
| **lorem-ipsum** | 生成占位内容 | inline | 按需求生成填充文本 | UI开发时的便捷工具 |

#### 配置层

| 技能 | 用途 | 执行模式 | 工作流程 | 亮点 |
|------|------|---------|---------|------|
| **update-config** | 配置settings.json | inline | 解析用户意图→修改配置项→验证配置有效性 | 不需要用户手动编辑JSON |
| **remember** | 记忆管理（CLAUDE.md条目） | inline | 接收信息→写入CLAUDE.md→后续会话可访问 | 运行时门控：`isEnabled: () => isAutoMemoryEnabled()` |
| **keybindings-help** | 键盘快捷键自定义帮助 | inline | 展示当前快捷键→指导自定义 | 纯信息展示型技能 |

#### Feature-gated层

| 技能 | Feature Flag | 用途 | 门控机制 |
|------|-------------|------|---------|
| **loop** | AGENT_TRIGGERS | 类Cron的Agent触发 | 每次调用时检查功能是否启用 |
| **claude-api** | BUILDING_CLAUDE_APPS | Claude API辅助 | 编译时条件注册 |
| **schedule** | AGENT_TRIGGERS_REMOTE | 远程调度 | 编译时条件注册 |

### 4.2 内置技能的注册机制

```typescript
// src/skills/bundledSkills.ts
registerBundledSkill({
  name: 'remember',
  description: 'Review auto-memory entries...',
  whenToUse: 'Use when the user wants to save information for future sessions',
  userInvocable: true,
  isEnabled: () => isAutoMemoryEnabled(),  // 运行时门控
  async getPromptForCommand(args) {
    return [{ type: 'text', text: SKILL_PROMPT }]  // 内容编译在二进制中
  }
})
```

**与文件系统技能的关键区别：**
- 内置技能的prompt内容编译在二进制中，不需要运行时文件读取
- 部分内置技能需要提取资源文件到磁盘（通过`safeWriteFile()`，使用`O_NOFOLLOW | O_EXCL`防止符号链接攻击）
- 提取使用惰性单例模式（`??=`操作符），多个并发调用共享同一个提取Promise

### 4.3 前置/后置校验

- **权限校验**：技能执行前通过`SAFE_SKILL_PROPERTIES`白名单检查——只包含安全属性的技能自动允许，否则需要用户确认
- **Hook校验**：技能可在frontmatter中定义`hooks`，通过Zod schema校验；无效的hooks仅记录警告但不阻止技能加载（容错设计）
- **MCP安全校验**：来自MCP的技能禁用Shell命令内联、不替换本地路径变量

---

## 5. 深入调研：Skill调用全流程

### 5.1 模型如何判断要用Tool还是MCP还是Skill？

**模型本身不区分Tool、MCP工具和Skill——它们对模型来说都是tool。**

关键区别在于：
- **内置Tool和MCP工具**：作为独立的tool定义出现在API的`tools`数组中，模型直接输出`tool_use` block调用
- **Skill**：通过**SkillTool**这个桥接工具间接调用。模型调用的是SkillTool，传入`{skill: "verify", args: ""}`

SkillTool的prompt（注入system prompt）包含了可用技能列表及其`whenToUse`描述，模型根据用户意图匹配最合适的技能。

### 5.2 Skill调用的两条路径

```
路径A：用户手动调用
  用户输入 /verify → CLI解析斜杠命令 → 直接调用processPromptSlashCommand()

路径B：模型自动调用
  用户说"帮我检查代码" → 模型输出tool_use(SkillTool, {skill: "verify"})
  → 8阶段工具执行流��线 → SkillTool.call() → 内部调用processPromptSlashCommand()

两条路径最终汇合到同一个提示词加载和执行逻辑
```

### 5.3 SkillTool的完整执行流程

```
[接收 {skill, args}]
     │
[Stage 1] 标准化技能名（trim + 去除前导 /）
     │
[Stage 2] 查找命令：findCommand(name, allCommands)
     │
     ├── 未找到 → 返回错误
     │
[Stage 3] 检查执行模式
     │
     ├── context == 'fork' → executeForkedSkill()
     │     │
     │     ├── 解析Agent定义
     │     ├── 构建隔离工具池（按allowedTools过滤）
     │     ├── 调用runAgent()创建子Agent
     │     ├── 子Agent独立执行多轮工具调用
     │     └── 返回结果文本："Skill 'verify' completed.\n\nResult:\n..."
     │
     └── inline模式 → processPromptSlashCommand()
           │
           ├── getPromptForCommand(args)
           │     ├── Step 1: 基础目录前缀
           │     ├── Step 2: 参数替换（$ARGUMENTS / $file / ${file}）
           │     ├── Step 3: 环境变量替换（${CLAUDE_SKILL_DIR}）
           │     ├── Step 4: Shell命令内联执行（MCP技能跳过）
           │     └── 返回最终prompt内容
           │
           ├── 提取元数据（allowedTools, model, effort）
           ├── 记录遥测（tengu_skill_tool_invocation）
           ├── 标记消息（tagMessagesWithToolUseID）
           ├── 记录调用（addInvokedSkill → 用于压缩后恢复）
           └── 返回结果 + contextModifier
                 ├── allowedTools → 追加到alwaysAllowRules
                 ├── model → 覆盖mainLoopModel
                 └── effort → 覆盖effortValue
```

### 5.4 示例：模拟全流程

**用户请求：** "帮我检查一下当前分支的代码质量"

**Step 1 - 模型判断：** 模型在system prompt中看到可用技能列表，其中`verify`的描述是"验证代码变更的正确性"，`whenToUse`是"当用户要求审查代码、检查改动时"。模型判断意图匹配，输出：

```json
{
  "type": "tool_use",
  "name": "SkillTool",
  "input": { "skill": "verify", "args": "" }
}
```

**Step 2 - 工具查找：** 系统按name在工具池中匹配到SkillTool（内置Tool），进入8阶段执行流水线。

**Step 3 - 输入验证：** Zod Schema验证`{skill: string, args: string}`结构。

**Step 4 - 权限检查：** 检查verify技能是否只有安全属性（`SAFE_SKILL_PROPERTIES`白名单）→ 自动允许。

**Step 5 - SkillTool.call()执行：**

```typescript
// SkillTool.ts
// 1. 标准化技能名
const normalizedName = "verify"  // trim + 去除前导 /

// 2. 查找命令
const command = findCommand("verify", allCommands)  // → 找到bundled的verify技能

// 3. 检查执行模式：verify的context是'fork'
// → executeForkedSkill()
```

**Step 6 - Fork执行：**

```typescript
// SkillTool.ts:222-237
for await (const message of runAgent({
  agentDefinition,        // verify的Agent定义
  promptMessages,         // 包含verify的prompt内容
  toolUseContext: { ... },
  canUseTool,
  isAsync: false,
  querySource: 'agent:custom',
  model: command.model,
  availableTools: filteredTools,  // 只有Bash, Read, Grep, Glob
  override: { agentId },
})) {
  agentMessages.push(message)
}
```

子Agent在隔离环境中执行：
1. 运行`git diff main...HEAD --stat`
2. 逐文件读取diff内容
3. 分析代码质量
4. 输出结构化报告

**Step 7 - 结果返回：** 子Agent完成后，结果汇总为文本：

```
Skill 'verify' completed.

Result:
## 代码审查报告
### 文件: src/auth/login.ts
- [高] 未处理的异常：第42行缺少try-catch
- [中] 硬编码超时值：建议使用配置常量
...
```

**Step 8 - 消息发射：** `tool_result` block返回给模型，模型向用户展示审查报告。

### 5.5 参数替换机制详解

```
输入：/gen-api GET users

Step 1: 命名参数替换
  arguments: "method resource"
  $method → "GET"
  $resource → "users"

Step 2: 索引参数替换
  $1 → "GET"（$0是技能名本身）
  $2 → "users"
  $ARGUMENTS[0] → "GET"
  $ARGUMENTS[1] → "users"

Step 3: 完整参数替换
  $ARGUMENTS → "GET users"

Step 4: 环境变量替换
  ${CLAUDE_SKILL_DIR} → /home/user/.claude/skills/gen-api/
  ${CLAUDE_SESSION_ID} → abc123

Step 5: Shell命令内联（仅非MCP技能）
  !`git branch --show-current` → "feature/api-refactor"

Step 6: 无占位符追加
  如果prompt中没有使用任何$占位符 → 将参数文本追加到prompt末尾
```

---

## 6. 深入调研：Tool、Skill、MCP全流程对比

### 6.1 核心异同对比表

| 维度 | 内置Tool | Skill | MCP工具 |
|------|---------|-------|---------|
| **代码内类型** | `Tool<Input,Output,P>` | `PromptCommand` | 映射为`Tool`（`isMcp:true`） |
| **定义格式** | TypeScript代码 | Markdown + YAML | JSON Schema（MCP协议） |
| **注册方式** | `buildTool()`编译时 | `registerBundledSkill()`/文件扫描 | `tools/list`动态发现 |
| **调用方式** | 模型直接`tool_use` | 通过SkillTool间接 / 用户`/command` | 模型直接`tool_use` |
| **执行方式** | 进程内`call()` | 注入prompt（inline）/ 子Agent（fork） | JSON-RPC代理 |
| **输入验证** | Zod safeParse + validateInput | 参数替换（弱验证） | JSON Schema验证 |
| **权限默认** | 部分自动允许（只读工具） | 安全属性白名单自动允许 | passthrough（每次确认） |
| **结果形式** | `ToolResult<Output>` | 对话消息/子Agent文本 | MCP content array |
| **安全边界** | 共享进程权限 | 可限制工具白名单（fork模式） | 进程隔离/网络隔离 |
| **命名** | 单一名称（如`FileReadTool`） | 目录名或name字段 | `mcp__server__tool` |
| **延迟加载** | `shouldDefer`标记 | 始终懒加载（只预加载frontmatter） | MCP工具默认延迟 |
| **可扩展性** | 需要修改代码 | 创建Markdown文件即可 | 实现MCP协议 |
| **错误处理** | 进程内异常→tool_result | prompt注入无显式错误机制 | 网络错误/认证过期 |
| **适用场景** | 原子操作（读文件、执行命令） | 组合流程（审查、验证、生成） | 连接外部服务 |

### 6.2 执行流水线对比

```
           内置Tool              Skill                   MCP工具
           ─────────            ──────                  ──────
Stage 1    工具查找(name)        SkillTool查找           工具查找(mcp__前缀名)
Stage 2    Zod Schema验证       参数替换(弱验证)          JSON Schema验证
Stage 3    Pre-Tool Hook        Pre-Tool Hook           Pre-Tool Hook
Stage 4    权限检查(7源规则)     安全属性白名单检查        权限检查(默认passthrough)
Stage 5    tool.call()          Inline: 注入prompt      ensureConnectedClient()
           (进程内)              Fork: 子Agent执行        → JSON-RPC tools/call
Stage 6    mapToolResult        contextModifier应用      mapToolResult + blob处理
Stage 7    Post-Tool Hook       Post-Tool Hook          Post-Tool Hook
Stage 8    消息发射              消息发射                  消息发射
```

### 6.3 关键差异的设计原因

**为什么Skill通过SkillTool间接调用而非直接注册为独立Tool？**

Skill的本质是prompt模板，不是函数调用。它没有严格的输入Schema（只有文本参数），执行方式也与Tool完全不同（注入对话 vs 函数调用）。通过SkillTool桥接，保持了Tool接口的纯粹性，同时让Skill融入统一的执行流水线。

**为什么Skill使用Markdown而非TypeScript定义？**

降低创建门槛是首要目标。任何用户都能写Markdown，但不是所有用户都会TypeScript。Markdown + frontmatter的格式同时满足了"人类可读"和"机器可解析"的需求。

**为什么Skill有两种执行模式？**

- **Inline**适合快速的行为修改（如`simplify`——审查刚写的代码，需要看到对话上下文）
- **Fork**适合复杂的独立任务（如`verify`——运行完整测试套件，大量工具调用会污染主对话上下文；同时可以限制工具集实现安全隔离）

---

## 7. Agent系统开发的Skill设计参考

### 参考1：Markdown-as-Config格式

用Markdown + YAML frontmatter作为技能/模板的定义格式。优势：人类可读、版本控制友好、渐进式复杂度（最简单的技能只需要正文）。

```markdown
---
description: 这是配置
allowed-tools: [Read, Write]
---
# 这是内容（prompt模板）
```

**适用场景：** 任何需要"配置 + 大段文本内容"混合体的系统。

### 参考2：双重调用模型（用户手动 + 模型自动）

通过`whenToUse`字段让模型理解何时该主动调用技能，扩大了技能的适用范围。

```typescript
// 模型自动调用时的判断依据
whenToUse: "当用户需要审查代码质量时"
```

**适用场景：** 任何Agent系统中的可复用操作——不应该只能通过显式命令触发。

### 参考3：Inline/Fork双模式执行

根据任务性质选择共享上下文或隔离执行，通过简单的配置字段切换。

```yaml
context: fork  # 复杂任务，隔离执行
context: inline  # 快速操作，共享上下文（默认）
```

**适用场景：** 任何需要平衡上下文共享与隔离的Agent系统。

### 参考4：懒加载 + Token预算分配

只预加载轻量元数据（名称、描述），完整内容按需加载。在展示可用技能列表时，通过三阶段预算分配控制token开销。

```
预算 = 1% × 上下文窗口
Phase 1: 全量 → Phase 2: 分区截断 → Phase 3: 仅名称
```

**适用场景：** 上下文窗口有限的任何Agent系统，特别是技能数量可能很多的场景。

### 参考5：分层来源 + 优先级覆盖

多层来源并行加载，高优先级覆盖低优先级，企业策略最高。

```
企业策略 > 项目级 > 用户级 > 插件 > 内置
```

**适用场景：** 任何需要多层配置合并的系统（VS Code的settings层级、npm的config链）。

### 参考6：条件激活（按路径模式）

通过`paths`字段实现"按文件类型自动激活"，减少用户的选择负担。

```yaml
paths:
  - "src/components/**"  # 只在前端组件目录激活
```

**适用场景：** Monorepo或多模块项目中，不同子系统需要不同的技能集。

### 参考7：压缩后技能恢复

在长对话中，技能内容可能被上下文压缩覆盖。通过记录已调用技能的完整信息，在压缩后重建并重新注入。

```typescript
// 每次技能调用时记录
addInvokedSkill(name, path, content, agentId)

// 压缩后恢复（25K总预算，5K单技能上限，最近调用优先）
createSkillAttachmentIfNeeded()
```

**适用场景：** 任何支持上下文压缩的Agent系统。

### 参考8：安全属性白名单（前向兼容安全）

用白名单而非黑名单决定哪些技能可以自动执行。新增属性默认需要权限审批。

```typescript
const SAFE_SKILL_PROPERTIES = new Set([
  'name', 'description', 'whenToUse', ...
  // 新增的未知属性 → 默认不在白名单中 → 需要用户确认
])
```

**适用场景：** 任何涉及安全敏感操作的插件/中间件系统。

### 参考9：信任边界按来源分级

安全策略根据来源信任等级递减：bundled（最信任）> managed > user > plugin > MCP（最不信任）。

```typescript
// MCP技能禁用Shell命令内联
if (loadedFrom !== 'mcp') {
  finalContent = await executeShellCommandsInPrompt(finalContent, ...)
}
```

**适用场景：** 任何支持多来源扩展的Agent系统。

### 参考10：Write-Once Registry打破循环依赖

通过无依赖的叶子模块作为注册中心，生产者初始化时写入，消费者运行时读取，打破模块循环依赖。

```typescript
// 叶子节点（无自身依赖）
let builders = null
export function register(b) { builders = b }
export function get() { return builders }
```

**适用场景：** 打包二进制中动态import无法解析的场景。

---

## 8. 总结速记表

| 维度 | 要点 | 关键设计 |
|------|------|---------|
| **Skill本质** | 提示词模板 + 元数据 + 执行上下文 | "AI Shell脚本"——自动化AI任务 |
| **定义格式** | Markdown + YAML frontmatter | 零门槛，人类可读，版本控制友好 |
| **代码内类型** | `PromptCommand` | 通过`SkillTool`桥接到Tool System |
| **调用方式** | 双重：用户`/name` + 模型自动 | `whenToUse`字段让模型理解何时触发 |
| **执行模式** | Inline（共享上下文）/ Fork（隔离） | `context: fork`实现权限+上下文+模型隔离 |
| **来源层级** | 6层：managed > project > user > plugin > bundled > MCP | 高优先级覆盖低优先级 |
| **懒加载** | 只预加载frontmatter，内容按需 | 三阶段Token预算分配算法 |
| **条件激活** | `paths`字段匹配文件路径 | Monorepo友好，减少选择负担 |
| **参数系统** | $ARGUMENTS / $N / 命名参数 | 四步顺序替换 + Shell内联 + 环境变量 |
| **安全模型** | SAFE_SKILL_PROPERTIES白名单 | 前向兼容安全，新属性默认需审批 |
| **MCP安全** | 禁用Shell内联 + 不替换本地路径 | 远程不信任，安全策略按来源递减 |
| **压缩恢复** | addInvokedSkill → 压缩后重建 | 25K总预算/5K单技能，最近优先 |
| **去重策略** | realpath解析符号链接 | 防止同一技能通过不同路径加载两次 |
| **循环依赖** | Write-Once Registry模式 | 叶子模块作为注册中心打破循环 |
| **Hook** | 技能级Hook叠加全局Hook | 调用时注册，不覆盖全局 |
| **与Tool关系** | Skill是Tool System的"客户" | 通过SkillTool桥接，共享执行流水线 |
| **与MCP关系** | MCP可提供技能（通过mcpSkillBuilders） | 统一加载和执行路径，但安全限制最严 |
| **Plugin** | 比Skill更高层级的扩展单元 | 可同时包含Skills+Agents+Hooks+MCP |
| **目录结构** | `skill-name/SKILL.md` + 附属文件 | 目录格式允许携带资源文件 |
| **内置技能** | 10+核心 + Feature-gated | 编译在二进制中，资源文件安全提取 |

**一句话总结：** Claude Code的Skill系统通过**Markdown-as-Config格式 + 双重调用模型 + Inline/Fork双模式执行 + 六层分层加载 + 条件激活 + 懒加载预算分配 + 压缩后恢复 + 信任边界分级**的组合设计，实现了一个零门槛创建、安全可控、跨会话复用的AI任务自动化框架。对于自研Agent系统，最值得借鉴的是：双重调用模型（手动+自动）、Inline/Fork双模式执行、安全属性白名单的前向兼容设计、以及分层来源的优先级覆盖模式。