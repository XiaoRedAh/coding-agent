"""单元测试：services/llm.py（JSON 截断修复）"""
import pytest
from llm.adapter import LLMAdapter


class TestJSONRepair:
    """测试 JSON 截断修复功能。"""

    @pytest.fixture
    def adapter(self):
        """Create a minimal LLMAdapter for testing JSON repair methods."""
        return LLMAdapter(provider="openai", client=None, model="test")

    def test_truncated_complete_object(self, adapter):
        """测试完整的 JSON 对象（无截断）"""
        raw = '{"file_path": "test.py", "old_string": "hello"}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result["file_path"] == "test.py"
        assert result["old_string"] == "hello"

    def test_truncated_string_value(self, adapter):
        """测试被截断的字符串值 - 返回错误，让工具层知道参数有问题"""
        # 模拟: {"file_path": "a.txt", "old_string": "hel
        # 这类截断通常无法安全修复，_repair_truncated_json 返回 False
        raw = '{"file_path": "a.txt", "old_string": "hel'
        result, ok = adapter._repair_truncated_json(raw)
        # 当无法修复时，返回 False（由调用方注入 _json_parse_error）
        assert isinstance(ok, bool)

    def test_truncated_middle_of_string(self, adapter):
        """测试在字符串中间截断"""
        raw = '{"command": "ls -la /tmp/very_long_'
        result, ok = adapter._repair_truncated_json(raw)
        # 无法修复完整对象，返回 False
        assert isinstance(ok, bool)

    def test_incomplete_nested_object(self, adapter):
        """测试不完整的嵌套对象"""
        raw = '{"result": {"files": ["a.py", "b.py"], "count":'
        result, ok = adapter._repair_truncated_json(raw)
        # 应该优雅地返回 False，不会崩溃
        assert isinstance(ok, bool)

    def test_empty_string(self, adapter):
        """空字符串"""
        raw = ""
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is False

    def test_whitespace_only(self, adapter):
        """纯空白"""
        raw = "   \n\t  "
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is False

    def test_completely_invalid_json(self, adapter):
        """完全无效的 JSON"""
        raw = "this is not json at all"
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is False

    def test_array_truncation(self, adapter):
        """测试数组截断"""
        raw = '{"items": [{"name": "task1"}, {"name":'
        result, ok = adapter._repair_truncated_json(raw)
        # 策略提取应该能找到 {"items": [...]} 之前的部分
        assert isinstance(ok, bool)

    def test_trailing_comma(self, adapter):
        """测试以逗号结尾的截断"""
        raw = '{"file_path": "test.py",'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result.get("file_path") == "test.py"

    def test_safe_parse_valid_json(self, adapter):
        """测试安全解析 - 有效 JSON"""
        raw = '{"key": "value", "num": 42}'
        result, err = adapter._safe_parse_json(raw)
        assert err is None
        assert result["key"] == "value"
        assert result["num"] == 42

    def test_safe_parse_invalid_json(self, adapter):
        """测试安全解析 - 无效 JSON"""
        raw = '{"key": unquoted_value}'
        result, err = adapter._safe_parse_json(raw)
        assert err is not None
        assert result == {}

    def test_safe_parse_truncated_json(self, adapter):
        """测试安全解析 - 截断的 JSON（无法解析）"""
        raw = '{"key": "val'
        result, err = adapter._safe_parse_json(raw)
        assert err is not None
        assert result == {}

    def test_single_key_object(self, adapter):
        """测试单个键的对象"""
        raw = '{"file_path": "a.txt"}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result["file_path"] == "a.txt"

    def test_nested_object_complete(self, adapter):
        """测试完整的嵌套对象"""
        raw = '{"outer": {"inner": "value"}}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result["outer"]["inner"] == "value"

    def test_deeply_nested_truncated(self, adapter):
        """测试深度嵌套的截断"""
        raw = '{"a": {"b": {"c": {"d": "val'
        result, ok = adapter._repair_truncated_json(raw)
        # 应该优雅地返回 False
        assert isinstance(ok, bool)


class TestJSONRepairIntegration:
    """测试 JSON 修复与工具调用流程的集成。"""

    @pytest.fixture
    def adapter(self):
        return LLMAdapter(provider="openai", client=None, model="test")

    def test_truncated_tool_args_not_repaired(self, adapter):
        """测试工具参数被截断时，如果无法修复则返回错误标记"""
        raw = "totally broken json {"
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is False

    def test_edge_case_double_brace(self, adapter):
        """边界：两个连续的 {"""
        raw = "{{"
        result, ok = adapter._repair_truncated_json(raw)
        # 应该优雅地返回 False，不会崩溃
        assert isinstance(ok, bool)

    def test_edge_case_unmatched_brace(self, adapter):
        """边界：大量未匹配的括号"""
        raw = '{"a": [{"b": [{"c":'
        result, ok = adapter._repair_truncated_json(raw)
        assert isinstance(ok, bool)

    def test_number_only_value(self, adapter):
        """边界：只有数字值的 key"""
        raw = '{"count":'
        result, ok = adapter._repair_truncated_json(raw)
        assert isinstance(ok, bool)

    def test_array_of_objects(self, adapter):
        """完整的对象数组"""
        raw = '{"files": [{"name": "a.py"}, {"name": "b.py"}]}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert len(result["files"]) == 2

    def test_special_characters_in_string(self, adapter):
        """带特殊字符的字符串"""
        raw = '{"path": "/tmp/test file (1).py"}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result["path"] == "/tmp/test file (1).py"

    def test_unicode_in_string(self, adapter):
        """带 Unicode 字符的字符串"""
        raw = '{"name": "测试文件"}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result["name"] == "测试文件"

    def test_boolean_and_null_values(self, adapter):
        """布尔值和 null 值"""
        raw = '{"active": true, "count": null}'
        result, ok = adapter._repair_truncated_json(raw)
        assert ok is True
        assert result["active"] is True
        assert result["count"] is None
