# MetaGPT简化版多Agent协作实现计划（面向当前项目）

## 1. 目标与边界

## 1.1 本阶段目标（必须实现）

围绕 MetaGPT 的核心思想，在当前项目中新增一个“可运行、可扩展、可治理”的多 Agent 协作模式，且至少完整覆盖：

1. SOP 工作流程（标准化阶段 + 阶段产物 + 阶段切换规则）。
2. 角色定义与规范（职责、输入、输出、约束、失败处理）。
3. Structured Communication（结构化消息与结构化产物）。
4. Publish-Subscribe Mechanism（发布-订阅消息路由与触发执行）。
5. 提示词工程（角色系统提示、动作提示、输出格式约束、错误恢复提示）。

## 1.2 本阶段简化范围（三角色）

仅先复现三角色协作：

1. 分析与设计角色（AnalystDesigner）
2. 工程师角色（Engineer）
3. 测试师角色（Tester）

## 1.3 非目标（本阶段不做）

1. 不替换现有 normal / coordinator / subagent 主流程。
2. 不改写已有内置 subagent 定义。
3. 不一次性做能力白名单重构。
4. 不追求“全自动无限修复”，而是明确最大迭代轮次与可回退策略。

---

## 2. 方法论定位（回答你的概念问题）

你提到“这算不算 workflow 模式的多agent协作？MetaGPT 属于哪种？”

结论：

1. 是，属于 workflow-oriented 多 Agent 协作（可称 Agentic Workflow）。
2. MetaGPT 的经典形态是 Role-based SOP Pipeline + Structured Artifacts + Pub/Sub Message Bus。
3. 不是纯自由对话群聊式协作，而是“有角色、有阶段、有文档契约”的受控流水线。

在你的项目里，建议命名为：

- SOP 协作模式（SOP Collaboration Mode）
- 或 MetaWorkflow 模式（内部代号）

---

## 3. 与当前项目的集成原则（保证不破坏现有功能）

## 3.1 新增，不侵入

采用“并行新模块 + 单点入口开关”策略：

1. 新建独立模块，不改动现有 `agents/definitions.py` 内置子代理表。
2. 在 `query.py` 只新增一个模式分流入口（例如 `SOP_MODE=1` 或显式命令触发），未触发时走原逻辑。
3. 复用现有能力：`agent_loop`、`agent` 工具、`run_shell`、`read_file/write_file/edit_file`、权限系统、压缩系统。

## 3.2 兼容优先

1. 默认关闭新模式（feature flag）。
2. 新模块异常时自动降级为“返回失败报告”，不影响主 REPL 可用性。
3. 所有新增数据结构版本化（schema_version）。

---

## 4. 总体架构设计（简化版 MetaGPT）

## 4.1 架构分层

1. Workflow Layer：定义 SOP 图（阶段节点、依赖、路由规则）。
2. Role Layer：三角色实现（角色配置 + 提示词模板 + 执行动作）。
3. Communication Layer：消息总线（发布/订阅/路由/重试）。
4. Artifact Layer：公共工作空间产物仓库（文档、代码、测试报告、清单）。

## 4.2 关键组件

1. WorkflowEngine（流程引擎）
2. RoleRegistry（角色注册中心，含自定义角色）
3. EventBus（发布订阅）
4. ArtifactStore（产物管理）
5. PromptBuilderForWorkflow（工作流提示词组装）

---

## 5. Structured Communication 设计

## 5.1 统一消息信封（Message Envelope）

所有角色通信统一为结构化 JSON（内部对象），核心字段：

1. message_id
2. schema_version
3. topic（如 `analysis.done`, `code.submitted`, `test.failed`）
4. sent_from（角色名）
5. send_to（角色名集合或广播）
6. cause_by（动作名）
7. payload（结构化内容）
8. artifact_refs（产物路径引用）
9. status（pending/success/fail）
10. timestamp

## 5.2 统一产物契约

角色之间尽量传“引用”而非大文本正文：

1. 大文档入 ArtifactStore。
2. 消息中放 `artifact_refs`。
3. 下游角色按引用拉取。

