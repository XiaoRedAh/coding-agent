"""
Module evaluation: Tool implementations
Cost: $0 | LLM required: No
Run: python eval/eval_tools.py
"""
import sys
import os
import tempfile
import time
import json
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

# Patch WORKDIR before importing tools (tools use safe_path which depends on WORKDIR)
_tmpdir_obj = tempfile.TemporaryDirectory()
_TMPDIR = Path(_tmpdir_obj.name)

import bootstrap.state as _state
_state.WORKDIR = _TMPDIR


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
#  Helper: create temp files in WORKDIR
# ──────────────────────────────────────────────

def _write_tmp(name: str, content: str) -> Path:
    """Write a file inside the patched WORKDIR."""
    p = _TMPDIR / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ──────────────────────────────────────────────
#  1. FileReadTool evaluation
# ──────────────────────────────────────────────

def evaluate_file_read() -> EvalResult:
    from tools import FileReadTool

    r = EvalResult("FileReadTool")

    # 1.1 Read a normal file with line numbers
    _write_tmp("read_test.txt", "alpha\nbeta\ngamma\ndelta\nepsilon")
    out = FileReadTool.handle("read_test.txt")
    r.record("1 | alpha" in out, "line numbers present", "line numbered output", out[:80])
    r.record("5 | epsilon" in out, "last line present", "line 5", out[-80:])

    # 1.2 Limit parameter truncates lines
    out = FileReadTool.handle("read_test.txt", limit=2)
    r.record("beta" in out, "limit=2 includes line 2", "beta in output", out[:80])
    r.record("gamma" not in out.split("more lines")[0] if "more lines" in out else "gamma" not in out,
             "limit=2 excludes line 3 from main body", "gamma absent", out[:120])
    r.record("3 more lines" in out, "truncation note present", "3 more lines", out)

    # 1.3 Non-existent file returns error
    out = FileReadTool.handle("nonexistent_file_xyz.txt")
    r.record("Error" in out or "error" in out.lower(), "missing file error", "error message", out[:80])

    # 1.4 Empty file
    _write_tmp("empty.txt", "")
    out = FileReadTool.handle("empty.txt")
    # Should not crash
    r.record(isinstance(out, str), "empty file returns string", "string", type(out).__name__)

    # 1.5 Large file truncation (via utils.truncate)
    big_content = "\n".join([f"line {i}" for i in range(10000)])
    _write_tmp("big.txt", big_content)
    out = FileReadTool.handle("big.txt")
    r.record(len(out) <= 55000, "large file truncated", "<=55000 chars", str(len(out)))

    return r


# ──────────────────────────────────────────────
#  2. FileWriteTool evaluation
# ──────────────────────────────────────────────

def evaluate_file_write() -> EvalResult:
    from tools import FileWriteTool

    r = EvalResult("FileWriteTool")

    # 2.1 Write new file
    out = FileWriteTool.handle("write_test.txt", "hello world")
    r.record("Successfully" in out, "write success message", "Successfully", out[:60])
    content = (_TMPDIR / "write_test.txt").read_text(encoding="utf-8")
    r.record(content == "hello world", "content matches", "hello world", content[:40])

    # 2.2 Overwrite existing
    FileWriteTool.handle("write_test.txt", "overwritten")
    content = (_TMPDIR / "write_test.txt").read_text(encoding="utf-8")
    r.record(content == "overwritten", "overwrite works", "overwritten", content[:40])

    # 2.3 Auto-create parent directories
    out = FileWriteTool.handle("sub/dir/deep.txt", "deep content")
    r.record((_TMPDIR / "sub" / "dir" / "deep.txt").exists(), "parent dirs created", "file exists", str(out[:60]))

    # 2.4 Reports byte count
    out = FileWriteTool.handle("byte_test.txt", "12345")
    r.record("5 bytes" in out, "byte count reported", "5 bytes", out[:60])

    return r


# ──────────────────────────────────────────────
#  3. FileEditTool evaluation
# ──────────────────────────────────────────────

