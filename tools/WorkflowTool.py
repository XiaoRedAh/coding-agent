"""
tools/WorkflowTool.py - SOP 工作流工具

让主 Agent 自主决定何时启用 SOP 工作流（分析→实现→测试的
结构化管线），而不是依赖用户预先设置 SOP_MODE=1 或 /workflow 命令。

多 agent 编排的"无模式预选"方向：LLM 判断任务适合 SOP 管线时
直接调用本工具，与 agent 工具（自主委托）同构。
"""

from engine.results import ToolResult

DEFINITION = {
    "name": "run_workflow",
    "description": (
        "Run a structured SOP workflow (Analyst -> Engineer -> Tester) for a "
        "development requirement. The workflow runs analysis, implementation, "
        "and adversarial testing in sequence with automatic fix loops, and "
        "persists per-stage artifacts. Use this for substantial, well-scoped "
        "development tasks that benefit from a strict analyze-implement-test "
        "pipeline. NOT for quick questions or small edits — handle those "
        "yourself."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "requirement": {
                "type": "string",
                "description": (
                    "Self-contained requirement description: what to build/change, "
                    "relevant file paths, and constraints."
                ),
            },
            "workflow_id": {
                "type": "string",
                "description": "Optional workflow id (default: metagpt-lite-3role).",
            },
        },
        "required": ["requirement"],
    },
}


def handle(requirement: str, workflow_id: str = "metagpt-lite-3role") -> str:
    """执行 SOP 工作流并返回结果摘要。"""
    if not requirement or not requirement.strip():
        return ToolResult.failure("requirement cannot be empty", "invalid_input")

    from workflows.engine import WorkflowEngine

    try:
        engine = WorkflowEngine()
        result = engine.run(
            requirement=requirement.strip(),
            workflow_id=workflow_id or "metagpt-lite-3role",
        )
    except Exception as e:
        return ToolResult.failure(f"Workflow failed: {e}", "workflow_error")

    lines = [
        f"Workflow {result.workflow_id} finished: {result.status.value}",
        f"Summary: {result.summary}",
    ]
    if result.generated_artifacts:
        lines.append("Artifacts:")
        lines.extend(f"- {p}" for p in result.generated_artifacts)
    # 返回给主 Agent 的是结构化摘要；主 Agent 据此向用户汇报或继续处理
    return ToolResult("\n".join(lines))