好处：

1. 降低上下文膨胀。
2. 提升可追溯性。
3. 与你现有压缩机制更兼容。

---

## 6. Publish-Subscribe 机制设计

## 6.1 订阅模型

每个角色定义关心的 topic：

1. AnalystDesigner 订阅：`user.requirement`
2. Engineer 订阅：`analysis.done`, `test.failed`
3. Tester 订阅：`code.submitted`

## 6.2 路由规则

1. 精确 topic 匹配（后续可扩展通配符）。
2. 支持定向发送与广播发送。
3. 支持“仅最新消息”与“积压消息重放”策略。

## 6.3 触发执行

1. EventBus 投递消息到角色私有队列。
2. WorkflowEngine 调度角色消费。
3. 角色执行后再发布下一条结构化消息。

---

## 7. 三角色 SOP 设计（本阶段核心）

## 7.1 角色一：分析与设计（AnalystDesigner）

职责：

1. 把用户需求转为可执行设计包。

输入：

1. 用户原始需求。

输出（必须产出单文档 + 结构化摘要）：

1. `artifacts/analysis/analysis_design.md`
2. `artifacts/analysis/analysis_design.json`（可选）

文档至少包含：

1. 目标与范围
2. 功能清单（优先级）
3. 技术方案
4. 模块拆分与文件建议
5. 接口/数据结构草案
6. 实施步骤
7. 验收标准（供 Tester 使用）

发布消息：

1. topic=`analysis.done`
2. 附 `artifact_refs`

## 7.2 角色二：工程师（Engineer）

职责：

1. 按设计包产出完整代码（可多文件）。

输入：

1. `analysis.done` 消息与设计文档引用。
2. （失败回路时）`test.failed` 缺陷报告。

输出建议（关键问题：提交什么到公共工作空间）

答案：提交“代码本体 + 交付清单”，而不是只提交一份说明文档。

必须产出：

1. 实际代码文件（落在目标项目目录）
2. `artifacts/code/delivery_manifest.json`
3. `artifacts/code/change_summary.md`

`delivery_manifest.json` 至少包含：

1. changed_files（新增/修改文件）
2. entry_points（运行入口）
3. run_commands（启动/构建/测试命令）
4. assumptions（关键假设）
5. known_risks（已知风险）

发布消息：

1. topic=`code.submitted`
2. 附 `artifact_refs`

## 7.3 角色三：测试师（Tester）

职责：

1. 基于验收标准与交付清单执行验证并给出通过/不通过结论。

输入：

1. `code.submitted` 消息。
2. 分析阶段的验收标准。

执行：

1. 读取 `delivery_manifest.json`。
2. 执行测试命令（单测/集成/静态检查，按项目能力）。
3. 生成测试报告与缺陷清单。

如何判断“测试通过”：

本阶段定义明确门禁（可配置）：

1. 阻塞级失败数（blocker）为 0。
2. 关键测试集全部通过。
3. 关键运行命令返回码为 0。

输出：

1. `artifacts/test/test_report.md`
2. `artifacts/test/test_report.json`
3. 若失败：`artifacts/test/bug_ticket_list.json`

发布消息：

1. 通过：topic=`test.passed`
2. 失败：topic=`test.failed`（定向发给 Engineer）

---

## 8. 失败回路与终止条件

## 8.1 失败回路

1. Tester 发布 `test.failed`。
2. Engineer 接收并修复。
3. Engineer 再次发布 `code.submitted`。
4. Tester 再测。

## 8.2 终止策略（防止死循环）

1. 最大修复轮次 `max_fix_rounds`（例如 3）。
2. 连续同类错误阈值限制。
3. 超阈值后输出“人工接管报告”，流程结束。

---

## 9. 提示词工程方案（精心设计）

## 9.1 设计原则

1. 角色身份稳定（Role Card 固化）。
2. 输出格式硬约束（模板 + JSON schema + 示例）。
3. 失败场景专门提示（当测试失败时如何读取缺陷单并最小修复）。
4. 明确禁止项（越权改动、无关重构、跳过测试）。