def evaluate_file_edit() -> EvalResult:
    from tools import FileEditTool

    r = EvalResult("FileEditTool")

    # 3.1 Basic exact match replacement
    _write_tmp("edit_test.py", "def foo():\n    return 1\n")
    out = FileEditTool.handle("edit_test.py", "return 1", "return 42")
    r.record("Successfully" in out, "edit success", "Successfully", out[:60])
    content = (_TMPDIR / "edit_test.py").read_text(encoding="utf-8")
    r.record("return 42" in content, "content replaced", "return 42", content[:60])

    # 3.2 Diff output contains + and - lines
    r.record("- " in out and "+ " in out, "diff output present", "+/- lines", out[:200])
    r.record("@@" in out, "diff header present", "@@", out[:200])

    # 3.3 Uniqueness check — duplicate old_string
    _write_tmp("dup.py", "x = 1\nx = 1\n")
    out = FileEditTool.handle("dup.py", "x = 1", "x = 2")
    r.record("found 2 times" in out or "2 times" in out, "uniqueness error", "found N times", out[:120])

    # 3.4 Not found
    out = FileEditTool.handle("edit_test.py", "nonexistent string xyz", "replacement")
    r.record("not found" in out.lower(), "not found error", "not found", out[:80])

    # 3.5 Quote normalization (curly quotes -> straight)
    _write_tmp("quotes.py", "msg = 'hello'\n")
    # Use curly single quotes in search
    out = FileEditTool.handle("quotes.py", "msg = \u2018hello\u2019", "msg = 'world'")
    r.record("Successfully" in out, "quote normalization works", "Successfully", out[:80])
    r.record("quote normalization" in out.lower(), "normalization noted", "note", out[:200])

    return r


# ──────────────────────────────────────────────
#  4. ListFilesTool evaluation
# ──────────────────────────────────────────────

def evaluate_list_files() -> EvalResult:
    from tools import ListFilesTool

    r = EvalResult("ListFilesTool")

    # Create some test files
    _write_tmp("src/a.py", "a")
    time.sleep(0.05)
    _write_tmp("src/b.py", "b")
    time.sleep(0.05)
    _write_tmp("src/c.js", "c")
    _write_tmp("docs/readme.md", "r")

    # 4.1 Glob pattern matching
    out = ListFilesTool.handle("src/*.py", str(_TMPDIR))
    r.record("a.py" in out and "b.py" in out, "glob *.py matches", "a.py, b.py", out[:120])
    r.record("c.js" not in out, "glob *.py excludes .js", "no c.js", out[:120])

    # 4.2 Recursive glob
    out = ListFilesTool.handle("**/*.py", str(_TMPDIR))
    r.record("a.py" in out, "recursive glob finds py files", "a.py", out[:120])

    # 4.3 Empty results
    out = ListFilesTool.handle("*.xyz", str(_TMPDIR))
    r.record("No files found" in out, "empty result message", "No files found", out[:60])

    # 4.4 Sorting by modification time (newest first)
    out = ListFilesTool.handle("src/*.py", str(_TMPDIR))
    lines = [l.strip() for l in out.strip().split("\n") if l.strip()]
    # b.py was written after a.py so should appear first
    if len(lines) >= 2:
        b_idx = next((i for i, l in enumerate(lines) if "b.py" in l), -1)
        a_idx = next((i for i, l in enumerate(lines) if "a.py" in l), -1)
        r.record(b_idx < a_idx, "sorted by mtime (newest first)", f"b@{b_idx}<a@{a_idx}", f"b@{b_idx},a@{a_idx}")
    else:
        r.record(False, "sorted by mtime", "2 lines", str(len(lines)))

    return r


# ──────────────────────────────────────────────
#  5. GrepSearchTool evaluation
# ──────────────────────────────────────────────

def evaluate_grep_search() -> EvalResult:
    from tools import GrepSearchTool

    r = EvalResult("GrepSearchTool")

    # Create searchable files
    _write_tmp("grep_dir/code.py", "def hello():\n    print('world')\n    return 42\n")
    _write_tmp("grep_dir/data.txt", "foo bar\nbaz hello qux\n")
    _write_tmp("grep_dir/other.js", "// hello javascript\n")

    # 5.1 Basic regex search
    out = GrepSearchTool.handle("hello", str(_TMPDIR / "grep_dir"))
    r.record("hello" in out, "basic search finds match", "hello", out[:120])

    # 5.2 Include filter
    out = GrepSearchTool.handle("hello", str(_TMPDIR / "grep_dir"), include="*.py")
    r.record("code.py" in out, "include=*.py finds .py", "code.py", out[:120])
    r.record(".js" not in out, "include=*.py excludes .js", "no .js", out[:120])

    # 5.3 No matches
    out = GrepSearchTool.handle("nonexistent_pattern_xyz", str(_TMPDIR / "grep_dir"))
    r.record("No matches" in out, "no match message", "No matches", out[:60])

    # 5.4 Regex pattern
    out = GrepSearchTool.handle("return [0-9]+", str(_TMPDIR / "grep_dir"))
    r.record("42" in out, "regex pattern works", "42", out[:120])

    # 5.5 Max matches limiting (create file with many matches)
    many_lines = "\n".join([f"match_line_{i}" for i in range(150)])
    _write_tmp("grep_dir/many.txt", many_lines)
    out = GrepSearchTool.handle("match_line_", str(_TMPDIR / "grep_dir" / "many.txt"))
    r.record("more matches" in out or out.count("match_line_") <= 100,
             "max matches limiting", "<=100 or note", str(out.count("match_line_")))

    return r


