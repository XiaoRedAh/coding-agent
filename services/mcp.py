"""
services/mcp.py - MCP（Model Context Protocol）集成

实现与 MCP 服务器的通信，将外部服务的工具转换为 Anthropic Tool 格式，
注入到主 Agent 的工具池中。

核心功能：
1. 配置加载 — 从 .xiaoagent/mcp.json 读取服务器配置
2. 连接管理 — 通过 stdio 启动本地 MCP 服务器进程
3. 工具发现 — 调用 tools/list 获取服务器提供的工具
4. 工具转换 — MCP 工具 → Anthropic Tool 格式（mcp__server__tool 命名）
5. 工具调用 — 将 LLM 的 tool_use 请求转发到对应的 MCP 服务器
6. Instructions — 将服务器的使用说明注入 system prompt

简化说明（对比 cc）：
- cc 支持 7 种传输协议，我们只支持 stdio（覆盖最常用场景）
- cc 有 6 层配置来源，我们只有项目级 .xiaoagent/mcp.json
- cc 有 OAuth 认证流程，我们暂不支持
- cc 有延迟加载和缓存优化，我们全量加载

对应 Claude Code 的 services/mcp/ 目录（3349 行 client.ts 的精简版）。
"""

import json
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from bootstrap.state import PROJECT_DIR


# ──────────────────────────────────────────────
#  配置
# ──────────────────────────────────────────────

MCP_CONFIG_PATH = PROJECT_DIR / "mcp.json"
MCP_TOOL_TIMEOUT = 120  # 工具调用超时（秒）
MCP_CONNECT_TIMEOUT = 30  # 连接超时（秒）


def _normalize_name(name: str) -> str:
    """将服务器/工具名称标准化为合法标识符"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_")


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """构建 MCP 工具的全名：mcp__<server>__<tool>"""
    return f"mcp__{_normalize_name(server_name)}__{_normalize_name(tool_name)}"


def parse_mcp_tool_name(full_name: str) -> tuple[str, str] | None:
    """从全名解析出 server_name 和 tool_name"""
    if not full_name.startswith("mcp__"):
        return None
    parts = full_name[5:].split("__", 1)
    if len(parts) != 2:
        return None
    return parts[0], parts[1]


# ──────────────────────────────────────────────
#  MCP 服务器连接（stdio 传输）
# ──────────────────────────────────────────────

class McpConnection:
    """
    与单个 MCP 服务器的 stdio 连接。

    通过子进程启动 MCP 服务器，使用 JSON-RPC over stdin/stdout 通信。
    """

    def __init__(self, name: str, command: str, args: list[str] = None, env: dict = None):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self.process: subprocess.Popen | None = None
        self.request_id = 0
        self._lock = threading.Lock()
        self.tools: list[dict] = []          # 服务器提供的工具列表
        self.instructions: str | None = None  # 服务器的使用说明

    def connect(self) -> bool:
        """启动 MCP 服务器进程并完成初始化握手"""
        try:
            import os
            full_env = {**os.environ, **(self.env or {})}
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                text=True,
                bufsize=1,
            )
            # 发送 initialize 请求
            init_result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "xiaoagent", "version": "1.0.0"},
            })
            if init_result is None:
                return False

            # 提取 instructions
            info = init_result.get("serverInfo", {})
            self.instructions = init_result.get("instructions")

            # 发送 initialized 通知
            self._send_notification("notifications/initialized", {})

            # 获取工具列表
            tools_result = self._send_request("tools/list", {})
            if tools_result and "tools" in tools_result:
                self.tools = tools_result["tools"]

            print(f"  [mcp:{self.name}] connected, {len(self.tools)} tools available")
            return True
        except Exception as e:
            print(f"  [mcp:{self.name}] connection failed: {e}")
            return False

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 MCP 服务器上的工具"""
        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result is None:
            return {"isError": True, "content": [{"type": "text", "text": "MCP call failed"}]}
        return result

    def close(self):
        """关闭连接，终止服务器进程"""
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _send_request(self, method: str, params: dict) -> dict | None:
        """发送 JSON-RPC 请求并等待响应"""
        with self._lock:
            if not self.process or self.process.poll() is not None:
                return None
            self.request_id += 1
            request = {
                "jsonrpc": "2.0",
                "id": self.request_id,
                "method": method,
                "params": params,
            }
            try:
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
                # 读取响应（简单的逐行读取，忽略通知）
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        return None
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        response = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # 跳过通知（没有 id 字段）
                    if "id" not in response:
                        continue
                    if response.get("id") == self.request_id:
                        if "error" in response:
                            err = response["error"]
                            print(f"  [mcp:{self.name}] error: {err.get('message', err)}")
                            return None
                        return response.get("result", {})
            except Exception as e:
                print(f"  [mcp:{self.name}] request error: {e}")
                return None

    def _send_notification(self, method: str, params: dict):
        """发送 JSON-RPC 通知（无响应）"""
        if not self.process or self.process.poll() is not None:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            self.process.stdin.write(json.dumps(notification) + "\n")
            self.process.stdin.flush()
        except Exception:
            pass


