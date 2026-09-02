from __future__ import annotations

import json
import threading
import time
import uuid
from datetime import datetime, timezone

from agents.subagent import run_subagent
from runtime import state as _state

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
        artifact_refs = self._persist_artifacts(parsed, raw_output, fix_round)

        return self._build_messages(parsed, artifact_refs)

    def _parse_output(self, raw_output: str) -> dict:
        """解析子 Agent 输出为结构化数据。

        稳定性设计（模式 C 时好时坏的主修复点）：
        1. JSON 提取失败 → 一次"重格式化"重试（小 LLM 调用），
           而不是静默兜底成空字段（旧逻辑会把格式失误当成测试失败，
           触发无效 fix 循环）
        2. 解析出的数字字段做安全转换（blocker_count 可能是 "两个"）
        """
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
        extracted = extract_json_object(raw_output)
        if extracted is None:
            print(
                f"\033[33m[Workflow]\033[0m {self.role.name}: JSON not found in output, reformatting...",
                flush=True,
            )
            extracted = self._reformat_retry(raw_output, required_fields.get(self.role.name, []))
        parsed = ensure_fields(extracted, required_fields.get(self.role.name, []), raw_output)

        # 数字字段安全转换
        if "blocker_count" in parsed:
            parsed["blocker_count"] = _safe_int(parsed.get("blocker_count"))
        return parsed

    def _reformat_retry(self, raw_output: str, required_fields: list[str]) -> dict | None:
        """一次重格式化重试：让 LLM 把原始输出转成合法 JSON。

        失败则返回 None（走 ensure_fields 兜底，保持旧行为）。
        用小代价（一次额外调用）避免格式失误被误判为业务失败。
        """
        schema_hint = json.dumps(
            {f: "..." for f in required_fields}, ensure_ascii=False)
        try:
            resp = _state.llm.chat(
                system=(
                    "You convert agent output to strict JSON. "
                    "Respond with ONLY the JSON object, no prose, no code fences."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Convert the following output to a JSON object with these "
                        f"top-level fields: {schema_hint}\n"
                        f"Preserve the original information as-is. "
                        f"If a field is not present in the output, omit it.\n\n"
                        f"Output to convert:\n{raw_output}"
                    ),
                }],
                max_tokens=4096,
            )
            text = ""
            for b in (resp.content or []):
                t = getattr(b, "text", None)
                if isinstance(t, str):
                    text += t
            return extract_json_object(text)
        except Exception as e:
            print(f"\033[33m[Workflow]\033[0m reformat retry failed: {e}", flush=True)
            return None

    def _persist_artifacts(self, parsed: dict, raw_output: str, fix_round: int = 0) -> list[str]:
        """产物统一落盘，消息里只传引用路径。

        fix_round > 0 时文件名带轮次后缀（r1/r2/...），
        保留每轮产物供排障对比，避免修复循环覆盖历史。
        """
        refs = []
        role_dir = self.role.name.lower()
        suffix = f".r{fix_round}" if fix_round > 0 else ""

        md_path = self.role.output_artifacts.get("markdown")
        if md_path:
            md_content = self._format_markdown(parsed, raw_output)
            refs.append(self.artifact_store.save_text(self._with_suffix(md_path, suffix), md_content))

        json_path = self.role.output_artifacts.get("json")
        if json_path:
            refs.append(self.artifact_store.save_json(self._with_suffix(json_path, suffix), parsed))

        if not refs:
            # 如果配置未声明输出路径，给一个安全的兜底文件
            fallback = f"{role_dir}/output_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
            refs.append(self.artifact_store.save_text(fallback, self._format_markdown(parsed, raw_output)))

        return refs

    @staticmethod
    def _with_suffix(path: str, suffix: str) -> str:
        """给路径加后缀（保持在扩展名之前）：a/b.md + .r1 → a/b.r1.md"""
        if not suffix:
            return path
        dot = path.rfind(".")
        if dot > path.rfind("/"):
            return path[:dot] + suffix + path[dot:]
        return path + suffix

    def _build_messages(self, parsed: dict, artifact_refs: list[str]) -> list[StructuredMessage]:
        if self.role.name == "Tester":
            # Tester 的发布 topic 由 verdict/blocker_count 决定
            verdict = str(parsed.get("verdict", "")).strip().lower()
            blocker_count = _safe_int(parsed.get("blocker_count"))
            is_passed = verdict == "pass" and blocker_count == 0
            # verdict 缺失/非法视为解析失败，明确标记（不再默认 fail）
            if verdict not in ("pass", "fail"):
                print(
                    f"\033[33m[Workflow]\033[0m Tester verdict invalid: {verdict!r}, treating as fail",
                    flush=True,
                )
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
        """同步执行 subagent，并在长耗时阶段输出心跳日志。

        使用中性的 workflow 系统提示词覆盖 agent 自身的提示词：
        内置 agent（如 verification）的提示词自带输出格式指令
        （"Return a structured report: 1. ... 4."），会与角色模板的
        "Return ONLY ONE JSON object" 冲突，导致输出格式不稳定。
        中性提示词只声明角色定位与硬约束，输出格式完全由角色模板决定。
        """
        workflow_system_prompt = (
            f"You are the {self.role.name} role in a strict SOP workflow. "
            f"Follow the instructions in the task message exactly, including "
            f"output format requirements. When the task asks for a JSON object, "
            f"output ONLY that JSON object with no surrounding prose. "
            f"Stay within your role's scope."
        )
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
                    system_prompt_override=workflow_system_prompt,
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


def _safe_int(value) -> int:
    """安全整数转换：None/空/非数字 → 0（防御 LLM 输出 '两个' 之类）。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
