"""
agents/team.py - 团队队友管理器

实现持久化自主队友（TeammateManager），每个队友运行在独立线程中。
队友拥有完整的工作-空闲-关闭生命周期：
1. 工作阶段：执行工具调用循环，处理收件箱消息
2. 空闲阶段：轮询消息和未认领任务，自动认领可用任务
3. 关闭阶段：超时无活动或收到关闭请求后退出
"""

import json
import threading
import time

from bootstrap.state import (
    WORKDIR, TEAM_DIR, TASKS_DIR,
    client, MODEL,
    POLL_INTERVAL, IDLE_TIMEOUT,
)
from tools.BashTool import handle as run_bash
from tools.FileReadTool import handle as run_read
from tools.FileWriteTool import handle as run_write
from tools.FileEditTool import handle as run_edit


class TeammateManager:
    """团队队友管理器，负责队友的创建、生命周期管理和状态跟踪"""

    def __init__(self, bus, task_mgr):
        """
        初始化团队管理器。

        Args:
            bus: MessageBus 实例
            task_mgr: TaskManager 实例
        """
        TEAM_DIR.mkdir(exist_ok=True)
        self.bus = bus
        self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = self._load()
        self.threads = {}

    def _load(self) -> dict:
        """加载团队配置文件"""
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save(self):
        """保存团队配置到文件"""
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict:
        """按名称查找队友"""
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str) -> str:
        """创建并启动一个队友线程"""
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working"}
            self.config["members"].append(member)
        self._save()
        threading.Thread(
            target=self._loop, args=(name, role, prompt), daemon=True,
        ).start()
        return f"Spawned '{name}' (role: {role})"

    def _set_status(self, name: str, status: str):
        """更新队友状态并保存"""
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()

    def _loop(self, name: str, role: str, prompt: str):
        """队友的主工作循环（运行在独立线程中）"""
        team_name = self.config["team_name"]
        sys_prompt = (
            f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
            f"Use idle when done with current work. You may auto-claim tasks."
        )
        messages = [{"role": "user", "content": prompt}]

        tools = [
            {
                "name": "bash",
                "description": "Run command.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            {
                "name": "read_file",
                "description": "Read file.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            {
                "name": "write_file",
                "description": "Write file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Edit file.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "send_message",
                "description": "Send message.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["to", "content"],
                },
            },
            {
                "name": "idle",
                "description": "Signal no more work.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "claim_task",
                "description": "Claim task by ID.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "integer"}},
                    "required": ["task_id"],
                },
            },
        ]

        while True:
            # === 工作阶段 ===
            for _ in range(50):
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})

                try:
                    response = client.messages.create(
                        model=MODEL,
                        system=sys_prompt,
                        messages=messages,
                        tools=tools,
                        max_tokens=8000,
                    )
                except Exception:
                    self._set_status(name, "shutdown")
                    return

                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    break

                results = []
                idle_requested = False
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "idle":
                            idle_requested = True
                            output = "Entering idle phase."
                        elif block.name == "claim_task":
                            output = self.task_mgr.claim(
                                block.input["task_id"], name,
                            )
                        elif block.name == "send_message":
                            output = self.bus.send(
                                name, block.input["to"], block.input["content"],
                            )
                        else:
                            dispatch = {
                                "bash":       lambda **kw: run_bash(kw["command"]),
                                "read_file":  lambda **kw: run_read(kw["path"]),
                                "write_file": lambda **kw: run_write(kw["path"], kw["content"]),
                                "edit_file":  lambda **kw: run_edit(kw["path"], kw["old_text"], kw["new_text"]),
                            }
                            output = dispatch.get(
                                block.name, lambda **kw: "Unknown",
                            )(**block.input)
                        print(f"  [{name}] {block.name}: {str(output)[:120]}")
                        results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": str(output),
                        })
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break

            # === 空闲阶段 ===
            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append(
                            {"role": "user", "content": json.dumps(msg)},
                        )
                    resume = True
                    break
                unclaimed = []
                for f in sorted(TASKS_DIR.glob("task_*.json")):
                    t = json.loads(f.read_text())
                    if (
                        t.get("status") == "pending"
                        and not t.get("owner")
                        and not t.get("blockedBy")
                    ):
                        unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
                    if len(messages) <= 3:
                        messages.insert(0, {
                            "role": "user",
                            "content": f"<identity>You are '{name}', role: {role}, team: {team_name}.</identity>",
                        })
                        messages.insert(1, {
                            "role": "assistant",
                            "content": f"I am {name}. Continuing.",
                        })
                    messages.append({
                        "role": "user",
                        "content": f"<auto-claimed>Task #{task['id']}: {task['subject']}\n{task.get('description', '')}</auto-claimed>",
                    })
                    messages.append({
                        "role": "assistant",
                        "content": f"Claimed task #{task['id']}. Working on it.",
                    })
                    resume = True
                    break

            if not resume:
                self._set_status(name, "shutdown")
                return
            self._set_status(name, "working")

    def list_all(self) -> str:
        """列出所有队友及其状态"""
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        """获取所有队友名称列表"""
        return [m["name"] for m in self.config["members"]]
