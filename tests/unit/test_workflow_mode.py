"""Unit tests for MetaGPT-lite workflow mode."""

from types import SimpleNamespace

from workflows.event_bus import EventBus
from workflows.prompting import PromptBuilderForWorkflow
from workflows.structured_output import extract_json_object, ensure_fields
from workflows.schemas import StructuredMessage
from workflows.gateway import maybe_run_workflow


def _msg(topic: str, send_to: list[str] | None = None) -> StructuredMessage:
    return StructuredMessage(
        message_id="m1",
        schema_version="1.0",
        topic=topic,
        sent_from="tester",
        send_to=send_to or [],
        cause_by="unit-test",
        payload={"k": "v"},
    )


def test_event_bus_topic_routing():
    bus = EventBus()
    bus.subscribe("Engineer", ["analysis.done"])
    bus.subscribe("Tester", ["code.submitted"])

    bus.publish(_msg("analysis.done"))

    engineer_msgs = bus.consume("Engineer")
    tester_msgs = bus.consume("Tester")

    assert len(engineer_msgs) == 1
    assert engineer_msgs[0].topic == "analysis.done"
    assert tester_msgs == []


def test_event_bus_send_to_filter():
    bus = EventBus()
    bus.subscribe("Engineer", ["test.failed"])
    bus.subscribe("Tester", ["test.failed"])

    bus.publish(_msg("test.failed", send_to=["Engineer"]))

    engineer_msgs = bus.consume("Engineer")
    tester_msgs = bus.consume("Tester")

    assert len(engineer_msgs) == 1
    assert tester_msgs == []


def test_structured_output_json_extraction_and_fill():
    text = """
hello
```json
{"verdict": "pass", "blocker_count": 0}
```
"""
    parsed = extract_json_object(text)
    out = ensure_fields(parsed, ["verdict", "blocker_count", "failed_checks"], text)

    assert out["verdict"] == "pass"
    assert out["blocker_count"] == 0
    assert out["failed_checks"] == []
    assert "raw_output" in out


def test_gateway_non_workflow_message_is_ignored():
    handled, reply = maybe_run_workflow([{"role": "user", "content": "hello"}])
    assert handled is False
    assert reply == ""


def test_gateway_command_triggers_engine(monkeypatch):
    fake_result = SimpleNamespace(
        workflow_id="metagpt-lite-3role",
        status=SimpleNamespace(value="passed"),
        terminal_topic="test.passed",
        summary="ok",
        generated_artifacts=["artifacts/analysis/analysis_design.md"],
    )

    class DummyEngine:
        def run(self, requirement: str, workflow_id: str):
            assert requirement == "build feature x"
            assert workflow_id == "metagpt-lite-3role"
            return fake_result

    monkeypatch.setattr("workflows.gateway.WorkflowEngine", DummyEngine)

    handled, reply = maybe_run_workflow([
        {"role": "user", "content": "/workflow metagpt-lite-3role build feature x"}
    ])

    assert handled is True
    assert "status=passed" in reply
    assert "artifacts/analysis/analysis_design.md" in reply


def test_prompt_builder_handles_json_braces_in_template():
    builder = PromptBuilderForWorkflow()

    prompt = builder.build_role_prompt(
        template_name="analyst.md",
        requirement="实现二分查找",
        incoming_topics=["user.requirement"],
        incoming_payloads=[{"requirement": "实现二分查找"}],
        artifact_refs=[],
        fix_round=0,
        max_fix_rounds=3,
    )

    assert "实现二分查找" in prompt
    assert '"summary"' in prompt
    assert "{requirement}" not in prompt
    assert "{incoming_payloads}" not in prompt
    assert "实现二分查找" in prompt