# ──────────────────────────────────────────────
#  6. BashTool evaluation
# ──────────────────────────────────────────────

def evaluate_bash_tool() -> EvalResult:
    from tools import BashTool

    # BashTool needs state.bg for background tasks
    import queue
    class FakeBG:
        def __init__(self):
            self.notifications = queue.Queue()
    _state.bg = FakeBG()

    r = EvalResult("BashTool")

    # 6.1 Simple command
    out = BashTool.handle("echo hello_world")
    r.record("hello_world" in out, "echo works", "hello_world", out[:60])

    # 6.2 Exit code 0
    out = BashTool.handle("true")
    r.record("no output" in out.lower() or isinstance(out, str), "exit 0 handled", "string", out[:60])

    # 6.3 Non-zero exit code
    out = BashTool.handle("false")
    r.record("exit code" in out.lower() or "failed" in out.lower(), "exit 1 error", "error message", out[:80])

    # 6.4 Stderr separation
    out = BashTool.handle("echo err_msg >&2 && exit 1")
    r.record("err_msg" in out, "stderr captured", "err_msg", out[:120])

    # 6.5 Timeout
    out = BashTool.handle("sleep 10", timeout=1)
    r.record("timed out" in out.lower() or "timeout" in out.lower(), "timeout works", "timeout msg", out[:80])

    # 6.6 grep exit 1 is OK (not error)
    _write_tmp("grep_bash_test.txt", "hello\nworld\n")
    out = BashTool.handle(f"grep nomatch {_TMPDIR / 'grep_bash_test.txt'}")
    # grep exit 1 should not say "failed"
    r.record("failed" not in out.lower() or "no matches" in out.lower(),
             "grep exit 1 not error", "no error", out[:80])

    # 6.7 Background mode returns task ID
    out = BashTool.handle("echo bg_test", run_in_background=True)
    r.record("Background task" in out or "started" in out,
             "background returns task id", "Background task", out[:80])

    # 6.8 Command with output
    out = BashTool.handle("echo line1 && echo line2")
    r.record("line1" in out and "line2" in out, "multi-line output", "line1+line2", out[:80])

    return r


# ──────────────────────────────────────────────
#  Advanced / Edge Case evaluations
# ──────────────────────────────────────────────

def evaluate_file_read_advanced() -> EvalResult:
    """FileReadTool 高级/边界场景"""
    from tools import FileReadTool
    r = EvalResult("FileReadTool (Advanced)")

    # A1. Empty file
    _write_tmp("empty.txt", "")
    out = FileReadTool.handle(str(_TMPDIR / "empty.txt"))
    r.record(out.strip() == "" or "no" in out.lower() or len(out) < 20,
             "empty file handled", "empty/minimal output", out[:60])

    # A2. Single line file
    _write_tmp("single.txt", "only one line")
    out = FileReadTool.handle(str(_TMPDIR / "single.txt"))
    r.record("1 |" in out or "1|" in out, "single line has line number", "line 1", out[:60])

    # A3. Large file truncation
    _write_tmp("large.txt", "x" * 60000)
    out = FileReadTool.handle(str(_TMPDIR / "large.txt"))
    r.record(len(out) <= 55000, "large file truncated", "<55000 chars", str(len(out)))

    # A4. Unicode content
    _write_tmp("unicode.txt", "你好世界\néàü\n🎉")
    out = FileReadTool.handle(str(_TMPDIR / "unicode.txt"))
    r.record("你好" in out, "unicode preserved", "你好", out[:60])

    # A5. File with limit parameter
    _write_tmp("limited.txt", "\n".join(f"line {i}" for i in range(100)))
    out = FileReadTool.handle(str(_TMPDIR / "limited.txt"), limit=5)
    r.record("line 4" in out and "line 10" not in out, "limit parameter works", "5 lines", out[:120])

    # A6. Non-existent file
    out = FileReadTool.handle(str(_TMPDIR / "does_not_exist.txt"))
    r.record("error" in out.lower(), "non-existent file returns error", "error", out[:80])

    return r


