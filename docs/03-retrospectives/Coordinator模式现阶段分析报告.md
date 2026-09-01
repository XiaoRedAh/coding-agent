# Coordinator 模式现阶段分析报告（2026-04-21）

## 0. 分析范围与结论摘要

### 分析范围
- 代码：`agents/coordinator.py`、`query.py`、`agents/subagent.py`、`agents/task_queue.py`、`agents/definitions.py`、`context.py`、`tools/__init__.py`
- 文档：`Coordinator模式详解.md`
- 测试证据：`tests/unit/test_coordinator.py`、`tests/component/test_agent_loop.py`

### 一句话结论
当前 Coordinator 模式“可运行，但工程一致性较弱”：核心并行机制已经成型，但与普通模式能力、测试基线、提示词与运行时契约存在明显漂移，导致你感受到的“可控性下降”和“管理混乱”是客观存在的。

---

## 1. 代码质量评估：当前到底混乱在哪里？

## 1.1 优点（已有基础）
- 职责主线清晰：Coordinator 负责“规划-派发-汇总”，Worker 负责执行。
- 并行回传机制合理：`AgentTaskQueue` + `wait_and_drain()` 能解决异步结果回流。
- 防护意识较强：主循环有 `max_turns`、连续 LLM 错误上限、工具错误上限。
- 文档覆盖面高：`Coordinator模式详解.md` 对流程解释很细。

## 1.2 主要质量问题（按严重性）

### P0：实现与测试契约严重漂移（高风险）
证据：运行目标测试后出现 `14 failed, 11 passed`，失败集中在 `test_coordinator` 与 `test_agent_loop`。

表现：
- 测试仍在验证“旧的 team/通信工具语义”（如 `send_message/read_inbox/broadcast`），但当前 `coordinator.py` 已切到新 Orchestrator 语义。
- `test_agent_loop` 中 mock 结构也与当前实现契约不一致（如通知返回值结构、响应字段预期），导致大量 `StopIteration`/断言偏差。

影响：
- 你无法通过测试快速判断“改动是否安全”，重构速度越快，失控感越强。

### P1：模式能力不对齐（普通模式 vs Coordinator）
证据：
- 普通模式走 `build_system_prompt()`，有 prompt cache block、skills 概览、MCP instructions、memory 注入。
- Coordinator 模式直接使用 `COORDINATOR_SYSTEM_PROMPT` 字符串，并按白名单裁剪工具。

影响：
- 你提到的“普通模式有 prompt cache/skills/MCP，Coordinator 没有”基本属实（至少主 Coordinator 本体如此）。
- 同一个系统在不同模式下行为差异过大，认知成本和维护成本都会上升。

### P1：交互与异步流程存在边界缺陷
证据：`query.py` 仅在 `is_coordinator_mode()` 下处理 `state.agent_tasks` 通知。

影响：
- 如果普通模式中调用 `agent(run_in_background=True)`，结果不会进入通知处理链，可能出现“后台子任务完成了但主流程无感知”。

### P1：SubAgent 工具错误计数存在重复累加
证据：`agents/subagent.py` 中同一工具失败路径会在异常分支与错误标记分支重复 `consecutive_tool_errors += 1`。

影响：
- Worker 可能比预期更早触发“工具错误过多停止”，降低任务鲁棒性。

### P2：提示词与运行时细节仍有小瑕疵
证据：`COORDINATOR_SYSTEM_PROMPT` 里 `## WORKING DIRECTORY: {WORKDIR}` 不是 f-string，运行时不会插值。

影响：
- 会降低提示词可信度与可用性（虽然不是致命 bug）。

### P2：单体函数过重，修改风险偏高
证据：`query.agent_loop()` 负责压缩、通知、LLM 调用、权限、工具执行、错误恢复、截断续写等多职责。

影响：
- 任何局部改动都容易引发回归，且测试定位困难。

---

## 2. 你关心的“能力对齐”问题：需要对齐吗？

## 2.1 结论
需要对齐，但不是“100% 同构对齐”，而是“分层对齐”。

