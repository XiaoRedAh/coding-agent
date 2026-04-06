"""单元测试：utils/truncate.py + utils/path.py"""
import pytest
from utils.truncate import truncate_result, MAX_RESULT_CHARS


class TestTruncateResult:
    def test_short_no_truncation(self):
        assert truncate_result("hello") == "hello"

    def test_exactly_at_limit(self):
        s = "x" * MAX_RESULT_CHARS
        assert truncate_result(s) == s

    def test_over_limit_truncated(self):
        s = "A" * 30000 + "MIDDLE" + "Z" * 30000
        result = truncate_result(s)
        assert len(result) <= MAX_RESULT_CHARS + 100
        assert "truncated" in result
        assert result.startswith("A")
        assert result.endswith("Z")

    def test_preserves_head_and_tail(self):
        head = "HEAD_MARKER_" * 100
        tail = "_TAIL_MARKER" * 100
        s = head + "x" * 60000 + tail
        result = truncate_result(s)
        assert "HEAD_MARKER" in result
        assert "TAIL_MARKER" in result

    def test_empty_string(self):
        assert truncate_result("") == ""


class TestSafePath:
    def test_valid_relative(self, tmp_workdir):
        from utils.path import safe_path
        (tmp_workdir / "test.py").write_text("pass")
        p = safe_path("test.py")
        assert p.name == "test.py"

    def test_escaping_raises(self, tmp_workdir):
        from utils.path import safe_path
        with pytest.raises(ValueError, match="escapes"):
            safe_path("../../etc/passwd")

    def test_nested_valid(self, tmp_workdir):
        from utils.path import safe_path
        (tmp_workdir / "src").mkdir()
        p = safe_path("src/main.py")
        assert "src" in str(p)
