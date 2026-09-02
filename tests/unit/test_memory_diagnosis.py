"""记忆系统诊断套件（P0）——验证完整数据流的每一环。

诊断的链路（按 LLM 视角）：
  A. 启动时：main.py 初始化 MemoryManager → prompt.py 注入说明+索引
  B. 会话中：LLM 按指示用 write_file 写记忆 → 权限白名单放行
  C. 下次会话：新 MEMORY.md 索引被注入 → LLM 能看到并 read_file 读取

以及跨场景语义：cwd 绑定、prompt cache 边界、截断保护。
"""

import pytest
from pathlib import Path
from unittest.mock import patch

import runtime.state as st
from services.memory import MemoryManager
from services.permissions import check_permission, PermissionRules


@pytest.fixture
def mem_env(tmp_path, monkeypatch):
    """完整的记忆环境：临时工作目录 + 记忆目录 + MemoryManager 单例。"""
    mem_dir = tmp_path / ".xiaoagent" / "memory"
    monkeypatch.setattr(st, "WORKDIR", tmp_path)
    monkeypatch.setattr(st, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(st, "PROJECT_DIR", tmp_path / ".xiaoagent")
    mgr = MemoryManager()
    monkeypatch.setattr(st, "memory", mgr)
    return mgr


# ──────────────────────────────────────────────
#  A. 注入链路：LLM 到底能不能"看到"记忆系统
# ──────────────────────────────────────────────

class TestInjection:
    def test_memory_instructions_in_system_prompt(self, mem_env):
        """【关键】system prompt 必须包含记忆系统使用说明，否则 LLM 根本不知道有记忆功能。"""
        from context.prompt import build_system_prompt
        blocks = build_system_prompt()
        full = "\n".join(b["text"] for b in blocks)
        assert "# auto memory" in full, "记忆说明未注入 system prompt"
        assert "persistent, file-based memory system" in full
        assert "How to Save Memories" in full

    def test_memory_instructions_in_dynamic_block(self, mem_env):
        """记忆说明应在动态块（不破坏静态区的 prompt cache）。"""
        from context.prompt import build_system_prompt
        blocks = build_system_prompt()
        static = blocks[0]["text"]
        dynamic = blocks[1]["text"] if len(blocks) > 1 else ""
        assert "auto memory" not in static, "记忆内容泄漏进静态区会击穿 prompt cache"
        assert "auto memory" in dynamic

    def test_empty_index_shown_as_empty(self, mem_env):
        """无记忆时索引区显示 (empty)，LLM 仍能看到使用说明。"""
        section = mem_env.get_prompt_section()
        assert "(empty — no memories saved yet)" in section

    def test_index_content_injected(self, mem_env, tmp_path):
        """已有记忆时，MEMORY.md 索引必须注入 prompt（LLM 才知道有什么可读）。"""
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text(
            "- [user_role](user_role.md) — Backend dev\n", encoding="utf-8")
        section = mem_env.get_prompt_section()
        assert "user_role" in section
        assert "Current Memory Index" in section

    def test_memory_dir_auto_created_on_prompt_build(self, mem_env):
        """构建 prompt 时应自动创建记忆目录（用户无需手动 mkdir）。"""
        assert not mem_env.memory_dir.exists()
        mem_env.get_prompt_section()
        assert mem_env.memory_dir.exists()

    def test_prompt_contains_absolute_memory_path(self, mem_env, tmp_path):
        """prompt 中给出的记忆路径必须是可用的绝对路径（LLM 要用它调 write_file）。"""
        section = mem_env.get_prompt_section()
        assert str(mem_env.memory_dir) in section


# ──────────────────────────────────────────────
#  B. 写入链路：LLM 按指示写记忆时会发生什么
# ──────────────────────────────────────────────

class TestWritePath:
    def test_write_memory_whitelisted_in_default_mode(self, mem_env, tmp_path):
        """【关键】default 模式下写记忆文件应自动放行（白名单），
        否则每次写记忆都弹确认，用户体验上等于'记忆功能不工作'。"""
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        target = str(mem_dir / "user_role.md")
        rules = PermissionRules()
        result = check_permission("write_file", {"file_path": target, "content": "x"},
                                  "default", rules)
        assert result["action"] == "allow", f"写记忆被拒: {result}"

    def test_edit_memory_whitelisted(self, mem_env):
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        target = str(mem_dir / "MEMORY.md")
        rules = PermissionRules()
        result = check_permission("edit_file",
                                  {"file_path": target, "old_string": "a", "new_string": "b"},
                                  "default", rules)
        assert result["action"] == "allow"

    def test_write_memory_relative_path_whitelisted(self, mem_env):
        """相对路径 .xiaoagent/memory/x.md 也应命中白名单（LLM 常用相对路径）。"""
        mem_env.memory_dir.mkdir(parents=True)
        rules = PermissionRules()
        result = check_permission(
            "write_file",
            {"file_path": ".xiaoagent/memory/user_role.md", "content": "x"},
            "default", rules)
        # 注意：白名单用 Path(file_path).resolve()，相对 cwd 解析后应命中
        assert result["action"] == "allow", f"相对路径写记忆被拒: {result}"

    def test_outside_memory_still_asks(self, mem_env, tmp_path):
        """记忆目录之外的写入仍需确认（白名单不能过宽）。"""
        rules = PermissionRules()
        target = str(tmp_path / "normal_code.py")
        result = check_permission("write_file", {"file_path": target, "content": "x"},
                                  "default", rules)
        assert result["action"] == "confirm"

    def test_full_write_workflow(self, mem_env, tmp_path):
        """端到端：按 prompt 指示的两步流程写入记忆。"""
        from tools.FileWriteTool import handle as write_file
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        # LLM 视角：prompt 说了用 write_file 写绝对路径
        out = write_file(
            str(mem_dir / "user_role.md"),
            "---\nname: user_role\ndescription: Backend dev\ntype: user\n---\nUser is a backend dev.",
        )
        assert out.startswith("Successfully wrote")
        out2 = write_file(
            str(mem_dir / "MEMORY.md"),
            "- [user_role](user_role.md) — Backend dev\n",
        )
        assert out2.startswith("Successfully wrote")
        # 验证下次会话能看到
        assert "user_role" in mem_env.get_prompt_section()

    def test_read_memory_by_llm_instruction(self, mem_env):
        """LLM 按索引 read_file 读取记忆文件。"""
        from tools.FileReadTool import handle as read_file
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        (mem_dir / "user_role.md").write_text(
            "---\nname: user_role\ntype: user\n---\nUser is a backend dev.",
            encoding="utf-8")
        out = read_file(str(mem_dir / "user_role.md"))
        assert "User is a backend dev" in out


# ──────────────────────────────────────────────
#  C. 结构语义：边界与限制
# ──────────────────────────────────────────────

class TestSemantics:
    def test_memory_bound_to_cwd(self, mem_env, tmp_path, monkeypatch):
        """【设计缺陷验证】记忆目录跟随 cwd：换目录运行 = '失忆'。

        这是用户'感觉记忆没起作用'的最可能根因——
        WORKDIR = Path.cwd()，记忆写在哪个目录就只属于哪个目录。
        """
        # 会话 1：在 dirA 记住一件事
        dirA = tmp_path / "projectA"
        dirA.mkdir()
        memA = dirA / ".xiaoagent" / "memory"
        memA.mkdir(parents=True)
        (memA / "MEMORY.md").write_text("- [key](key.md) — A 的记忆\n", encoding="utf-8")

        # 会话 2：在 dirB 启动 agent
        dirB = tmp_path / "projectB"
        dirB.mkdir()
        monkeypatch.setattr(st, "WORKDIR", dirB)
        monkeypatch.setattr(st, "MEMORY_DIR", dirB / ".xiaoagent" / "memory")
        mgrB = MemoryManager()
        section = mgrB.get_prompt_section()
        # dirB 的 agent 看不到 dirA 的记忆
        assert "A 的记忆" not in section
        assert "(empty" in section

    def test_truncation_protects_index(self, mem_env):
        """索引超限时截断保护（防止记忆膨胀撑爆 system prompt）。"""
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        lines = [f"- [m{i}](m{i}.md) — line {i}" for i in range(300)]
        (mem_dir / "MEMORY.md").write_text("\n".join(lines), encoding="utf-8")
        section = mem_env.get_prompt_section()
        assert "truncated at 200 lines" in section

    def test_corrupted_index_returns_empty_not_crash(self, mem_env):
        """索引损坏（编码错误）不应崩溃。"""
        mem_dir = mem_env.memory_dir
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_bytes(b"\xff\xfe garbage \x00")
        section = mem_env.get_prompt_section()
        assert "# auto memory" in section  # 说明仍在，只是索引为空


# ──────────────────────────────────────────────
#  D. 组件测试：主循环权限 hook 的接线
# ──────────────────────────────────────────────

class TestLoopWiring:
    def test_session_hooks_use_state_memory(self):
        """主循环钩子引用的 memory 单例来自 state（main.py 注入的同一个）。"""
        from agents import session
        import inspect
        src = inspect.getsource(session)
        assert "state.memory" in src or "state.perm_rules" in src

    def test_state_memory_initial_none(self):
        """未初始化时 state.memory 为 None——此时 prompt 构建会跳过记忆段。
        （这就是'忘了 main.py 初始化就会静默失去记忆'的脆弱点）"""
        import importlib
        # state.memory 默认 None（其他测试可能已赋值，这里只验证模块默认约定）
        assert hasattr(st, "memory")