建议原则：
- 统一基础设施层：上下文注入框架、工具发现机制、异步通知协议、错误恢复协议。
- 保留角色差异层：Coordinator 只做 orchestration（可读、可派发、可汇总），Worker 执行具体操作。

## 2.2 三项能力逐项判断

### A. Prompt Cache
- 现状：普通模式支持；Coordinator 主体不支持分块 cache。
- 判断：建议对齐。
- 做法：让 Coordinator 也复用 `build_system_prompt()` 的分块机制，再叠加 Coordinator 专属规则块，而不是完全绕开。

### B. Skills 集成
- 现状：普通模式可 `load_skill`；Coordinator 白名单没有 `load_skill`；Worker(general) 有。
- 判断：建议“有限对齐”。
- 做法：
  - Coordinator 主体不必开放所有技能，但应能读取“技能目录摘要”并可按需 `load_skill`（至少用于规划约束）。
  - 如果担心越权，可只允许只读技能类（策略/流程技能），不允许执行型技能。

### C. MCP 集成
- 现状：普通模式主 Agent 可见 MCP 工具；Coordinator 白名单机制无法自然纳入动态 MCP 工具名；SubAgent 的固定 `allowed_tools` 也会过滤掉 MCP 动态工具。
- 判断：建议对齐（至少在 Worker 层对齐）。
- 做法：
  - 将“静态白名单”改为“能力标签白名单”（例如 read/search/shell/mcp/skill/spawn），由注册中心映射到具体工具名（含动态 MCP）。
  - Coordinator 主体可选只读 MCP；Worker(general) 应支持 MCP（否则多源信息任务能力明显受限）。

---

## 3. 协调者模式实现质量：明显 bug 与优化方向

## 3.1 明显问题清单（建议优先修）

### Bug-1：非 Coordinator 模式下异步 Agent 通知丢失
- 位置：`query.py` 的 `if state.agent_tasks and is_coordinator_mode():`
- 现象：普通模式异步 sub-agent 完成后，通知不会被消费。
- 方案：将通知处理从“模式判断”剥离为统一事件循环能力，再由模式决定“如何解释通知”。

### Bug-2：SubAgent 工具错误计数重复累加
- 位置：`agents/subagent.py` 工具执行分支。
- 现象：同一次失败可能记两次错误，导致过早终止。
- 方案：每个工具调用仅计算一次最终错误状态，避免多点累加。

### Bug-3：Coordinator 提示词中的工作目录变量未插值
- 位置：`agents/coordinator.py` 的 `COORDINATOR_SYSTEM_PROMPT`。
- 现象：`{WORKDIR}` 原样输出。
- 方案：改成 f-string 或统一交由 context 构建器注入。

### Bug-4：测试体系与实现脱节
- 位置：`tests/unit/test_coordinator.py`、`tests/component/test_agent_loop.py`
- 现象：旧语义断言仍在，mock 协议落后于当前实现。
- 方案：先重建“契约测试”（协议级），再补行为测试。

## 3.2 交互/通信/提示词/工作流综合评价

### 交互
- 优点：日志可读，用户能看到 Worker 启动与完成。
- 问题：不同模式对异步通知行为不一致，造成“用户心智模型不一致”。

### 通信
- 优点：`task-notification` + `in-flight-count/all-complete` 协议直观。
- 问题：协议没有单独版本化/schema 测试，回归时难以及时发现。

### 提示词
- 优点：Coordinator 提示词结构化（Plan/Delegate/Synthesize）。
- 问题：与系统动态信息（skills/mcp/memory/git）脱钩，且存在变量未插值。

### 工作流
- 优点：并行分解思路正确。
- 问题：在工程层面缺少“模式共用内核 + 模式差异插件”的抽象，导致代码和测试都分叉漂移。

---

## 4. 代码质量提升方案（可落地）

## 4.1 两周可执行治理路线（建议）

