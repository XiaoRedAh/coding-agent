"""
Module evaluation: MCP integration (services/mcp.py)
Cost: $0 | LLM required: No
Run: python eval/eval_mcp.py
"""
import sys
import os
from pathlib import Path
from dataclasses import dataclass, field

sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("MODEL_ID", "test-model")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from services.mcp import (
    _normalize_name, build_mcp_tool_name, parse_mcp_tool_name,
    McpConnection, McpManager,
)


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
#  1. Tool name normalization
# ──────────────────────────────────────────────

def evaluate_name_normalization() -> EvalResult:
    r = EvalResult("Name Normalization")

    # 1.1 Simple name unchanged
    r.record(_normalize_name("github") == "github", "simple name", "github", _normalize_name("github"))

    # 1.2 Hyphens to underscores
    r.record(_normalize_name("my-server") == "my_server", "hyphens to underscores", "my_server", _normalize_name("my-server"))

    # 1.3 Dots to underscores
    r.record(_normalize_name("v2.api") == "v2_api", "dots to underscores", "v2_api", _normalize_name("v2.api"))

    # 1.4 Spaces to underscores
    r.record(_normalize_name("my tool") == "my_tool", "spaces to underscores", "my_tool", _normalize_name("my tool"))

    # 1.5 Leading/trailing special chars stripped
    out = _normalize_name("--name--")
    r.record(out == "name", "strips leading/trailing underscores", "name", out)

    # 1.6 Already valid name
    r.record(_normalize_name("valid_name_123") == "valid_name_123", "already valid", "valid_name_123", _normalize_name("valid_name_123"))

    return r


# ──────────────────────────────────────────────
#  2. MCP tool name building and parsing
# ──────────────────────────────────────────────

def evaluate_tool_name_ops() -> EvalResult:
    r = EvalResult("Tool Name Build/Parse")

    # 2.1 Build standard name
    name = build_mcp_tool_name("github", "create_issue")
    r.record(name == "mcp__github__create_issue", "build standard name",
             "mcp__github__create_issue", name)

    # 2.2 Build with special chars in server name
    name = build_mcp_tool_name("my-server", "run.query")
    r.record(name == "mcp__my_server__run_query", "build with special chars",
             "mcp__my_server__run_query", name)

    # 2.3 Parse valid name
    parsed = parse_mcp_tool_name("mcp__github__create_issue")
    r.record(parsed == ("github", "create_issue"), "parse valid name",
             "('github', 'create_issue')", str(parsed))

    # 2.4 Parse non-MCP name returns None
    parsed = parse_mcp_tool_name("read_file")
    r.record(parsed is None, "non-MCP name returns None", "None", str(parsed))

    # 2.5 Parse malformed name
    parsed = parse_mcp_tool_name("mcp__onlyserver")
    r.record(parsed is None, "malformed name returns None", "None", str(parsed))

    # 2.6 Roundtrip: build then parse
    built = build_mcp_tool_name("slack", "send_message")
    parsed = parse_mcp_tool_name(built)
    r.record(parsed == ("slack", "send_message"), "roundtrip build->parse",
             "('slack', 'send_message')", str(parsed))

    return r


# ──────────────────────────────────────────────
#  3. McpManager with mock connections
# ──────────────────────────────────────────────

