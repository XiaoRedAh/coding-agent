"""单元测试：services/memory.py（Memory 系统，纯文件操作，不涉及 LLM）"""
import pytest
from services.memory import MemoryManager


class TestMemoryManager:
    def test_init(self):
        mgr = MemoryManager()
        assert mgr.memory_dir is not None

    def test_ensure_dir(self, tmp_workdir):
        import bootstrap.state as st
        st.MEMORY_DIR = tmp_workdir / ".xiaoagent" / "memory"
        mgr = MemoryManager()
        mgr.memory_dir = st.MEMORY_DIR
        mgr.ensure_dir()
        assert mgr.memory_dir.exists()

    def test_get_index_empty(self, tmp_workdir):
        import bootstrap.state as st
        st.MEMORY_DIR = tmp_workdir / ".xiaoagent" / "memory"
        mgr = MemoryManager()
        mgr.memory_dir = st.MEMORY_DIR
        assert mgr.get_index_content() == ""

    def test_get_index_with_content(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        st.MEMORY_DIR = mem_dir
        (mem_dir / "MEMORY.md").write_text("- [user_role](user_role.md) — Developer\n")
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        content = mgr.get_index_content()
        assert "user_role" in content

    def test_get_index_truncation(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        st.MEMORY_DIR = mem_dir
        # 250 lines — exceeds 200 limit
        lines = [f"- [memory_{i}](m{i}.md) — line {i}" for i in range(250)]
        (mem_dir / "MEMORY.md").write_text("\n".join(lines))
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        content = mgr.get_index_content()
        assert "truncated" in content.lower()

    def test_get_prompt_section(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        st.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        section = mgr.get_prompt_section()
        assert "auto memory" in section
        assert "Memory Types" in section
        assert "How to Save" in section
        assert "What NOT to Save" in section

    def test_list_memories_empty(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        st.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        assert mgr.list_memories() == []

    def test_list_memories_with_files(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        st.MEMORY_DIR = mem_dir
        (mem_dir / "user_role.md").write_text("---\nname: user_role\ndescription: Dev\ntype: user\n---\nContent")
        (mem_dir / "MEMORY.md").write_text("index")
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        memories = mgr.list_memories()
        assert len(memories) == 1
        assert memories[0]["name"] == "user_role"
        assert memories[0]["type"] == "user"

    def test_is_memory_path(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        st.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        assert mgr.is_memory_path(str(mem_dir / "test.md"))
        assert not mgr.is_memory_path(str(tmp_workdir / "src" / "main.py"))

    def test_parse_frontmatter(self):
        text = "---\nname: test\ndescription: A test\ntype: user\n---\nBody"
        meta = MemoryManager._parse_frontmatter(text)
        assert meta["name"] == "test"
        assert meta["type"] == "user"

    def test_parse_frontmatter_no_frontmatter(self):
        meta = MemoryManager._parse_frontmatter("Just plain text")
        assert meta == {}

    def test_prompt_section_includes_index(self, tmp_workdir):
        import bootstrap.state as st
        mem_dir = tmp_workdir / ".xiaoagent" / "memory"
        mem_dir.mkdir(parents=True)
        st.MEMORY_DIR = mem_dir
        (mem_dir / "MEMORY.md").write_text("- [test](test.md) — Test memory")
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir
        section = mgr.get_prompt_section()
        assert "Current Memory Index" in section
        assert "test.md" in section