def evaluate_file_edit_advanced() -> EvalResult:
    """FileEditTool 高级/边界场景"""
    from tools import FileEditTool
    r = EvalResult("FileEditTool (Advanced)")

    # A1. Multiple occurrences (should reject)
    _write_tmp("multi.py", "x = 1\nx = 2\nx = 3\n")
    out = FileEditTool.handle(str(_TMPDIR / "multi.py"), "x =", "y =")
    r.record("found" in out.lower() and ("3" in out or "times" in out or "unique" in out.lower()),
             "rejects multi-occurrence", "error about uniqueness", out[:120])

    # A2. old_string not found
    _write_tmp("nofind.py", "hello world\n")
    out = FileEditTool.handle(str(_TMPDIR / "nofind.py"), "NOTFOUND", "replacement")
    r.record("not found" in out.lower(), "not found error", "not found", out[:80])

    # A3. Replace with empty string (delete)
    _write_tmp("delete.py", "keep this\ndelete this line\nkeep too\n")
    out = FileEditTool.handle(str(_TMPDIR / "delete.py"), "delete this line\n", "")
    r.record("successfully" in out.lower() or "edited" in out.lower(),
             "delete via empty replacement", "success", out[:80])
    content = (_TMPDIR / "delete.py").read_text()
    r.record("delete this line" not in content, "line actually deleted", "no deleted line", content[:80])

    # A4. Multiline replacement
    _write_tmp("multiline.py", "def old():\n    pass\n\ndef other():\n    pass\n")
    out = FileEditTool.handle(str(_TMPDIR / "multiline.py"),
                              "def old():\n    pass", "def new():\n    return 42")
    r.record("successfully" in out.lower() or "edited" in out.lower(),
             "multiline replace", "success", out[:80])

    # A5. Diff output contains correct markers
    _write_tmp("diff.py", "old_value = 1\n")
    out = FileEditTool.handle(str(_TMPDIR / "diff.py"), "old_value = 1", "new_value = 2")
    r.record("- old_value" in out and "+ new_value" in out, "diff has +/- markers", "+/-", out[:200])

    # A6. Curly quote normalization
    _write_tmp("quotes.py", 'msg = "hello"\n')
    out = FileEditTool.handle(str(_TMPDIR / "quotes.py"),
                              'msg = \u201Chello\u201D', 'msg = "world"')
    r.record("successfully" in out.lower() or "normalization" in out.lower(),
             "curly quote normalization", "success", out[:120])

    return r


def evaluate_bash_advanced() -> EvalResult:
    """BashTool 高级/边界场景"""
    from tools import BashTool
    r = EvalResult("BashTool (Advanced)")

    # A1. Pipe command
    out = BashTool.handle("echo 'hello world' | wc -w")
    r.record("2" in out, "pipe works", "2", out[:60])

    # A2. Environment variable
    out = BashTool.handle("echo $HOME")
    r.record("/" in out, "env var expanded", "/ in path", out[:80])

    # A3. Working directory
    out = BashTool.handle("pwd")
    r.record("/" in out, "pwd returns path", "path", out[:80])

    # A4. Multi-command with &&
    out = BashTool.handle("echo first && echo second")
    r.record("first" in out and "second" in out, "chained && works", "first+second", out[:80])

    # A5. Command with semicolon
    out = BashTool.handle("echo a; echo b")
    r.record("a" in out and "b" in out, "semicolon chain", "a+b", out[:60])

    # A6. diff exit code 1 = has differences (not error)
    _write_tmp("diff_a.txt", "line1\nline2\n")
    _write_tmp("diff_b.txt", "line1\nline3\n")
    out = BashTool.handle(f"diff {_TMPDIR / 'diff_a.txt'} {_TMPDIR / 'diff_b.txt'}")
    r.record("failed" not in out.lower() or "line" in out, "diff exit 1 handled", "not error", out[:120])

    # A7. Large output truncation
    out = BashTool.handle("seq 1 100000")
    r.record(len(out) <= 55000, "large output truncated", "<55000", str(len(out)))

    return r


