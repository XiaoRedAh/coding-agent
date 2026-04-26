"""Workflow mode package for MetaGPT-lite multi-agent collaboration."""

from .engine import WorkflowEngine, WorkflowRunResult
from .gateway import maybe_run_workflow

__all__ = ["WorkflowEngine", "WorkflowRunResult", "maybe_run_workflow"]
