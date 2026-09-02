from __future__ import annotations

import uuid

from .artifact_store import ArtifactStore
from .event_bus import EventBus
from .loader import WorkflowLoader
from .prompting import PromptBuilderForWorkflow
from .role_runtime import RoleRuntime
from .schemas import StructuredMessage, WorkflowRunResult, WorkflowStatus


class WorkflowEngine:
    def __init__(self):
        # 加载默认/自定义 workflow 配置
        self.loader = WorkflowLoader()

    def run(self, requirement: str, workflow_id: str = "metagpt-lite-3role") -> WorkflowRunResult:
        # 1) 初始化配置与运行期组件
        cfg = self.loader.load(workflow_id)
        print(
            f"\033[36m[Workflow]\033[0m loaded config: roles={len(cfg.roles)}, max_steps={cfg.max_steps}, max_fix_rounds={cfg.max_fix_rounds}",
            flush=True,
        )
        bus = EventBus()
        artifact_store = ArtifactStore("artifacts")
        prompt_builder = PromptBuilderForWorkflow()

        # 2) 为每个角色创建运行时执行器
        runtimes = {
            role.name: RoleRuntime(
                role=role,
                artifact_store=artifact_store,
                prompt_builder=prompt_builder,
                schema_version=cfg.schema_version,
            )
            for role in cfg.roles
        }

        # 3) 注册订阅关系（topic -> role）
        for role in cfg.roles:
            bus.subscribe(role.name, role.subscriptions)

        # 4) 发布初始事件，驱动流程启动
        bus.publish(
            StructuredMessage(
                message_id=f"msg-{uuid.uuid4().hex[:12]}",
                schema_version=cfg.schema_version,
                topic="user.requirement",
                sent_from="User",
                send_to=[],
                cause_by="user.input",
                payload={"requirement": requirement},
                artifact_refs=[],
                status="success",
            )
        )

        fix_round = 0
        terminal_topic = "workflow.failed"
        status = WorkflowStatus.FAILED
        summary = "Workflow stopped before reaching a terminal success condition."
        generated_artifacts: list[str] = []

        # 主循环：逐步消费消息，直到触发终态或无进展
        for step_idx in range(cfg.max_steps):
            print(
                f"\033[90m[Workflow]\033[0m step {step_idx + 1}/{cfg.max_steps} (fix_round={fix_round}/{cfg.max_fix_rounds})",
                flush=True,
            )
            progressed = False
            for role in cfg.roles:
                incoming = bus.consume(role.name)
                if not incoming:
                    continue

                progressed = True
                print(
                    f"\033[90m[Workflow]\033[0m role={role.name} consume={len(incoming)}",
                    flush=True,
                )
                # 角色执行后会产出新的结构化消息，继续发布到总线
                # （异常兜底：单个角色崩溃不应炸掉整个 workflow）
                try:
                    produced = runtimes[role.name].execute(
                        requirement=requirement,
                        incoming_messages=incoming,
                        fix_round=fix_round,
                        max_fix_rounds=cfg.max_fix_rounds,
                    )
                except Exception as exc:
                    print(
                        f"\033[31m[Workflow]\033[0m role={role.name} crashed: {exc}",
                        flush=True,
                    )
                    failed = StructuredMessage(
                        message_id=f"msg-{uuid.uuid4().hex[:12]}",
                        schema_version=cfg.schema_version,
                        topic="workflow.failed",
                        sent_from=role.name,
                        send_to=[],
                        cause_by=f"{role.name}.exception",
                        payload={
                            "error": str(exc)[:500],
                            "role": role.name,
                        },
                        artifact_refs=[],
                        status="fail",
                    )
                    bus.publish(failed)
                    return WorkflowRunResult(
                        status=WorkflowStatus.FAILED,
                        workflow_id=cfg.workflow_id,
                        requirement=requirement,
                        summary=f"Role {role.name} crashed: {str(exc)[:200]}",
                        terminal_topic="workflow.failed",
                        generated_artifacts=sorted(set(generated_artifacts)),
                        event_log=bus.event_log,
                    )
                for msg in produced:
                    generated_artifacts.extend(msg.artifact_refs)
                    bus.publish(msg)
                    print(
                        f"\033[90m[Workflow]\033[0m role={role.name} published topic={msg.topic}, artifacts={len(msg.artifact_refs)}",
                        flush=True,
                    )

                    if msg.topic == "test.failed":
                        # 失败回路计数：超过阈值则升级人工接管
                        fix_round += 1
                        print(
                            f"\033[33m[Workflow]\033[0m test.failed -> fix_round={fix_round}/{cfg.max_fix_rounds}",
                            flush=True,
                        )
                        if fix_round > cfg.max_fix_rounds:
                            escalated = StructuredMessage(
                                message_id=f"msg-{uuid.uuid4().hex[:12]}",
                                schema_version=cfg.schema_version,
                                topic="workflow.escalated",
                                sent_from="WorkflowEngine",
                                send_to=[],
                                cause_by="fix-round-limit",
                                payload={
                                    "reason": "Exceeded max fix rounds",
                                    "max_fix_rounds": cfg.max_fix_rounds,
                                    "actual_fix_rounds": fix_round,
                                },
                                artifact_refs=[],
                                status="fail",
                            )
                            bus.publish(escalated)
                            terminal_topic = escalated.topic
                            status = WorkflowStatus.ESCALATED
                            summary = "Workflow escalated because test-fix loop exceeded max rounds."
                            print(
                                "\033[31m[Workflow]\033[0m escalated: exceeded max fix rounds",
                                flush=True,
                            )
                            return WorkflowRunResult(
                                status=status,
                                workflow_id=cfg.workflow_id,
                                requirement=requirement,
                                summary=summary,
                                terminal_topic=terminal_topic,
                                generated_artifacts=sorted(set(generated_artifacts)),
                                event_log=bus.event_log,
                            )

                    if msg.topic in cfg.terminal_topics:
                        # 命中终态，立即返回结果
                        terminal_topic = msg.topic
                        if msg.topic == "test.passed":
                            status = WorkflowStatus.PASSED
                            summary = "Workflow completed successfully with passing tests."
                        elif msg.topic == "workflow.escalated":
                            status = WorkflowStatus.ESCALATED
                            summary = "Workflow escalated after repeated failures."
                        else:
                            status = WorkflowStatus.FAILED
                            summary = "Workflow finished with failure state."
                        print(
                            f"\033[36m[Workflow]\033[0m terminal topic={msg.topic}, status={status.value}",
                            flush=True,
                        )
                        return WorkflowRunResult(
                            status=status,
                            workflow_id=cfg.workflow_id,
                            requirement=requirement,
                            summary=summary,
                            terminal_topic=terminal_topic,
                            generated_artifacts=sorted(set(generated_artifacts)),
                            event_log=bus.event_log,
                        )

            if not progressed:
                # 没有任何角色消费到新消息，说明流程已停滞
                print("\033[33m[Workflow]\033[0m no progress in this step, stopping", flush=True)
                break

        return WorkflowRunResult(
            status=status,
            workflow_id=cfg.workflow_id,
            requirement=requirement,
            summary=summary,
            terminal_topic=terminal_topic,
            generated_artifacts=sorted(set(generated_artifacts)),
            event_log=bus.event_log,
        )