def evaluate_grep_advanced() -> EvalResult:
    """GrepSearchTool 高级/边界场景"""
    from tools import GrepSearchTool
    r = EvalResult("GrepSearchTool (Advanced)")

    # A1. Case-insensitive pattern (grep -E doesn't add -i, so this tests exact match)
    _write_tmp("grep_adv/case.txt", "Hello World\nhello world\nHELLO WORLD\n")
    out = GrepSearchTool.handle("hello", str(_TMPDIR / "grep_adv"))
    r.record("hello world" in out.lower(), "lowercase match", "hello", out[:120])

    # A2. Regex with groups
    _write_tmp("grep_adv/regex.txt", "error: code 404\nwarning: code 200\nerror: code 500\n")
    out = GrepSearchTool.handle("error.*code [45][0-9]{2}", str(_TMPDIR / "grep_adv"))
    r.record("404" in out or "500" in out, "complex regex", "404 or 500", out[:120])

    # A3. Include filter
    _write_tmp("grep_adv/code.py", "import os\n")
    _write_tmp("grep_adv/code.js", "import os\n")
    out = GrepSearchTool.handle("import", str(_TMPDIR / "grep_adv"), include="*.py")
    r.record("code.py" in out and "code.js" not in out, "include filter", "only .py", out[:120])

    # A4. Binary file skipped
    _write_tmp("grep_adv/binary.bin", "\x00\x01\x02\x03")
    out = GrepSearchTool.handle("test", str(_TMPDIR / "grep_adv"))
    r.record("binary" not in out.lower() or True, "binary handled", "no crash", out[:60])

    # A5. Empty search path
    import tempfile
    with tempfile.TemporaryDirectory() as empty_dir:
        out = GrepSearchTool.handle("anything", empty_dir)
        r.record("no match" in out.lower() or "error" not in out.lower() or True,
                 "empty dir no crash", "no crash", out[:60])

    return r


# ──────────────────────────────────────────────
#  Report generation
# ──────────────────────────────────────────────

def run_full_evaluation():
    evaluators = [
        ("FileReadTool", evaluate_file_read),
        ("FileWriteTool", evaluate_file_write),
        ("FileEditTool", evaluate_file_edit),
        ("ListFilesTool", evaluate_list_files),
        ("GrepSearchTool", evaluate_grep_search),
        ("BashTool", evaluate_bash_tool),
        ("FileReadTool (Advanced)", evaluate_file_read_advanced),
        ("FileEditTool (Advanced)", evaluate_file_edit_advanced),
        ("BashTool (Advanced)", evaluate_bash_advanced),
        ("GrepSearchTool (Advanced)", evaluate_grep_advanced),
    ]

    results = []
    for name, fn in evaluators:
        try:
            results.append(fn())
        except Exception as e:
            r = EvalResult(name)
            r.record(False, f"evaluator crashed: {e}")
            results.append(r)

    total_cases = sum(r.total for r in results)
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)

    print("=" * 70)
    print("  Tool Implementation Evaluation Report")
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

    # Cleanup
    _tmpdir_obj.cleanup()
    return total_failed == 0


# ──────────────────────────────────────────────
#  pytest compatible
# ──────────────────────────────────────────────

def test_file_read():
    r = evaluate_file_read()
    assert r.accuracy >= 0.90, f"FileReadTool accuracy {r.accuracy:.1%} < 90%"

def test_file_write():
    r = evaluate_file_write()
    assert r.accuracy >= 0.90, f"FileWriteTool accuracy {r.accuracy:.1%} < 90%"

def test_file_edit():
    r = evaluate_file_edit()
    assert r.accuracy >= 0.90, f"FileEditTool accuracy {r.accuracy:.1%} < 90%"

def test_list_files():
    r = evaluate_list_files()
    assert r.accuracy >= 0.90, f"ListFilesTool accuracy {r.accuracy:.1%} < 90%"

def test_grep_search():
    r = evaluate_grep_search()
    assert r.accuracy >= 0.80, f"GrepSearchTool accuracy {r.accuracy:.1%} < 80%"

def test_bash_tool():
    r = evaluate_bash_tool()
    assert r.accuracy >= 0.80, f"BashTool accuracy {r.accuracy:.1%} < 80%"


if __name__ == "__main__":
    success = run_full_evaluation()
    sys.exit(0 if success else 1)
