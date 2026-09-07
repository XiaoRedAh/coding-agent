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
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from runtime.state import PROJECT_DIR


# ──────────────────────────────────────────────
#  配置（超时值来自 config/defaults.yaml mcp 节）
# ──────────────────────────────────────────────

from runtime.state import settings as _settings

MCP_CONFIG_PATH = PROJECT_DIR / "mcp.json"
MCP_TOOL_TIMEOUT = _settings.mcp.tool_timeout      # 工具调用超时（秒）
MCP_CONNECT_TIMEOUT = _settings.mcp.connect_timeout  # 连接超时（秒）


def _normalize_name(name: str) -> str:
    """将服务器/工具名称标准化为合法标识符。

    连续的非字母数字字符（含下划线、连字符、点、空格等）折叠为单个下划线，
    避免名称本身含双下划线时与 mcp__<server>__<tool> 的分隔符产生歧义。
    """
    return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")


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
        self._response_queue: queue.Queue | None = None  # stdout 读取线程投递的响应
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def _build_command(self) -> tuple[list[str] | str, bool]:
        """构造启动命令，返回 (cmd, use_shell)。

        Windows 下 npx/npm/yarn 等是 .cmd/.bat shim，CreateProcess 无法直接执行，
        必须经 shell（cmd.exe）解析；其余（python.exe、node.exe 等真实可执行文件）
        保持 shell=False，避免 shell 注入与转义问题。
        """
        if os.name == "nt":
            resolved = shutil.which(self.command)
            if resolved and resolved.lower().endswith((".cmd", ".bat")):
                # list2cmdline 将列表转成 cmd.exe 可正确解析的引用串
                return subprocess.list2cmdline([resolved] + self.args), True
        return [self.command] + self.args, False

    def connect(self) -> bool:
        """启动 MCP 服务器进程并完成初始化握手"""
        try:
            full_env = {**os.environ, **(self.env or {})}
            cmd, use_shell = self._build_command()
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                text=True,
                bufsize=1,
                shell=use_shell,
                encoding="utf-8",     # MCP JSON-RPC 是 UTF-8；Windows 默认 GBK 会解码崩溃
                errors="replace",     # 防个别坏字节炸掉读取线程
            )

            # 启动后台读取线程：stdout 持续读入队列（配合超时），
            # stderr 持续消费（防止管道缓冲区写满导致子进程死锁）
            self._response_queue = queue.Queue()
            self._stdout_thread = threading.Thread(
                target=self._read_stdout_loop, daemon=True)
            self._stderr_thread = threading.Thread(
                target=self._read_stderr_loop, daemon=True)
            self._stdout_thread.start()
            self._stderr_thread.start()

            # 发送 initialize 请求（连接阶段用 connect_timeout）
            init_result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "xiaoagent", "version": "1.0.0"},
            }, timeout=MCP_CONNECT_TIMEOUT)
            if init_result is None:
                self.close()
                return False

            # 提取 instructions
            self.instructions = init_result.get("instructions")

            # 发送 initialized 通知
            self._send_notification("notifications/initialized", {})

            # 获取工具列表（发现失败 = 连接失败，避免注册零工具的空连接）
            tools_result = self._send_request(
                "tools/list", {}, timeout=MCP_CONNECT_TIMEOUT)
            if tools_result is None or "tools" not in tools_result:
                print(f"  [mcp:{self.name}] tools/list failed, treating as connection failure")
                self.close()
                return False
            self.tools = tools_result["tools"]

            print(f"  [mcp:{self.name}] connected, {len(self.tools)} tools available")
            return True
        except Exception as e:
            print(f"  [mcp:{self.name}] connection failed: {e}")
            self.close()
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

    def _send_request(self, method: str, params: dict, timeout: float | None = None) -> dict | None:
        """发送 JSON-RPC 请求并等待响应（带超时，避免 MCP 挂起卡死主循环）"""
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
            except Exception as e:
                print(f"  [mcp:{self.name}] request write error: {e}")
                return None

            # 从响应队列读取（读取线程已把 stdout 行投递进来）
            timeout = MCP_TOOL_TIMEOUT if timeout is None else timeout
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    print(f"  [mcp:{self.name}] timeout waiting for {method} response")
                    return None
                try:
                    line = self._response_queue.get(timeout=remaining)
                except queue.Empty:
                    print(f"  [mcp:{self.name}] timeout waiting for {method} response")
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

    def _send_notification(self, method: str, params: dict):
        """发送 JSON-RPC 通知（无响应）"""
        with self._lock:
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

    def _read_stdout_loop(self):
        """后台线程：持续读取 stdout 行并投递到响应队列。

        用独立线程读取，主线程才能在 queue.get(timeout) 上实现超时；
        否则阻塞的 readline() 会让 MCP 挂起永久卡死主循环。
        """
        stream = self.process.stdout
        try:
            while True:
                line = stream.readline()
                if not line:            # EOF：进程退出或管道关闭
                    break
                self._response_queue.put(line)
        except Exception:
            pass

    def _read_stderr_loop(self):
        """后台线程：持续消费 stderr，防止管道缓冲区写满导致子进程死锁。

        MCP 服务器（如 npx）常往 stderr 写日志/下载进度，若不消费，
        写满约 64KB 管道缓冲区后子进程写阻塞，反过来触发主循环卡死。
        这里静默丢弃（如需诊断可改为记录到日志）。
        """
        stream = self.process.stderr
        try:
            while True:
                chunk = stream.readline()
                if not chunk:
                    break
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
        from engine.results import ToolResult
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
                                return ToolResult.failure(
                                    f"MCP Error: {content[0].get('text', 'Unknown error')}",
                                    "mcp_error")
                            return ToolResult.failure(
                                "MCP Error: Unknown error", "mcp_error")
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