## 9.2 三层提示词结构

1. Layer A：系统角色提示（长期稳定）。
2. Layer B：阶段任务提示（当前 SOP 节点）。
3. Layer C：结构化输出提示（模板和 schema）。

## 9.3 Prompt 产物

建议新增：

1. `prompts/workflow/analyst.md`
2. `prompts/workflow/engineer.md`
3. `prompts/workflow/tester.md`
4. `prompts/workflow/common_output_schema.json`

---

## 10. 可定制化设计（角色与流程）

## 10.1 目标

你要求“不要写死成仅 MetaGPT 三角色 SOP”，因此必须支持：

1. 用户新增自定义 sub agent。
2. 用户新增/修改流程并绑定角色。

## 10.2 不改内置 subagent 的实现方式

采取“扩展注册中心”而非修改内置表：

1. 保持 `agents/definitions.py` 原样。
2. 新增 `agents/custom_registry.py`，从配置目录加载自定义角色。
3. Workflow 模式只使用“合并后的只读视图”，不回写内置定义。

## 10.3 流程可定制化（DAG 配置）

新增配置文件（建议）：

1. `.xiaoagent/workflows/roles/*.yaml`
2. `.xiaoagent/workflows/pipelines/*.yaml`

示例能力：

1. 定义节点（role/action）
2. 定义边（on topic）
3. 定义终止条件
4. 定义轮次限制

本阶段先内置一个默认 `metagpt-lite-3role.yaml`，后续开放 UI/命令行编辑。

---

## 11. 技术栈与实现依赖

## 11.1 技术栈

1. 语言：Python（沿用当前项目）
2. 并发：先同步驱动 + 队列（必要处可线程）
3. 数据模型：Pydantic（项目已有）
4. 消息总线：项目内轻量 EventBus（内存队列）
5. 持久化：文件系统（ArtifactStore）
6. 执行：复用 `agent_loop` 与已有 tools

## 11.2 建议新增模块

1. `workflows/engine.py`（流程引擎）
2. `workflows/event_bus.py`（发布订阅）
3. `workflows/schemas.py`（消息/产物 schema）
4. `workflows/role_runtime.py`（角色运行时）
5. `workflows/artifact_store.py`（产物存储）
6. `workflows/loader.py`（角色/流程配置加载）
7. `workflows/defaults/metagpt_lite_3role.yaml`

---

## 12. 与现有系统的接入点

## 12.1 最小接入

1. 在 `query.py` 增加一个模式分支入口：
   - 触发条件：环境变量或用户命令（如 `/workflow metagpt-lite`）
2. 入口函数仅调用 `WorkflowEngine.run(requirement, workflow_id)`。
3. 未触发时完全不进入新代码路径。

## 12.2 与现有工具系统复用

1. 角色执行内部仍可调用 `agent_loop`。
2. 工程师/测试师实际动作继续通过现有工具权限体系执行。
3. 不破坏你现有 coordinator 机制。

## 12.3 主Agent责任与会话生命周期（关键澄清）

结论：需要保留主agent，且不会在流程跑完后直接退出进程。

1. 主agent长期驻留在 REPL 会话中，负责接收用户输入、决定是否触发 workflow、汇总最终结果并继续对话。
2. WorkflowEngine 是“单次需求处理器”，只负责完成一次 SOP 流程（从 `user.requirement` 到 `test.passed/test.failed/escalated`）。
3. 单次流程结束后，系统返回主agent控制权，主agent输出阶段总结与产物索引，然后继续等待用户下一条消息。
4. 用户可在同一会话继续提问（追问、改需求、发起下一轮 workflow、切回普通问答模式）。
5. 只有用户主动退出（如 `q/exit`）时，REPL 才结束；workflow 完成本身不触发退出。

建议的运行时状态机：

