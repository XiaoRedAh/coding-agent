from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime

from agents.subagent import run_subagent

from .artifact_store import ArtifactStore
from .prompting import PromptBuilderForWorkflow
from .schemas import RoleConfig, StructuredMessage
from .structured_output import ensure_fields, extract_json_object


class RoleRuntime:
    def __init__(
        self,
        role: RoleConfig,
        artifact_store: ArtifactStore,
        prompt_builder: PromptBuilderForWorkflow,
        schema_version: str,
    ):
        self.role = role
        self.artifact_store = artifact_store
        self.prompt_builder = prompt_builder
        self.schema_version = schema_version

    def execute(
        self,
        requirement: str,
        incoming_messages: list[StructuredMessage],
        fix_round: int,
        max_fix_rounds: int,
    ) -> list[StructuredMessage]:
        # 把上游消息拆成 prompt 需要的结构化上下文
        incoming_topics = [msg.topic for msg in incoming_messages]
        incoming_payloads = [msg.payload for msg in incoming_messages]
        incoming_artifact_refs = []
        for msg in incoming_messages:
            incoming_artifact_refs.extend(msg.artifact_refs)

        # 统一模板渲染，避免角色提示词拼接散落在各处
        prompt = self.prompt_builder.build_role_prompt(
            template_name=self.role.prompt_template,
            requirement=requirement,
            incoming_topics=incoming_topics,
            incoming_payloads=incoming_payloads,
            artifact_refs=incoming_artifact_refs,
            fix_round=fix_round,
            max_fix_rounds=max_fix_rounds,
        )

        # 复用现有 subagent 执行能力，角色类型由配置决定
        print(
            f"\033[90m[Workflow]\033[0m {self.role.name} running subagent(type={self.role.agent_type})...",
            flush=True,
        )
        raw_output = self._run_subagent_with_heartbeat(prompt)
        print(
            f"\033[90m[Workflow]\033[0m {self.role.name} subagent done (output_len={len(raw_output)})",
            flush=True,
        )

        # 解析 + 持久化 + 组装消息，形成标准输出链
        parsed = self._parse_output(raw_output)
        artifact_refs = self._persist_artifacts(parsed, raw_output)

        return self._build_messages(parsed, artifact_refs)

    def _parse_output(self, raw_output: str) -> dict:
        # 每个角色约束不同的关键字段，用于兜底补全
        required_fields = {
            "AnalystDesigner": [
                "summary", "objectives", "functional_requirements", "technical_design",
                "module_plan", "acceptance_criteria", "risks",
            ],
            "Engineer": [
                "implementation_summary", "changed_files", "entry_points", "run_commands",
                "assumptions", "known_risks",
            ],
            "Tester": [
                "verdict", "blocker_count", "passed_checks", "failed_checks", "test_commands", "defects", "summary",
            ],
        }
        # 先尝试提取 JSON，再补齐必需字段，避免下游因格式漂移崩溃
        extracted = extract_json_object(raw_output)
        return ensure_fields(extracted, required_fields.get(self.role.name, []), raw_output)

    def _persist_artifacts(self, parsed: dict, raw_output: str) -> list[str]:
        # 产物统一落盘，消息里只传引用路径
        refs = []
        role_dir = self.role.name.lower()

        md_path = self.role.output_artifacts.get("markdown")
        if md_path:
            md_content = self._format_markdown(parsed, raw_output)
            refs.append(self.artifact_store.save_text(md_path, md_content))

        json_path = self.role.output_artifacts.get("json")
        if json_path:
            refs.append(self.artifact_store.save_json(json_path, parsed))

        if not refs:
            # 如果配置未声明输出路径，给一个安全的兜底文件
            fallback = f"{role_dir}/output_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.md"
            refs.append(self.artifact_store.save_text(fallback, self._format_markdown(parsed, raw_output)))

        return refs

    def _build_messages(self, parsed: dict, artifact_refs: list[str]) -> list[StructuredMessage]:
        if self.role.name == "Tester":
            # Tester 的发布 topic 由 verdict/blocker_count 决定
            verdict = str(parsed.get("verdict", "fail")).strip().lower()
            blocker_count = int(parsed.get("blocker_count") or 0)
            is_passed = verdict == "pass" and blocker_count == 0
            topic = self.role.publish["on_pass"] if is_passed else self.role.publish["on_fail"]
        else:
            topic = self.role.publish.get("default", "workflow.step.done")

        return [
            StructuredMessage(
                message_id=f"msg-{uuid.uuid4().hex[:12]}",
                schema_version=self.schema_version,
                topic=topic,
                sent_from=self.role.name,
                send_to=[],
                cause_by=f"{self.role.name}.execute",
                payload=parsed,
                artifact_refs=artifact_refs,
                status="success",
            )
        ]

    @staticmethod
    def _format_markdown(parsed: dict, raw_output: str) -> str:
        return (
            "# Structured Output\n\n"
            f"```json\n{json.dumps(parsed, ensure_ascii=False, indent=2)}\n```\n\n"
            "# Raw Output\n\n"
            f"{raw_output}\n"
        )

    def _run_subagent_with_heartbeat(self, prompt: str) -> str:
        """同步执行 subagent，并在长耗时阶段输出心跳日志。"""
        result_holder: dict[str, str] = {}
        error_holder: dict[str, Exception] = {}
        latest_status = {"text": "starting"}
        status_lock = threading.Lock()

        def _on_status_update(status: str) -> None:
            clean = str(status or "working").replace("\n", " ").strip()
            if len(clean) > 80:
                clean = clean[:77] + "..."
            with status_lock:
                latest_status["text"] = clean or "working"

        def _target():
            try:
                result_holder["output"] = run_subagent(
                    prompt,
                    self.role.agent_type,
                    self.role.name,
                    status_callback=_on_status_update,
                )
            except Exception as exc:  # pragma: no cover - defensive branch
                error_holder["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()

        waited = 0
        heartbeat_seconds = 1
        while thread.is_alive():
            thread.join(timeout=heartbeat_seconds)
            if thread.is_alive():
                waited += heartbeat_seconds
                with status_lock:
                    status_text = latest_status["text"]
                print(
                    (
                        f"\r\033[90m[Workflow]\033[0m {self.role.name} working "
                        f"[{waited:>4}s] | {status_text}\033[K"
                    ),
                    end="",
                    flush=True,
                )

        if waited > 0:
            print("", flush=True)

        if "error" in error_holder:
            raise error_holder["error"]
        return result_holder.get("output", "")
