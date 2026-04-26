from __future__ import annotations

import json
from pathlib import Path

from bootstrap import state as st
from agents.custom_registry import load_custom_role_configs
from .schemas import RoleConfig, WorkflowConfig

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


class WorkflowLoader:
    def __init__(self):
        # 用户自定义配置目录（工作区 .xiaoagent 下）
        self.custom_pipeline_dir = st.PROJECT_DIR / "workflows" / "pipelines"
        self.custom_role_dir = st.PROJECT_DIR / "workflows" / "roles"

        # 内置默认配置目录（随代码发布）
        self.default_pipeline_dir = Path(__file__).parent / "defaults"

    def load(self, workflow_id: str = "metagpt-lite-3role") -> WorkflowConfig:
        # 先加载 pipeline，再叠加用户角色覆盖
        data = self._load_pipeline_data(workflow_id)
        self._merge_custom_roles(data)

        roles = [
            RoleConfig(
                name=role["name"],
                description=role.get("description", ""),
                agent_type=role.get("agent_type", "general"),
                subscriptions=role.get("subscriptions", []),
                prompt_template=role["prompt_template"],
                output_artifacts=role.get("output_artifacts", {}),
                publish=role.get("publish", {}),
            )
            for role in data["roles"]
        ]

        return WorkflowConfig(
            workflow_id=data.get("workflow_id", workflow_id),
            name=data.get("name", workflow_id),
            schema_version=data.get("schema_version", "1.0"),
            roles=roles,
            max_steps=int(data.get("max_steps", 20)),
            max_fix_rounds=int(data.get("max_fix_rounds", 3)),
            terminal_topics=data.get("terminal_topics", ["test.passed", "workflow.escalated", "workflow.failed"]),
        )

    def _load_pipeline_data(self, workflow_id: str) -> dict:
        # 加载优先级：自定义 > 内置默认
        candidates = [
            self.custom_pipeline_dir / f"{workflow_id}.yaml",
            self.custom_pipeline_dir / f"{workflow_id}.yml",
            self.custom_pipeline_dir / f"{workflow_id}.json",
            self.default_pipeline_dir / f"{workflow_id}.yaml",
            self.default_pipeline_dir / f"{workflow_id}.yml",
            self.default_pipeline_dir / f"{workflow_id}.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                return self._load_data_file(candidate)
        raise FileNotFoundError(f"Workflow config not found: {workflow_id}")

    def _load_data_file(self, path: Path) -> dict:
        # 同时支持 json/yaml，便于不同团队习惯
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".json":
            return json.loads(text)
        if yaml is None:
            raise RuntimeError("PyYAML is required for .yaml workflow files. Please install pyyaml.")
        return yaml.safe_load(text)

    def _merge_custom_roles(self, pipeline_data: dict) -> None:
        # 以 role.name 为 key 合并，用户配置覆盖默认配置
        role_map = {role["name"]: role for role in pipeline_data.get("roles", [])}
        for role_name, role_data in load_custom_role_configs().items():
            role_map[role_name] = {**role_map.get(role_name, {}), **role_data}

        pipeline_data["roles"] = list(role_map.values())