### 第一阶段（1-3天）：止血
1. 修复 `query.py` 异步通知模式绑定问题。
2. 修复 `subagent.py` 工具错误重复计数。
3. 修复 `coordinator.py` 的 `{WORKDIR}` 注入。
4. 更新失败测试到当前协议，恢复“最小可信 CI”。

### 第二阶段（4-7天）：对齐
1. 抽象统一 `SystemPromptBuilder`：支持 mode overlays（normal/coordinator/subagent）。
2. 将 Coordinator 从“静态工具名白名单”升级为“能力标签白名单”。
3. 让 Worker(general) 支持动态 MCP 工具。
4. 为 Coordinator 增加可控的 `load_skill`（至少读策略技能）。

### 第三阶段（8-14天）：稳态
1. 拆分 `agent_loop`：
   - `collect_runtime_events()`
   - `call_llm_with_recovery()`
   - `execute_tool_blocks()`
   - `apply_post_turn_guards()`
2. 新增协议测试：
   - task notification schema
   - tool_result schema
   - truncation continuation schema
3. 新增端到端冒烟：normal/coordinator 各 1 条并行任务路径。

## 4.2 架构建议（避免再次混乱）

### 建议一：模式化内核（Kernel + Mode Policy）
- Kernel：统一循环、错误恢复、压缩、通知。
- Policy：只定义该模式的系统提示词 overlay、可用能力、策略阈值。
- 好处：功能扩展时不会复制粘贴整条链路。

### 建议二：能力中心化注册（Capability Registry）
- 以“能力”描述工具，不直接写死工具名。
- 动态工具（MCP）自动映射到能力。
- 好处：避免新增工具后要在 N 处手改白名单。

## 4.3 “工具名白名单”升级为“能力白名单”到底是什么意思？

这个概念可以简单理解为：

- 工具名白名单：你在模式里直接写死“允许哪些工具名”。
  - 例如：`{"read_file", "list_files", "grep_search", "run_shell", "agent"}`
- 能力白名单：你在模式里声明“允许哪些能力类别”，再由注册中心把类别解析为具体工具。
  - 例如：`{"cap.read", "cap.search", "cap.spawn", "cap.mcp.readonly"}`

一句话差异：
- 工具名白名单是“按按钮授权”（一个个按钮勾选）。
- 能力白名单是“按权限域授权”（先授权域，再自动包含域内按钮）。

### 4.3.1 为什么要这么做？

你这个项目已经出现了典型症状：
- 模式变多（normal / coordinator / subagent）。
- 工具变多（内置工具 + 动态 MCP 工具）。
- 工具会演进（重命名、新增、删除）。

继续用工具名白名单，会产生三个问题：

1. 可维护性差
- 每新增一个工具名，都要去多个白名单里同步更新。
- 漏改一个模式就会出现“这个模式里突然不能用”或“误放开”。

2. 动态工具天然不友好
- MCP 工具名是运行时动态生成的（如 `mcp__server__tool`），很难在静态白名单里优雅维护。

3. 安全策略表达能力弱
- 你真正想表达的通常是“允许只读搜索，不允许写入执行”，这本质上是能力约束，不是单个工具名约束。

### 4.3.2 在你项目里，能力白名单会长什么样？

建议先定义统一能力枚举（示例）：

- `cap.read`: 读取单文件内容
- `cap.list`: 列文件/目录
- `cap.search`: 文本或代码检索
- `cap.shell.readonly`: 只读命令执行
- `cap.shell.exec`: 通用命令执行
- `cap.file.write`: 新建写入
- `cap.file.edit`: 原地修改
- `cap.spawn`: 派生子 Agent
- `cap.skill.read`: 加载技能
- `cap.mcp.readonly`: 调用只读 MCP 工具
- `cap.mcp.exec`: 调用执行型 MCP 工具

然后给每个工具打能力标签（示例映射）：

- `read_file` -> `{cap.read}`
- `list_files` -> `{cap.list}`
- `grep_search` -> `{cap.search}`
- `run_shell` -> `{cap.shell.readonly, cap.shell.exec}`（再结合权限模式细分）
- `write_file` -> `{cap.file.write}`
- `edit_file` -> `{cap.file.edit}`
- `agent` -> `{cap.spawn}`
- `load_skill` -> `{cap.skill.read}`
- `mcp__*` -> 根据工具元数据判定为 `{cap.mcp.readonly}` 或 `{cap.mcp.exec}`

