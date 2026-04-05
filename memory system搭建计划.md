# Memory System 搭建计划

---

## 一、当前项目的 Memory 现状

### 1.1 是否已实现？

**没有。** 当前项目没有任何跨会话的记忆持久化机制。每次启动 `main.py`，Agent 从零开始——不记得用户的偏好、上次的决策、项目的约定。

现有的相似机制：
- **CLAUDE.md**：项目指令文件，但这是版本控制的静态配置，不是动态学习的记忆
- **Skills**：可复用的任务指南，但是预定义的知识，不是对话中学到的
- **上下文压缩的摘要**：保存到 `.xiaoagent/transcripts/`，但只是转录存档，不用于后续会话

### 1.2 缺少 Memory 的影响

| 场景 | 没有 Memory | 有 Memory |
|------|-----------|----------|
| 用户说"用中文回复" | 每次都要重复说 | 记住一次，永久生效 |
| 项目用 pytest 不用 unittest | Agent 可能用错 | 记住项目约定 |
| 用户反馈"不要加注释" | 下次又加 | 记住反馈，不再犯 |
| 上次讨论过数据库 schema 变更 | 完全不知道 | 能回忆关键决策 |

---

## 二、关于 Memory 的理解分析

### 2.1 你的理解对吗？

> "Memory 系统只是锦上添花的组件，不一定非得实现？没有 Memory，Agent 照样可以正常运作？"

**基本正确。** Memory 不是 Agent 的核心功能——没有它，Agent 仍然能读文件、写代码、执行命令。Claude Code 在没有 Memory 的早期版本中也工作得很好。

但 Memory 显著提升**长期使用体验**：
- 第 1 次使用：有无 Memory 差别不大
- 第 10 次使用：有 Memory 的 Agent 更懂你
- 第 100 次使用：差距非常明显

> "有了 Memory 后，Agent 会变得越来越懂你？"

**是的，这是 Memory 的核心价值。** Memory 让 Agent 具备"学习能力"——不是模型层面的学习，而是上下文层面的学习。

> "Memory 也会进一步加剧上下文窗口的压力？"

**是的，但 CC 通过精巧设计大幅缓解了这个问题：**

1. **MEMORY.md 索引**：只有索引文件（200 行/25KB 上限）始终在 prompt 中
2. **相关性选择**：每次对话最多加载 5 个最相关的记忆文件（用 Sonnet 选择）
3. **"不存什么"规则**：严格避免存储可从代码/git/CLAUDE.md 推导的信息
4. **渐进式加载**：不是一次性加载所有记忆

**Token 成本估算**（CC 的做法）：
- MEMORY.md 索引：~500-2000 token（始终在 prompt）
- 相关记忆加载：~1000-5000 token（每次最多 5 个文件）
- 总计：200K 窗口中的 ~1-3%，非常合理

### 2.2 是否有必要实现？

**建议实现一个基础版本。** 原因：
1. 这是 Claude Code 的核心特性之一，不实现会缺少重要的对齐维度
2. 基础版本实现成本很低（~200 行代码）
3. 对理解 CC 架构有学习价值
4. 为后续迭代（自动提取、相关性选择等）打好基础

---

## 三、搭建计划

### 3.1 设计原则

1. **最简可用**：只实现核心的"存/取/索引"，暂不做自动提取和相关性选择
2. **对齐 CC**：文件格式（frontmatter + markdown）、四种类型、MEMORY.md 索引
3. **Token 友好**：MEMORY.md 有上限，单文件有上限
4. **代码复用**：和 Skills 共用 frontmatter 解析逻辑

### 3.2 目标架构

```
.xiaoagent/
├── memory/                   # Memory 目录
│   ├── MEMORY.md             # 索引文件（始终在 System Prompt）
│   ├── user_role.md          # 用户记忆
│   ├── feedback_testing.md   # 反馈记忆
│   └── project_deadline.md   # 项目记忆
├── settings.json             # 权限规则
├── tasks/                    # 持久化任务
└── ...
```

### 3.3 文件格式

```markdown
---
name: user_role
description: 用户是数据科学家，当前专注于日志系统
type: user
---

用户是一名数据科学家，目前正在调查项目的日志基础设施。
回答问题时应侧重于数据分析和可观测性的视角。
```