1. `IDLE`：主agent待命，接收用户输入。
2. `WORKFLOW_RUNNING`：主agent将当前需求委托给 WorkflowEngine，并监听事件。
3. `WORKFLOW_DONE`：WorkflowEngine返回结果给主agent。
4. `BACK_TO_IDLE`：主agent向用户回复后回到待命，继续接受提问。

---

## 13. 工程质量与可维护性设计

## 13.1 可复用性

1. SOP 配置驱动（不是硬编码 if/else）。
2. Role 卡片与 Prompt 模板分离。
3. 消息 schema 与业务逻辑分离。

## 13.2 可观测性

1. 每轮输出事件日志（发布者、topic、订阅者、耗时）。
2. 每阶段输出产物路径和摘要。
3. 最终输出 workflow execution report。

## 13.3 安全性

1. 角色执行仍走现有权限检查。
2. 限制最大迭代轮次和最大文件改动规模（可配置）。
3. 对危险命令保持 confirm/deny 机制不变。

---

## 14. 实施计划（分阶段）

## Phase 1：协议与骨架（2-3 天）

1. 定义消息 schema 与产物 schema。
2. 实现 EventBus 与 WorkflowEngine 骨架。
3. 实现默认三角色 workflow 配置解析。

产出：

1. 可跑通“空执行流程”（不执行业务，仅消息流）。

## Phase 2：三角色最小可用（3-5 天）

1. 实现 AnalystDesigner（产出分析文档）。
2. 实现 Engineer（产出代码 + 交付清单）。
3. 实现 Tester（执行测试 + 通过/失败判定）。
4. 接入失败回路与最大轮次终止。

产出：

1. 端到端可执行的 `metagpt-lite-3role`。

## Phase 3：可定制化（2-4 天）

1. 实现自定义角色加载（YAML）。
2. 实现自定义流程 DAG 加载。
3. 增加流程校验器（环检测、孤立节点、未订阅 topic）。

产出：

1. 用户可新增角色与流程配置。

## Phase 4：稳定性与治理（2-3 天）

1. 单元测试：schema、路由、终止条件。
2. 组件测试：三角色标准流程。
3. 回归验证：normal/coordinator 路径不受影响。

---

## 15. 验收标准（本阶段）

1. 输入一个需求后，三角色按 SOP 顺序协作完成。
2. 角色间通信全部使用结构化消息。
3. 产物可追溯（analysis/code/test 与清单齐全）。
4. 测试失败可触发至少一轮修复回路。
5. 达到终止条件后有明确最终状态（passed/failed/escalated）。
6. 关闭新模式时，现有 normal/coordinator 行为与结果不变。

---

## 16. 风险与应对

1. 风险：上下文过长导致角色漂移。
- 应对：消息传引用、产物落盘、模板约束输出。

2. 风险：测试回路陷入震荡。
- 应对：最大轮次 + 缺陷去重 + 强制最小变更策略。

3. 风险：用户自定义流程配置错误。
- 应对：加载前 schema 校验 + DAG 校验 + 友好错误提示。

4. 风险：与现有功能耦合扩大。
- 应对：独立模块 + feature flag + 明确边界接口。

---

## 17. 建议的首版默认流程（你当前需求对应）

1. `user.requirement` -> AnalystDesigner
2. AnalystDesigner 发布 `analysis.done`
3. Engineer 订阅 `analysis.done`，输出代码并发布 `code.submitted`
4. Tester 订阅 `code.submitted`
5. 若通过 -> 发布 `test.passed` 并结束
6. 若失败 -> 发布 `test.failed` 给 Engineer
7. Engineer 修复后回到步骤 3，最多 N 轮
8. WorkflowEngine 结束后把结果回传主agent，由主agent继续与用户交互（不退出会话）

---

## 18. 结论

该方案在“机制复现完整度”与“工程落地风险”之间做了平衡：

1. 保留 MetaGPT 的核心方法论（SOP、结构化协作、发布订阅、可执行反馈）。
2. 先用三角色完成最小闭环，快速可用。
3. 从第一天就设计成可配置工作流，而不是一次性写死。
4. 与现有项目解耦，确保不影响当前 normal/coordinator 稳定性。