最后模式只声明允许能力，不再声明具体工具名（示例）：

- Coordinator：`{cap.read, cap.list, cap.search, cap.shell.readonly, cap.spawn, cap.skill.read, cap.mcp.readonly}`
- Worker(general)：`{cap.read, cap.list, cap.search, cap.shell.exec, cap.file.write, cap.file.edit, cap.skill.read, cap.mcp.exec}`

### 4.3.3 你打算怎么做（落地步骤）？

建议按“兼容迁移”做，不要一次性推翻：

1. 引入能力注册中心
- 新增 `CapabilityRegistry`（可放在 `tools/` 或 `services/`），提供：
  - 工具名 -> 能力标签映射
  - 能力标签 -> 工具名集合解析

2. 保留旧白名单字段，新增能力白名单字段
- 例如 `allowed_tools` 继续可用，同时新增 `allowed_capabilities`。
- 解析顺序：优先能力白名单；若为空则回退工具名白名单。

3. 改造工具过滤入口
- 你现在是 `get_all_definitions()/get_all_handlers()` 后按工具名过滤。
- 升级为“先按能力解析出 allowed tool names，再走现有过滤逻辑”。

4. 给 MCP 工具接入能力判定
- 在 `services/mcp.py` 生成 tool definition 时附加可选元信息（如只读标识）。
- 无元信息时先默认收敛到只读能力，避免误放开执行型能力。

5. 测试分三层补齐
- 注册中心单测：映射是否正确。
- 模式契约测：某模式允许/拒绝哪些能力。
- 集成测试：Coordinator 不能写文件但能调研+派发，Worker(general) 可执行。

### 4.3.4 这会不会让系统更复杂？

短期会增加一层抽象，长期会显著降低复杂度：

- 短期成本：多一个 registry 和映射维护。
- 长期收益：新增工具、调整模式、接入 MCP 时，不用在多处散点改白名单。

对你当前阶段（功能增长快、模式分叉明显）来说，这个改造的核心价值是：
- 把“分散配置复杂度”收敛为“中心化策略复杂度”，从而恢复可控性。

### 建议三：文档与测试跟代码同版本推进
- 每次改协议（如 notification 格式），必须同时改：
  - 文档片段
  - 契约测试
  - 迁移说明
- 好处：防止再出现“代码是新语义，测试还是旧语义”。

---

## 5. 对你当前问题的直接回答

1. 代码质量如何？
- 中等偏下（不是“烂”，但处在快速迭代后的失配期）。
- 最大问题不是算法，而是“模式分叉导致的一致性债务”。

2. 普通模式有 prompt cache/skills/mcp，Coordinator 没有，是否要对齐？
- 要对齐，但建议“基础设施全对齐 + 角色能力差异化”。
- 不建议继续让 Coordinator 成为“旁路实现”。

3. 协调者模式实现得怎么样？有明显 bug 吗？
- 并行主干思路是对的。
- 明显问题有：异步通知模式绑定、SubAgent 错误计数、提示词变量注入、测试契约漂移。
- 采用“模式化内核 + 能力注册中心 + 协议测试”是更稳妥的优化方向。

---

## 6. 建议你优先执行的 5 个动作（按收益排序）

1. 先修 3 个确定性 bug：通知处理、错误计数、`{WORKDIR}` 注入。
2. 把失败的 14 个测试按“过期测试/真实缺陷”两类重建。
3. 引入统一 PromptBuilder（Coordinator 不再绕开 context 管线）。
4. 将工具权限从“工具名白名单”升级为“能力白名单”。
5. 补一条 Coordinator 端到端回归测试（并行 2 Worker + 汇总输出）。

如果你愿意，我下一步可以直接给你一份“最小重构 PR 计划”（包含具体改哪些文件、每个文件改动点和对应测试用例）。
