from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class WorkflowStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ESCALATED = "escalated"
    STOPPED = "stopped"


@dataclass(slots=True)
class StructuredMessage:
    message_id: str
    schema_version: str
    topic: str
    sent_from: str
    send_to: list[str]
    cause_by: str
    payload: dict[str, Any]
    artifact_refs: list[str] = field(default_factory=list)
    status: str = "success"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat(timespec="seconds") + "Z")


@dataclass(slots=True)
class RoleConfig:
    name: str
    description: str
    agent_type: str
    subscriptions: list[str]
    prompt_template: str
    output_artifacts: dict[str, str]
    publish: dict[str, str]


@dataclass(slots=True)
class WorkflowConfig:
    workflow_id: str
    name: str
    schema_version: str
    roles: list[RoleConfig]
    max_steps: int = 20
    max_fix_rounds: int = 3
    terminal_topics: list[str] = field(default_factory=lambda: ["test.passed", "workflow.escalated", "workflow.failed"])


@dataclass(slots=True)
class WorkflowRunResult:
    status: WorkflowStatus
    workflow_id: str
    requirement: str
    summary: str
    terminal_topic: str
    generated_artifacts: list[str]
    event_log: list[StructuredMessage]
