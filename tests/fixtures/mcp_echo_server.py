"""
一个极简但符合规范的 MCP 服务器（stdio 传输），用于测试 MCP 客户端。

实现 Model Context Protocol (MCP) 的 JSON-RPC 子集：
  - initialize              -> capabilities + serverInfo + instructions
  - notifications/initialized（通知，无 id，无响应）
  - tools/list              -> 工具定义
  - tools/call              -> 调用工具

提供的工具：
  - echo(message)        -> 原样返回 message
  - add(a, b)            -> 返回 a + b 的文本
  - hang()               -> 永久阻塞（用于测试客户端的调用超时）
  - flood_stderr(n)      -> 向 stderr 写 n 行（用于测试管道死锁防护）

该服务器是"真实"的 MCP 服务器（完整实现协议），但零外部依赖，
任何带 Python 的环境都能跑，适合确定性测试与阅读学习。
"""
import json
import sys
import time

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the message verbatim",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "add",
        "description": "Add two numbers and return the sum",
        "inputSchema": {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
        },
    },
    {
        "name": "hang",
        "description": "Block forever (for testing client call timeout)",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "flood_stderr",
        "description": "Write many lines to stderr (for testing pipe deadlock protection)",
        "inputSchema": {
            "type": "object",
            "properties": {"n": {"type": "integer"}},
        },
    },
]


def _handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "echo-test-server", "version": "1.0.0"},
        "instructions": "Use echo to test roundtrip, add to test math.",
    }


def _handle_tool_call(name, arguments):
    if name == "echo":
        return {
            "content": [{"type": "text", "text": arguments.get("message", "")}],
            "isError": False,
        }
    if name == "add":
        a = arguments.get("a", 0)
        b = arguments.get("b", 0)
        return {
            "content": [{"type": "text", "text": str(a + b)}],
            "isError": False,
        }
    if name == "hang":
        time.sleep(3600)  # 有效"永久"阻塞，测试客户端超时
        return {"content": [{"type": "text", "text": "never"}], "isError": False}
    if name == "flood_stderr":
        n = int(arguments.get("n", 10000))
        for i in range(n):
            # 逐行 flush，快速填满管道缓冲区，验证客户端 stderr 消费线程
            print(f"stderr log line {i}", file=sys.stderr, flush=True)
        return {
            "content": [{"type": "text", "text": f"wrote {n} lines to stderr"}],
            "isError": False,
        }
    return {
        "content": [{"type": "text", "text": f"unknown tool: {name}"}],
        "isError": True,
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        # 通知（无 id）不响应
        if msg_id is None:
            continue

        if method == "initialize":
            result = _handle_initialize(params)
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            result = _handle_tool_call(params.get("name"), params.get("arguments", {}))
        else:
            result = {}

        print(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}), flush=True)


if __name__ == "__main__":
    main()
