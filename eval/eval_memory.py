"""
Module evaluation: Memory system (services/memory.py)
Cost: $0 | LLM required: No
Run: python eval/eval_memory.py
"""
import sys
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

# Patch MEMORY_DIR before importing
import runtime.state as _state


@dataclass
class EvalResult:
    category: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    details: list = field(default_factory=list)

    @property
    def accuracy(self):
        return self.passed / self.total if self.total else 0.0

    def record(self, success, desc, expected="", actual=""):
        self.total += 1
        if success:
            self.passed += 1
        else:
            self.failed += 1
            self.details.append(f"  FAIL: {desc} (expected={expected}, actual={actual})")


# ──────────────────────────────────────────────
#  Helper: create memory files
# ──────────────────────────────────────────────

def _write_memory_file(mem_dir: Path, filename: str, name: str, desc: str,
                        mtype: str, body: str):
    """Create a memory file with frontmatter."""
    content = f"---\nname: {name}\ndescription: {desc}\ntype: {mtype}\n---\n{body}"
    (mem_dir / filename).write_text(content, encoding="utf-8")


# ──────────────────────────────────────────────
#  1. MEMORY.md index truncation
# ──────────────────────────────────────────────

def evaluate_index_truncation() -> EvalResult:
    from services.memory import MemoryManager, MAX_INDEX_LINES, MAX_INDEX_BYTES

    r = EvalResult("MEMORY.md Index Truncation")

    with tempfile.TemporaryDirectory() as td:
        mem_dir = Path(td)
        _state.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir

        # 1.1 No MEMORY.md — returns empty
        content = mgr.get_index_content()
        r.record(content == "", "missing index returns empty", "", content[:20])

        # 1.2 Normal MEMORY.md
        index_path = mem_dir / "MEMORY.md"
        index_path.write_text("- [User Role](user_role.md) -- user is a developer\n", encoding="utf-8")
        content = mgr.get_index_content()
        r.record("user_role.md" in content, "normal index readable", "user_role.md", content[:80])

        # 1.3 Index > 200 lines — truncated
        big_index = "\n".join([f"- [Memory {i}](mem_{i}.md) -- line {i}" for i in range(300)])
        index_path.write_text(big_index, encoding="utf-8")
        content = mgr.get_index_content()
        lines = content.split("\n")
        # Should have truncation warning
        r.record("truncated" in content.lower() or "WARNING" in content,
                 ">200 lines triggers truncation", "truncation warning", content[-80:])
        # The main content lines should be <= MAX_INDEX_LINES (+ warning lines)
        main_lines = [l for l in lines if l.startswith("- [")]
        r.record(len(main_lines) <= MAX_INDEX_LINES,
                 f"main lines <= {MAX_INDEX_LINES}", f"<={MAX_INDEX_LINES}", str(len(main_lines)))

        # 1.4 Index > 25KB — truncated by bytes
        huge_index = "A" * 30000
        index_path.write_text(huge_index, encoding="utf-8")
        content = mgr.get_index_content()
        r.record(len(content.encode("utf-8")) <= MAX_INDEX_BYTES + 200,
                 "byte limit truncation", f"<={MAX_INDEX_BYTES}+margin",
                 str(len(content.encode("utf-8"))))

    return r


# ──────────────────────────────────────────────
#  2. is_memory_path whitelist
# ──────────────────────────────────────────────

def evaluate_is_memory_path() -> EvalResult:
    from services.memory import MemoryManager

    r = EvalResult("is_memory_path Whitelist")

    with tempfile.TemporaryDirectory() as td:
        mem_dir = Path(td) / "memory"
        mem_dir.mkdir()
        _state.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir

        # 2.1 File inside memory dir
        (mem_dir / "test.md").write_text("test", encoding="utf-8")
        r.record(mgr.is_memory_path(str(mem_dir / "test.md")), "file inside mem dir", "True", "False")

        # 2.2 File outside memory dir
        outside = Path(td) / "outside.md"
        outside.write_text("out", encoding="utf-8")
        r.record(not mgr.is_memory_path(str(outside)), "file outside mem dir", "False", "True")

        # 2.3 Subdirectory inside memory dir
        sub = mem_dir / "sub"
        sub.mkdir()
        (sub / "deep.md").write_text("deep", encoding="utf-8")
        r.record(mgr.is_memory_path(str(sub / "deep.md")), "nested file inside mem dir", "True", "False")

    return r


# ──────────────────────────────────────────────
#  3. get_prompt_section content structure
# ──────────────────────────────────────────────

def evaluate_prompt_section() -> EvalResult:
    from services.memory import MemoryManager

    r = EvalResult("get_prompt_section Structure")

    with tempfile.TemporaryDirectory() as td:
        mem_dir = Path(td) / "memory"
        mem_dir.mkdir()
        _state.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir

        # 3.1 Empty memory — contains instructions and empty note
        section = mgr.get_prompt_section()
        r.record("# auto memory" in section, "has header", "# auto memory", section[:40])
        r.record("Memory Types" in section, "has Memory Types section", "Memory Types", "absent")
        r.record("How to Save" in section, "has How to Save section", "How to Save", "absent")
        r.record("empty" in section.lower(), "empty note present", "empty", "absent")

        # 3.2 With MEMORY.md — includes index content
        (mem_dir / "MEMORY.md").write_text("- [Pref](pref.md) -- user prefers dark mode\n", encoding="utf-8")
        section = mgr.get_prompt_section()
        r.record("Current Memory Index" in section, "has index section", "Current Memory Index", "absent")
        r.record("dark mode" in section, "index content included", "dark mode", section[-100:])

    return r