def evaluate_manager_mock() -> EvalResult:
    r = EvalResult("McpManager (Mock)")

    mgr = McpManager()

    # 3.1 Empty manager
    r.record(mgr.server_count == 0, "empty manager has 0 servers", "0", str(mgr.server_count))
    r.record(mgr.tool_count == 0, "empty manager has 0 tools", "0", str(mgr.tool_count))

    # 3.2 Inject a mock connection
    mock_conn = McpConnection("test_server", "echo", [])
    mock_conn.tools = [
        {
            "name": "search",
            "description": "Search the codebase",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
        },
        {
            "name": "index",
            "description": "Index all files",
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]
    mock_conn.instructions = "Use search to find code patterns."
    mgr.connections["test_server"] = mock_conn

    r.record(mgr.server_count == 1, "1 mock server", "1", str(mgr.server_count))
    r.record(mgr.tool_count == 2, "2 mock tools", "2", str(mgr.tool_count))

    # 3.3 get_tool_definitions format
    defs = mgr.get_tool_definitions()
    r.record(len(defs) == 2, "2 tool definitions", "2", str(len(defs)))

    first_def = defs[0]
    r.record(first_def["name"] == "mcp__test_server__search",
             "definition name is mcp__server__tool", "mcp__test_server__search", first_def["name"])
    r.record("[MCP: test_server]" in first_def["description"],
             "description has server prefix", "[MCP: test_server]", first_def["description"][:50])
    r.record("input_schema" in first_def, "has input_schema", "present", "absent")

    return r


# ──────────────────────────────────────────────
#  4. Tool definition conversion (Anthropic format)
# ──────────────────────────────────────────────

def evaluate_tool_conversion() -> EvalResult:
    r = EvalResult("Tool Definition Conversion")

    mgr = McpManager()
    mock_conn = McpConnection("api", "echo", [])
    mock_conn.tools = [
        {
            "name": "fetch",
            "description": "Fetch data from API",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch"},
                },
                "required": ["url"],
            },
        },
    ]
    mgr.connections["api"] = mock_conn

    defs = mgr.get_tool_definitions()
    r.record(len(defs) == 1, "1 definition", "1", str(len(defs)))

    d = defs[0]
    # 4.1 Name format
    r.record(d["name"] == "mcp__api__fetch", "correct name format", "mcp__api__fetch", d["name"])

    # 4.2 Description format
    r.record(d["description"].startswith("[MCP: api]"), "description prefix", "[MCP: api]", d["description"][:20])

    # 4.3 input_schema preserved
    schema = d["input_schema"]
    r.record(schema["type"] == "object", "schema type=object", "object", schema.get("type"))
    r.record("url" in schema.get("properties", {}), "url property preserved", "url", str(list(schema.get("properties", {}).keys())))

    return r


# ──────────────────────────────────────────────
#  5. Instructions generation
# ──────────────────────────────────────────────

def evaluate_instructions() -> EvalResult:
    r = EvalResult("Instructions Generation")

    mgr = McpManager()

    # 5.1 No connections — empty instructions
    r.record(mgr.get_instructions() == "", "empty mgr = empty instructions", "", mgr.get_instructions()[:20])

    # 5.2 Connection without instructions
    mock_conn1 = McpConnection("no_inst", "echo", [])
    mock_conn1.tools = []
    mock_conn1.instructions = None
    mgr.connections["no_inst"] = mock_conn1
    r.record(mgr.get_instructions() == "", "no instructions = empty", "", mgr.get_instructions()[:20])

    # 5.3 Connection with instructions
    mock_conn2 = McpConnection("github", "echo", [])
    mock_conn2.tools = []
    mock_conn2.instructions = "Use GitHub tools to manage repositories."
    mgr.connections["github"] = mock_conn2

    instr = mgr.get_instructions()
    r.record("# MCP Server Instructions" in instr, "has header", "# MCP Server Instructions", instr[:40])
    r.record("## github" in instr, "has server section", "## github", instr[:100])
    r.record("manage repositories" in instr, "contains instruction text", "manage repositories", instr[:200])

    return r


# ──────────────────────────────────────────────
#  6. Description truncation at 2048 chars
# ──────────────────────────────────────────────

def evaluate_description_truncation() -> EvalResult:
    r = EvalResult("Description Truncation")

    mgr = McpManager()
    mock_conn = McpConnection("verbose", "echo", [])
    long_desc = "A" * 3000
    mock_conn.tools = [
        {"name": "tool", "description": long_desc, "inputSchema": {"type": "object", "properties": {}}},
    ]
    mgr.connections["verbose"] = mock_conn

    defs = mgr.get_tool_definitions()
    d = defs[0]

    # The description is "[MCP: verbose] " + truncated_desc
    # Original desc is 3000 chars, should be truncated to 2048 (2045 + "...")
    prefix = "[MCP: verbose] "
    desc_after_prefix = d["description"][len(prefix):]
    r.record(len(desc_after_prefix) <= 2048, "description <= 2048 chars",
             "<=2048", str(len(desc_after_prefix)))
    r.record(desc_after_prefix.endswith("..."), "truncated desc ends with ...",
             "...", desc_after_prefix[-5:])

    return r


