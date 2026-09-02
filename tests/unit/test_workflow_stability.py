"""多 Agent / 压缩稳定性修复的测试。

覆盖：
  A. Workflow 稳定性：中性提示词覆盖、解析失败重试、安全数字转换、
     产物分版本、engine 角色崩溃兜底
  B. 委托指导：base.md 含 agent 工具使用时机
  C. run_workflow 工具注册
  D. 压缩修复：CJK token 估算、压缩后文件恢复、L2 保留文件最新读取
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import runtime.state as st


# ──────────────────────────────────────────────
#  A. Workflow 稳定性
# ──────────────────────────────────────────────

class TestWorkflowStability:
    def _make_role_runtime(self, tmp_path, monkeypatch):
        from workflows.role_runtime import RoleRuntime
        from workflows.artifact_store import ArtifactStore
        from workflows.prompting import PromptBuilderForWorkflow
        from workflows.schemas import RoleConfig

        monkeypatch.chdir(tmp_path)
        role = RoleConfig(
            name="Tester",
            description="test",
            agent_type="verification",
            subscriptions=["code.submitted"],
            prompt_template="tester.md",
            output_artifacts={
                "markdown": "test/test_report.md",
                "json": "test/test_report.json",
            },
            publish={"on_pass": "test.passed", "on_fail": "test.failed"},
        )
        store = ArtifactStore()
        builder = PromptBuilderForWorkflow()
        return RoleRuntime(role, store, builder, "1.0")

    def test_neutral_system_prompt_passed_to_subagent(self, tmp_path, monkeypatch):
        """【病灶1修复】workflow 角色用中性提示词覆盖内置 agent 提示词，
        消除 verification 的 prose 报告指令与角色模板 JSON 指令的冲突。"""
        runtime = self._make_role_runtime(tmp_path, monkeypatch)
        captured = {}

        def fake_run_subagent(prompt, agent_type, description="",
                              status_callback=None, system_prompt_override=None):
            captured["override"] = system_prompt_override
            captured["type"] = agent_type
            return '{"verdict": "pass", "blocker_count": 0, "summary": "ok"}'

        with patch("workflows.role_runtime.run_subagent", fake_run_subagent):
            runtime.execute("do something", [], 0, 3)

        assert captured["type"] == "verification"  # 工具白名单仍由 agent_type 决定
        assert captured["override"] is not None
        assert "Tester" in captured["override"]
        # 中性提示词本身不含输出格式指令（格式由角色模板决定）
        assert "structured report" not in captured["override"].lower()

    def test_parse_failure_triggers_reformat_retry(self, tmp_path, monkeypatch):
        """【病灶2修复】JSON 提取失败 → 一次重格式化重试，而非静默判 fail。"""
        runtime = self._make_role_runtime(tmp_path, monkeypatch)

        with patch("workflows.role_runtime.run_subagent",
                   lambda *a, **k: "The tests all passed fine. No blockers found."):
            # 重格式化重试成功返回 JSON
            fake_resp = SimpleNamespace(content=[
                SimpleNamespace(text='{"verdict": "pass", "blocker_count": 0}')])
            with patch.object(st, "llm") as fake_llm:
                fake_llm.chat.return_value = fake_resp
                msgs = runtime.execute("req", [], 0, 3)

        assert msgs[0].topic == "test.passed"  # 重试成功 → 真实 verdict 生效

    def test_reformat_retry_failure_falls_back(self, tmp_path, monkeypatch):
        """重试也失败时保持兜底行为（空 verdict → fail），但流程不崩。"""
        runtime = self._make_role_runtime(tmp_path, monkeypatch)

        with patch("workflows.role_runtime.run_subagent",
                   lambda *a, **k: "no json here at all"):
            with patch.object(st, "llm") as fake_llm:
                fake_llm.chat.side_effect = Exception("llm down")
                msgs = runtime.execute("req", [], 0, 3)

        assert msgs[0].topic == "test.failed"  # 兜底不崩，走 fail 分支

    def test_blocker_count_safe_int(self, tmp_path, monkeypatch):
        """blocker_count 是非数字（如 '两个'）时不抛异常。"""
        runtime = self._make_role_runtime(tmp_path, monkeypatch)

        with patch("workflows.role_runtime.run_subagent",
                   lambda *a, **k: '{"verdict": "fail", "blocker_count": "两个"}'):
            msgs = runtime.execute("req", [], 0, 3)

        assert msgs[0].payload["blocker_count"] == 0

    def test_artifacts_versioned_by_fix_round(self, tmp_path, monkeypatch):
        """fix_round > 0 时产物带轮次后缀，修复循环不覆盖历史。"""
        runtime = self._make_role_runtime(tmp_path, monkeypatch)

        with patch("workflows.role_runtime.run_subagent",
                   lambda *a, **k: '{"verdict": "fail", "blocker_count": 1}'):
            msgs_r0 = runtime.execute("req", [], 0, 3)
            msgs_r1 = runtime.execute("req", [], 1, 3)

        assert any("test_report.md" in r and ".r" not in r for r in msgs_r0[0].artifact_refs)
        assert any("test_report.r1.md" in r for r in msgs_r1[0].artifact_refs)

    def test_engine_role_crash_handled(self, tmp_path, monkeypatch):
        """【病灶4修复】单个角色崩溃 → workflow.failed 终态，不向上炸。"""
        from workflows.engine import WorkflowEngine
        from workflows.role_runtime import RoleRuntime

        monkeypatch.chdir(tmp_path)
        engine = WorkflowEngine()

        def crashing_execute(self, *args, **kwargs):
            raise ValueError("subagent exploded")

        with patch.object(RoleRuntime, "execute", crashing_execute):
            result = engine.run("some requirement")

        assert result.status.value == "failed"
        assert "crashed" in result.summary or "Tester" in result.summary


# ──────────────────────────────────────────────
#  B. 委托指导注入
# ──────────────────────────────────────────────

class TestDelegationGuidance:
    def test_base_md_contains_delegation_section(self):
        """base.md 必须包含 agent 工具的委托时机 + 执行机制指导。"""
        from prompts.loader import PromptLoader
        base = PromptLoader(user_dir=Path("nonexistent_user_dir_xyz")).load("base.md")
        assert "Delegation" in base
        assert "Multi-directional research" in base
        assert "Bulk independent tasks" in base
        assert "Verification after changes" in base
        # 执行机制说明（同步=依赖安全顺序执行 / 后台=真并行）
        assert "Choosing the execution mode" in base
        assert "run sequentially, in order" in base
        assert "run_in_background" in base
        assert "order dependencies MUST use synchronous" in base
        assert "run_workflow" in base  # SOP 工具化指引

    def test_system_prompt_injects_delegation(self, tmp_workdir, monkeypatch):
        """委托指导进入 system prompt 静态区（可被 prompt cache）。"""
        from context.prompt import build_system_prompt

        monkeypatch.setattr(st, "memory", None)
        monkeypatch.setattr(st, "skills", None)
        blocks = build_system_prompt()
        assert "Delegation" in blocks[0]["text"]


# ──────────────────────────────────────────────
#  C. run_workflow 工具注册
# ──────────────────────────────────────────────

class TestWorkflowTool:
    def test_tool_registered(self):
        from tools import get_all_definitions, get_all_handlers

        names = [d["name"] for d in get_all_definitions()]
        assert "run_workflow" in names
        assert "run_workflow" in get_all_handlers()

    def test_empty_requirement_rejected(self):
        from tools.WorkflowTool import handle
        from engine.results import ToolResult

        result = handle("   ")
        assert isinstance(result, ToolResult)
        assert result.ok is False


# ──────────────────────────────────────────────
#  D. 压缩修复
# ──────────────────────────────────────────────

class TestCJKTokenEstimation:
    def test_cjk_estimated_higher_than_ascii(self):
        """同样字符数，中文的 token 估算应显著高于英文（旧系数低估 2 倍）。"""
        from context.compact import _estimate_tokens

        ascii_text = "a" * 300
        cjk_text = "中" * 300
        assert _estimate_tokens(cjk_text) > _estimate_tokens(ascii_text) * 1.5

    def test_ascii_backward_compatible(self):
        """纯 ASCII 保持 ~3 字符/token 的历史行为。"""
        from context.compact import _estimate_tokens

        assert _estimate_tokens("a" * 300) == 100

    def test_tracker_cjk_message(self):
        """中文消息计入更高的估算 token。"""
        from context.compact import TokenTracker

        t = TokenTracker()
        t.track_new_message({"role": "user", "content": "中" * 300})
        est_ascii_equivalent = 300 // 3
        assert t.estimate_current_tokens() > est_ascii_equivalent


class TestPostCompactRestore:
    def test_recent_files_restored(self, tmp_path, monkeypatch):
        """L5 压缩后恢复最近读取的文件内容。"""
        from context.compact import _collect_recent_files, _restore_recent_files

        # 两个真实文件
        f1 = tmp_path / "a.py"
        f1.write_text("print('a')", encoding="utf-8")
        f2 = tmp_path / "b.py"
        f2.write_text("print('b')", encoding="utf-8")

        messages = [
            {"role": "assistant", "content": [
                SimpleNamespace(type="tool_use", name="read_file",
                                input={"file_path": str(f1)})]},
            {"role": "user", "content": [{}]},
            {"role": "assistant", "content": [
                SimpleNamespace(type="tool_use", name="read_file",
                                input={"file_path": str(f2)})]},
        ]
        paths = _collect_recent_files(messages, 5)
        assert str(f1) in paths and str(f2) in paths

        new_messages = [
            {"role": "user", "content": "summary"},
            {"role": "assistant", "content": "ack"},
        ]
        restored = _restore_recent_files(messages, new_messages)
        assert restored == 2
        # 插在摘要之后、ack 之前
        assert "summary" in new_messages[0]["content"]
        assert "print('a')" in new_messages[1]["content"]
        assert "ack" in new_messages[2]["content"]

    def test_missing_files_skipped(self, tmp_path):
        """文件已删除时不崩，恢复 0 个。"""
        from context.compact import _restore_recent_files

        messages = [
            {"role": "assistant", "content": [
                SimpleNamespace(type="tool_use", name="read_file",
                                input={"file_path": str(tmp_path / "gone.py")})]},
        ]
        new_messages = [
            {"role": "user", "content": "summary"},
            {"role": "assistant", "content": "ack"},
        ]
        assert _restore_recent_files(messages, new_messages) == 0
        assert len(new_messages) == 2  # 未插入恢复消息

    def test_auto_compact_tracks_new_messages(self, tmp_path, monkeypatch):
        """auto_compact 重建后登记新消息到 tracker（重估利用率）。"""
        from context.compact import TokenTracker, auto_compact
        from context import compact as compact_mod

        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(compact_mod, "TRANSCRIPT_DIR", tmp_path / "transcripts")

        f1 = tmp_path / "a.py"
        f1.write_text("x = 1", encoding="utf-8")
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": [
                SimpleNamespace(type="tool_use", name="read_file",
                                input={"file_path": str(f1)})]},
            {"role": "user", "content": [SimpleNamespace()]},
            {"role": "assistant", "content": "done work"},
            {"role": "user", "content": "next"},
        ]
        fake_resp = SimpleNamespace(content=[
            SimpleNamespace(text="<summary>compressed</summary>")])
        tracker = TokenTracker()
        with patch.object(st, "llm") as fake_llm:
            fake_llm.chat.return_value = fake_resp
            result = auto_compact(messages, tracker)

        assert tracker.messages_since_anchor == len(result)
        assert tracker.estimate_current_tokens() > 0


class TestSnipKeepsLatestRead:
    def test_latest_read_per_file_kept(self):
        """同文件多次读取：最新一次保留（即使超出最近 N 窗口）。"""
        from context.compact import snip_stale_results

        msgs = []
        # f0 读两次（旧+新），再读 f1..f5（拉开与最近窗口的距离）
        reads = ["f0.py", "f0.py"] + [f"f{i}.py" for i in range(1, 6)]
        for i, fpath in enumerate(reads):
            msgs.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "read_file",
                 "input": {"file_path": fpath}}]})
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i}",
                 "content": f"content {fpath} " * 30}]})

        snip_stale_results(msgs, 0.65)

        # t1（f0.py 的最新读取）应保留原文；t0（f0.py 旧读取）应被 snip
        def result_content(tid):
            for m in msgs:
                if m["role"] == "user":
                    for b in m["content"]:
                        if isinstance(b, dict) and b.get("tool_use_id") == tid:
                            return b["content"]
            return None

        assert result_content("t0").startswith("[Content snipped")
        assert not result_content("t1").startswith("[Content snipped")