# ──────────────────────────────────────────────
#  MCP 管理器
# ──────────────────────────────────────────────

class McpManager:
    """
    管理所有 MCP 服务器连接。

    负责：
    1. 加载配置 → 建立连接
    2. 工具发现 → 转换为 Anthropic Tool 格式
    3. 工具调用路由 → 转发到对应服务器
    4. Instructions 收集 → 注入 system prompt
    5. 生命周期 → 优雅关闭所有连接
    """

    def __init__(self):
        self.connections: dict[str, McpConnection] = {}

    def load_and_connect(self):
        """从配置文件加载 MCP 服务器并建立连接"""
        if not MCP_CONFIG_PATH.exists():
            return

        try:
            config = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[mcp] failed to load config: {e}")
            return

        servers = config.get("mcpServers", {})
        for name, server_config in servers.items():
            if server_config.get("disabled", False):
                continue
            command = server_config.get("command")
            if not command:
                print(f"[mcp:{name}] no command specified, skipping")
                continue
            args = server_config.get("args", [])
            env = server_config.get("env")

            conn = McpConnection(name, command, args, env)
            if conn.connect():
                self.connections[name] = conn
            else:
                conn.close()

    def get_tool_definitions(self) -> list[dict]:
        """获取所有 MCP 工具的 Anthropic Tool 格式定义"""
        defs = []
        for server_name, conn in self.connections.items():
            for tool in conn.tools:
                full_name = build_mcp_tool_name(server_name, tool["name"])
                desc = tool.get("description", "")
                if len(desc) > 2048:
                    desc = desc[:2045] + "..."
                defs.append({
                    "name": full_name,
                    "description": f"[MCP: {server_name}] {desc}",
                    "input_schema": tool.get("inputSchema", {
                        "type": "object", "properties": {},
                    }),
                })
        return defs

    def get_tool_handlers(self) -> dict:
        """获取所有 MCP 工具的处理函数映射"""
        handlers = {}
        for server_name, conn in self.connections.items():
            for tool in conn.tools:
                full_name = build_mcp_tool_name(server_name, tool["name"])
                # 闭包捕获 conn 和 tool_name
                def make_handler(c, tn):
                    def handler(**kwargs):
                        result = c.call_tool(tn, kwargs)
                        if result.get("isError"):
                            content = result.get("content", [])
                            if content and isinstance(content, list):
                                return f"MCP Error: {content[0].get('text', 'Unknown error')}"
                            return "MCP Error: Unknown error"
                        content = result.get("content", [])
                        if content and isinstance(content, list):
                            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                            return "\n".join(texts) if texts else "(no output)"
                        return str(content)
                    return handler
                handlers[full_name] = make_handler(conn, tool["name"])
        return handlers

    def get_instructions(self) -> str:
        """收集所有已连接服务器的 instructions，拼接为 system prompt 片段"""
        blocks = []
        for name, conn in self.connections.items():
            if conn.instructions:
                blocks.append(f"## {name}\n{conn.instructions}")
        if not blocks:
            return ""
        return "# MCP Server Instructions\n\n" + "\n\n".join(blocks)

    def close_all(self):
        """关闭所有 MCP 连接"""
        for name, conn in self.connections.items():
            print(f"  [mcp:{name}] closing...")
            conn.close()
        self.connections.clear()

    @property
    def server_count(self) -> int:
        return len(self.connections)

    @property
    def tool_count(self) -> int:
        return sum(len(c.tools) for c in self.connections.values())
