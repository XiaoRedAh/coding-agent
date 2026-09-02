from __future__ import annotations

from prompts.loader import PromptLoader, default_loader


class PromptBuilderForWorkflow:
    def __init__(self, loader: PromptLoader | None = None):
        # P1: 工作流模板纳入三级覆盖体系（内置 < 用户级 < 项目级）
        self.loader = loader or default_loader()

    def build_role_prompt(
        self,
        template_name: str,
        requirement: str,
        incoming_topics: list[str],
        incoming_payloads: list[dict],
        artifact_refs: list[str],
        fix_round: int,
        max_fix_rounds: int,
    ) -> str:
        template = self._load_template(template_name)
        variables = {
            "requirement": requirement,
            "incoming_topics": "\n".join(incoming_topics) if incoming_topics else "(none)",
            "incoming_payloads": self._to_json_like(incoming_payloads),
            "artifact_refs": "\n".join(artifact_refs) if artifact_refs else "(none)",
            "fix_round": str(fix_round),
            "max_fix_rounds": str(max_fix_rounds),
        }
        return self._render_known_placeholders(template, variables)

    def _load_template(self, template_name: str) -> str:
        return self.loader.load(f"workflow/{template_name}")

    @staticmethod
    def _to_json_like(payloads: list[dict]) -> str:
        lines = []
        for idx, payload in enumerate(payloads, start=1):
            lines.append(f"[{idx}] {payload}")
        return "\n".join(lines) if lines else "(none)"

    @staticmethod
    def _render_known_placeholders(template: str, variables: dict[str, str]) -> str:
        """仅替换约定占位符，避免 JSON 花括号被 str.format 误解析。"""
        rendered = template
        for key, value in variables.items():
            rendered = rendered.replace(f"{{{key}}}", value)
        return rendered