# ──────────────────────────────────────────────
#  7. Tool handlers generation
# ──────────────────────────────────────────────

def evaluate_tool_handlers() -> EvalResult:
    r = EvalResult("Tool Handlers")

    mgr = McpManager()
    mock_conn = McpConnection("svc", "echo", [])
    mock_conn.tools = [
        {"name": "action", "description": "Do something", "inputSchema": {"type": "object", "properties": {}}},
    ]
    mgr.connections["svc"] = mock_conn

    handlers = mgr.get_tool_handlers()
    expected_name = "mcp__svc__action"

    # 7.1 Handler registered with correct name
    r.record(expected_name in handlers, "handler registered", expected_name, str(list(handlers.keys())))

    # 7.2 Handler is callable
    r.record(callable(handlers.get(expected_name)), "handler is callable", "callable", str(type(handlers.get(expected_name))))

    return r


# ──────────────────────────────────────────────
#  8. close_all cleanup
# ──────────────────────────────────────────────

def evaluate_close_all() -> EvalResult:
    r = EvalResult("close_all Cleanup")

    mgr = McpManager()
    mock_conn = McpConnection("temp", "echo", [])
    mock_conn.tools = []
    mgr.connections["temp"] = mock_conn

    mgr.close_all()
    r.record(len(mgr.connections) == 0, "close_all clears connections", "0", str(len(mgr.connections)))
    r.record(mgr.server_count == 0, "server_count = 0 after close", "0", str(mgr.server_count))

    return r


# ──────────────────────────────────────────────
#  Report generation
# ──────────────────────────────────────────────

def run_full_evaluation():
    evaluators = [
        ("Name Normalization", evaluate_name_normalization),
        ("Tool Name Build/Parse", evaluate_tool_name_ops),
        ("McpManager Mock", evaluate_manager_mock),
        ("Tool Conversion", evaluate_tool_conversion),
        ("Instructions", evaluate_instructions),
        ("Description Truncation", evaluate_description_truncation),
        ("Tool Handlers", evaluate_tool_handlers),
        ("close_all", evaluate_close_all),
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
    print("  MCP Integration Evaluation Report")
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

def test_name_normalization():
    r = evaluate_name_normalization()
    assert r.accuracy >= 0.90, f"Name normalization accuracy {r.accuracy:.1%} < 90%"

def test_tool_name_ops():
    r = evaluate_tool_name_ops()
    assert r.accuracy >= 0.90, f"Tool name ops accuracy {r.accuracy:.1%} < 90%"

def test_manager_mock():
    r = evaluate_manager_mock()
    assert r.accuracy >= 0.90, f"Manager mock accuracy {r.accuracy:.1%} < 90%"

def test_tool_conversion():
    r = evaluate_tool_conversion()
    assert r.accuracy >= 0.90, f"Tool conversion accuracy {r.accuracy:.1%} < 90%"

def test_instructions():
    r = evaluate_instructions()
    assert r.accuracy >= 0.90, f"Instructions accuracy {r.accuracy:.1%} < 90%"

def test_description_truncation():
    r = evaluate_description_truncation()
    assert r.accuracy >= 0.90, f"Description truncation accuracy {r.accuracy:.1%} < 90%"

def test_tool_handlers():
    r = evaluate_tool_handlers()
    assert r.accuracy >= 0.90, f"Tool handlers accuracy {r.accuracy:.1%} < 90%"

def test_close_all():
    r = evaluate_close_all()
    assert r.accuracy == 1.0, f"close_all accuracy {r.accuracy:.1%} < 100%"


if __name__ == "__main__":
    success = run_full_evaluation()
    sys.exit(0 if success else 1)