# ──────────────────────────────────────────────
#  4. list_memories scanning
# ──────────────────────────────────────────────

def evaluate_list_memories() -> EvalResult:
    from services.memory import MemoryManager

    r = EvalResult("list_memories Scanning")

    with tempfile.TemporaryDirectory() as td:
        mem_dir = Path(td) / "memory"
        mem_dir.mkdir()
        _state.MEMORY_DIR = mem_dir
        mgr = MemoryManager()
        mgr.memory_dir = mem_dir

        # 4.1 Empty directory
        memories = mgr.list_memories()
        r.record(len(memories) == 0, "empty dir returns []", "0", str(len(memories)))

        # 4.2 Create memory files
        _write_memory_file(mem_dir, "user_role.md", "User Role", "Developer", "user", "User is a backend dev.")
        _write_memory_file(mem_dir, "feedback_tests.md", "Test Feedback", "No mocking", "feedback", "Don't mock DB.")
        # Also create MEMORY.md (should be skipped)
        (mem_dir / "MEMORY.md").write_text("- [User Role](user_role.md)\n", encoding="utf-8")

        memories = mgr.list_memories()
        r.record(len(memories) == 2, "finds 2 memory files (skips MEMORY.md)", "2", str(len(memories)))

        # 4.3 Metadata extraction
        names = [m["name"] for m in memories]
        r.record("User Role" in names, "extracts name from frontmatter", "User Role", str(names))

        types = [m["type"] for m in memories]
        r.record("user" in types, "extracts type", "user", str(types))
        r.record("feedback" in types, "extracts feedback type", "feedback", str(types))

        # 4.4 Path included
        paths = [m["path"] for m in memories]
        r.record(all("memory" in p for p in paths), "path includes memory dir", "memory in path", str(paths[:1]))

    return r


# ──────────────────────────────────────────────
#  5. Frontmatter parsing
# ──────────────────────────────────────────────

def evaluate_frontmatter() -> EvalResult:
    from services.memory import MemoryManager

    r = EvalResult("Frontmatter Parsing")

    # 5.1 Valid frontmatter
    meta = MemoryManager._parse_frontmatter("---\nname: Test\ntype: user\n---\nBody here")
    r.record(meta.get("name") == "Test", "parses name", "Test", meta.get("name", ""))
    r.record(meta.get("type") == "user", "parses type", "user", meta.get("type", ""))

    # 5.2 No frontmatter
    meta = MemoryManager._parse_frontmatter("Just body text, no frontmatter.")
    r.record(len(meta) == 0, "no frontmatter returns {}", "0 keys", str(len(meta)))

    return r


# ──────────────────────────────────────────────
#  Report generation
# ──────────────────────────────────────────────

def run_full_evaluation():
    evaluators = [
        ("Index Truncation", evaluate_index_truncation),
        ("is_memory_path", evaluate_is_memory_path),
        ("Prompt Section", evaluate_prompt_section),
        ("list_memories", evaluate_list_memories),
        ("Frontmatter", evaluate_frontmatter),
    ]

    results = []
    for name, fn in evaluators:
        try:
            results.append(fn())
        except Exception as e:
            er = EvalResult(name)
            er.record(False, f"evaluator crashed: {e}")
            results.append(er)

    total_cases = sum(r.total for r in results)
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)

    print("=" * 70)
    print("  Memory System Evaluation Report")
    print("=" * 70)
    print()

    for r in results:
        status = "PASS" if r.failed == 0 else "FAIL"
        print(f"[{status}] {r.category}: {r.passed}/{r.total} ({r.accuracy:.1%})")
        for detail in r.details:
            print(detail)

    print()
    print("-" * 70)
    overall = total_passed / total_cases if total_cases else 0
    print(f"  Total: {total_passed}/{total_cases} ({overall:.1%})")
    print(f"  Passed: {total_passed}  Failed: {total_failed}")
    print(f"  Test cases: {total_cases}")
    print(f"  API calls: 0  |  Cost: $0")
    print("-" * 70)

    return total_failed == 0


# ──────────────────────────────────────────────
#  pytest compatible
# ──────────────────────────────────────────────

def test_index_truncation():
    r = evaluate_index_truncation()
    assert r.accuracy >= 0.90, f"Index truncation accuracy {r.accuracy:.1%} < 90%"

def test_is_memory_path():
    r = evaluate_is_memory_path()
    assert r.accuracy >= 0.90, f"is_memory_path accuracy {r.accuracy:.1%} < 90%"

def test_prompt_section():
    r = evaluate_prompt_section()
    assert r.accuracy >= 0.90, f"Prompt section accuracy {r.accuracy:.1%} < 90%"

def test_list_memories():
    r = evaluate_list_memories()
    assert r.accuracy >= 0.90, f"list_memories accuracy {r.accuracy:.1%} < 90%"

def test_frontmatter():
    r = evaluate_frontmatter()
    assert r.accuracy >= 0.90, f"Frontmatter accuracy {r.accuracy:.1%} < 90%"


if __name__ == "__main__":
    success = run_full_evaluation()
    sys.exit(0 if success else 1)