### 3.4 核心模块设计

```
services/
└── memory.py               # Memory 管理器

新增功能：
1. MemoryManager 类
   - load_index()     — 读取 MEMORY.md 索引
   - save_memory()    — 保存一条记忆（创建文件 + 更新索引）
   - list_memories()  — 列出所有记忆
   - delete_memory()  — 删除记忆
   - get_prompt()     — 构建 Memory 的 System Prompt 片段

2. System Prompt 集成
   - context.py 中调用 memory.get_prompt() 追加到 prompt

3. 两个新工具（或复用现有 Write/Edit）
   - 方案 A: LLM 直接用 write_file 写 memory 目录下的文件
   - 方案 B: 专门的 save_memory 工具
   → 选择方案 A（更简单，对齐 CC 的做法——CC 也是让 LLM 用 Write 工具写记忆文件）
```

### 3.5 System Prompt 中的 Memory 指令

在 `system-prompt.md` 末尾追加 Memory 指令（对齐 CC 的 buildMemoryLines）：

```markdown
# Memory

You have a persistent memory system at `.xiaoagent/memory/`.
Write to it when you learn important information about the user or project.

## Memory Types
- **user**: User's role, preferences, knowledge level
- **feedback**: User corrections or confirmed approaches  
- **project**: Ongoing work, decisions, deadlines
- **reference**: Pointers to external systems

## How to Save
1. Write the memory file with frontmatter (name, description, type)
2. Add a one-line entry to MEMORY.md

## What NOT to Save
- Code patterns (derivable from code)
- Git history (use git log)
- Anything in CLAUDE.md
- Current conversation details (use tasks instead)

## When to Access
- When memories seem relevant to the current task
- When the user explicitly asks to recall something
```

### 3.6 实施步骤

```
步骤 1: 创建 services/memory.py
  - MemoryManager 类
  - load_index(), save_memory(), list_memories(), get_prompt()
  - MEMORY.md 读写（200 行上限）

步骤 2: 更新 bootstrap/state.py
  - 新增 MEMORY_DIR 路径常量
  - 新增 memory 运行时实例

步骤 3: 更新 main.py
  - 初始化 MemoryManager

步骤 4: 更新 context.py
  - build_system_prompt() 中调用 memory.get_prompt()
  - 追加到 system prompt 末尾

步骤 5: 更新 system-prompt.md
  - 添加 {{memory_instructions}} 占位符

步骤 6: 权限集成
  - services/permissions.py 中为 memory 目录添加写入白名单
  （LLM 用 write_file/edit_file 写记忆文件时不应弹确认）

步骤 7: 测试
  - 创建示例记忆文件
  - 验证 System Prompt 包含 MEMORY.md 内容
  - 验证 LLM 能读写记忆
```

### 3.7 暂不实现的 CC 功能

| CC 功能 | 暂不实现原因 | 后续迭代优先级 |
|---------|-------------|--------------|
| 自动记忆提取 | 需要 forked agent + 权限隔离 | 中 |
| 相关性选择 | 需要额外 API 调用（Sonnet） | 中 |
| Team Memory | 需要共享目录 + 同步 | 低 |
| Agent Memory | 需要 per-agent 隔离 | 低 |
| 每日日志 + 夜间整合 | 仅 KAIROS 助手模式 | 低 |
| 200 文件上限 + 驱逐 | 基础版不会有这么多 | 低 |

### 3.8 功能对照表

| 功能 | CC 实现 | 计划实现 | 简化说明 |
|------|--------|---------|---------|
| 四种类型 | user/feedback/project/reference | 同 | 对齐 |
| MEMORY.md 索引 | 200 行/25KB 上限 | 200 行上限 | 对齐 |
| Frontmatter 格式 | name/description/type | 同 | 对齐 |
| System Prompt 指令 | buildMemoryLines() | 模板注入 | 简化 |
| 显式保存 | LLM 用 Write 工具 | 同 | 对齐 |
| 自动提取 | forked agent | 不实现 | 后续 |
| 相关性加载 | Sonnet 选择 5 个 | 不实现 | 后续 |
| Memory 目录白名单 | 写入时跳过权限确认 | 实现 | 对齐 |
| "不存什么"规则 | 详细列表 | 在 prompt 中声明 | 对齐 |
