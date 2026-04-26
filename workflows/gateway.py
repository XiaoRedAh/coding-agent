from __future__ import annotations

import os
import time

from .engine import WorkflowEngine


def maybe_run_workflow(messages: list[dict]) -> tuple[bool, str]:
    """判断当前轮是否进入 workflow 模式。

    触发方式：
    1. 显式命令：/workflow [workflow_id] <requirement>
    2. 环境开关：SOP_MODE=1（把普通用户输入作为 requirement）
    """
    if not messages:
        return False, ""

    last = messages[-1]
    if last.get("role") != "user":
        return False, ""

    content = last.get("content")
    if not isinstance(content, str):
        return False, ""

    workflow_id = "metagpt-lite-3role"
    requirement = ""
    text = content.strip()

    if text.startswith("/workflow"):
        # 支持两种写法：
        # /workflow <requirement>
        # /workflow <workflow_id> <requirement>
        parts = text.split(maxsplit=2)
        if len(parts) == 1:
            return True, "Usage: /workflow [workflow_id] <requirement>"
        if len(parts) == 2:
            requirement = parts[1]
        else:
            # Heuristic: treat token-1 as workflow id only when it looks like an id.
            if parts[1].startswith("metagpt-"):
                workflow_id = parts[1]
                requirement = parts[2]
            else:
                requirement = text[len("/workflow"):].strip()
    elif os.getenv("SOP_MODE", "").lower() in {"1", "true"}:
        requirement = text
    else:
        return False, ""

    requirement = requirement.strip()
    if not requirement:
        return True, "Workflow requirement cannot be empty."

    # 进入 workflow 引擎执行单次 SOP 流程
    print(f"\033[36m[Workflow]\033[0m start id={workflow_id}", flush=True)
    print(f"\033[36m[Workflow]\033[0m requirement: {requirement[:120]}", flush=True)
    started_at = time.time()
    engine = WorkflowEngine()
    result = engine.run(requirement=requirement, workflow_id=workflow_id)
    elapsed = time.time() - started_at
    print(f"\033[36m[Workflow]\033[0m finished in {elapsed:.1f}s", flush=True)

    lines = [
        f"[Workflow] id={result.workflow_id}",
        f"[Workflow] status={result.status.value}, terminal_topic={result.terminal_topic}",
        f"[Workflow] summary={result.summary}",
    ]
    if result.generated_artifacts:
        lines.append("[Workflow] artifacts:")
        lines.extend([f"- {path}" for path in result.generated_artifacts])

    # 返回给主 agent 展示；主会话不会退出
    return True, "\n".join(lines)
