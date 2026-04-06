"""单元测试：tools/FileEditTool.py 内部函数"""
import pytest
from tools.FileEditTool import _normalize_quotes, _find_actual_string, _generate_diff


class TestNormalizeQuotes:
    def test_curly_single(self):
        assert _normalize_quotes("\u2018hello\u2019") == "'hello'"

    def test_curly_double(self):
        assert _normalize_quotes("\u201Chello\u201D") == '"hello"'

    def test_straight_unchanged(self):
        assert _normalize_quotes("'hello' \"world\"") == "'hello' \"world\""

    def test_mixed(self):
        result = _normalize_quotes("\u2018test\u201D")
        assert result == "'test\""


class TestFindActualString:
    def test_exact_match(self):
        assert _find_actual_string("hello world", "world") == "world"

    def test_normalized_match(self):
        file_content = 'const msg = "hello";'
        search = 'const msg = \u201Chello\u201D;'
        result = _find_actual_string(file_content, search)
        assert result is not None

    def test_no_match(self):
        assert _find_actual_string("hello world", "goodbye") is None

    def test_empty_search(self):
        assert _find_actual_string("hello", "") == ""


class TestGenerateDiff:
    def test_single_line_change(self):
        old = "line1\nold_line\nline3"
        new = "line1\nnew_line\nline3"
        diff = _generate_diff(old, new, "old_line", "new_line")
        assert "@@ -2,1 +2,1 @@" in diff
        assert "- old_line" in diff
        assert "+ new_line" in diff

    def test_multi_line_change(self):
        old = "a\nb\nc"
        new = "a\nx\ny\nz\nc"
        diff = _generate_diff(old, new, "b", "x\ny\nz")
        assert "- b" in diff
        assert "+ x" in diff

    def test_first_line(self):
        old = "old\nrest"
        new = "new\nrest"
        diff = _generate_diff(old, new, "old", "new")
        assert "@@ -1" in diff
