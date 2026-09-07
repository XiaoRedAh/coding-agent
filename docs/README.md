# docs — 文档索引

本目录是项目开发过程中的文档存档，按文档性质分类组织。所有文件均为历史记录，**不代表其描述的一定与当前代码一致**，阅读时请以 `../README.md` 和代码为准。

> 相关但暂未归入本目录的调研资料：
> - `../cc源码调研/` — Claude Code 源码逐模块调研（docs 调研报告的上游素材）
> - `../最小化对齐/` — 按模块与 Claude Code 对齐的学习笔记

## 目录结构

| 目录 | 内容 | 数量 |
|------|------|------|
| [`01-research/`](01-research/) | 外部技术/产品调研（含竞品分析） | 9 |
| [`02-plans/`](02-plans/) | 历史设计方案与实施计划 | 8 |
| [`03-retrospectives/`](03-retrospectives/) | 开发过程复盘与时点记录 | 7 |
| [`04-architecture/`](04-architecture/) | 项目架构详解（与代码对照阅读，当前版） | 11 |
| [`archive/`](archive/) | 已被新版本取代的过时文档 | 5 |

---

## 01-research/ — 技术调研

外部技术原理 / 产品能力调研，用于支撑后续设计决策。

| 文件 | 说明 |
|------|------|
| `Agent Skills深度解读.md` | Agent Skills 概念、原理与实现教程 |
| `Agent失败处理调研报告.md` | 基于 Claude Code 源码的失败处理机制调研 |
| `Agent测试与评估深度调研.md` | Agent 测试/观测/评估方法调研（2026-04-05） |
| `AI Agent中的LLM深度调研.md` | Agent 对 LLM 的能力要求与模型选型（2026-04-07） |
| `MCP深度解读.md` | MCP 协议深度解析（2026-04） |
| `模型接入调研.md` | 多模型接入实践调研 |
| `流式输出调研.md` | LLM 流式输出原理与实现 |
| `类似产品横向分析报告.md` | Claude Code / Codex CLI / Gemini CLI 等横向对比 |

## 02-plans/ — 设计与计划

项目内部设计方案与实施计划。**多数已完成落地**（对应代码已存在），保留作为演进记录。

| 文件 | 对应落地代码（如已实施） |
|------|------|
| `Coordinator模式调研与重构计划.md` | `agents/coordinator.py` |
| `memory system搭建计划.md` | `services/memory.py` |
| `MetaGPT简化版多Agent协作实现计划.md` | `workflows/` |
| `META_GPT_IMPLEMENTATION_PLAN.md` | `workflows/`（v4 计划） |
| `prompt cache实现计划.md` | `context.py` |
| `sub agent和多agent协作重构计划.md` | `agents/subagent.py` |

## 03-retrospectives/ — 复盘与记录

开发过程中某一时点的分析、复盘与改动记录，反映项目演进历史。

| 文件 | 说明 |
|------|------|
| `Coordinator模式现阶段分析报告.md` | Coordinator 代码质量与测试契约漂移分析（2026-04-21） |
| `memory机制深度分析报告-2026-04-26.md` | Memory 机制工程缺口分析（2026-04-26） |
| `SOP会话问题复盘-2026-04-23.md` | SOP 流程未收敛问题复盘（2026-04-23） |
| `交互体验优化.md` | CLI 交互体验改进记录 |
| `本次代码优化修改说明.md` | 某次代码优化（通知、错误计数等 bug 修复）说明 |
| `测试与评估结果分析.md` | 测试与评估执行情况记录 |
| `项目组件分析与清理.md` | 组件现状分析与 CC 对比 |

## 04-architecture/ — 项目详解（当前版）

对项目本身架构的讲解，**与当前代码对照阅读**。详见目录内 [README.md](04-architecture/README.md)
（含归档映射）。按模块拆分，每篇围绕一个子系统：

| 文件 | 主题 | 对应代码 |
|------|------|----------|
| `README.md` | 文档地图(mindmap) + 归档映射 + 阅读顺序 | - |
| `00-提示词工程与行为规则.md` | 三级覆盖、动静分离、base.md 逐节、fragments、度量（附录） | `prompts/` · `context/prompt.py` |
| `01-总览与启动流程.md` | 定位、目录、启动链路、配置分层、Prompt 体系、演进 | `main.py` · `config/` · `prompts/` |
| `02-核心循环.md` | AgentLoop、ReAct、plan-and-solve、错误恢复、等待闭环（附录·变更史） | `engine/loop.py` |
| `03-工具系统.md` | 工具定义/注册/分发、ToolResult、隔离、动态能力（附录） | `tools/` |
| `04-权限与安全.md` | 模式/规则/危险检测、决策管线、bypass-immune、自杀护栏（附录） | `services/permissions.py` |
| `05-上下文管理.md` | 五级压缩管线、预算/熔断、压缩后恢复（附录） | `context/compact.py` |
| `06-记忆系统.md` | 跨会话记忆、写引导、渐进式注入、KPI（附录） | `services/memory.py` |
| `07-技能系统.md` | Agent Skills、三层披露、双入口、多级来源（附录） | `skills/` |
| `08-多Agent与工作流.md` | 子 Agent、注册表、SOP 引擎、Coordinator 过时（附录） | `agents/` · `workflows/` |
| `09-稳定执行.md` | 失败处理全景 + 可观测性 + 复盘方法论（附录） | `engine/errors.py` · `services/tracing.py` |
| `10-并发与消息传递.md` | 线程/队列/锁/事件/事件总线的底层原理、手搓 vs 现成库 | `agents/task_queue.py` · `workflows/event_bus.py` |
| `项目评估体系详解.md` | ✅ 与 `../eval/` 对应（不重写） | `eval/` |

> 注：MCP 模块尚未测试重构，暂不编写详解；测试与评估不另行编写新文档。

## archive/ — 归档

被新版本明确取代的文档，保留以备追溯。

| 文件 | 取代者 |
|------|------|
| `项目详解.md` | 04-architecture 新体系（整体） |
| `项目详解-v2.md` | 新 `01-总览` / `02-核心循环` 等（2026-09-04 归档） |
| `项目失败处理详解.md` | 新 `09-稳定执行.md`（2026-09-04 归档） |
| `Coordinator模式详解.md` | Coordinator 已过时，仅在新 `08` 简述（2026-09-04 归档） |
| `MetaGPT简化版多Agent协作模式实现详解.md` | 新 `08-多Agent与工作流.md`（2026-09-04 归档） |

---

## 整理说明

- 本次整理（2026-09-01）：按"调研 / 计划 / 复盘 / 详解"四类归档，未改动任何文档内容，仅调整目录位置。
- 复盘类文档刻意保留原文件名与内容（含日期），作为真实的历史记录。
- 若某份"详解/计划"文档与当前代码出现出入，优先以代码与根目录 `README.md` 为准。
