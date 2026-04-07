"""
agents/team.py - Swarm 团队模式

实现持久化自主队友（TeammateManager），每个队友运行在独立线程中。
队友之间可以**直接通信**（对等网状拓扑），不仅限于与 lead 通信。

队友生命周期：
1. 工作阶段：执行工具调用循环，处理收件箱消息
2. 空闲阶段：轮询消息和未认领任务，自动认领
3. 关闭阶段：超时或收到关闭请求后退出

设计要点：
- 工具定义从全局 tools/ 包动态过滤（零重复）
- 系统提示注入队友列表，支持 peer-to-peer 寻址
- 通过 MessageBus 的收件箱机制实现对等通信

对应 Claude Code 的 Swarm Team 模式 (utils/swarm/)。
"""

import json
import threading
import time

from bootstrap import state as _root_state
from bootstrap.state import (
    WORKDIR, TEAM_DIR, TASKS_DIR,
    POLL_INTERVAL, IDLE_TIMEOUT,
)
from agents.definitions import get_filtered_tools, GENERAL_TOOLS
from utils.truncate import truncate_result


# 队友专用的额外工具定义（不在全局工具注册表中）
_TEAM_EXTRA_TOOL_DEFS = [
    {
        "name": "send_message",
        "description": (
            "Send a message to another teammate or the lead. "
            "Use teammate's name as the 'to' field. Use 'lead' to message the main agent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient name (teammate name or 'lead')"},
                "content": {"type": "string", "description": "Message content"},
            },
            "required": ["to", "content"],
        },
    },
    {
        "name": "idle",
        "description": "Signal that you have no more work. Enter idle state to wait for messages or new tasks.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "claim_task",
        "description": "Claim an unclaimed task from the task board by ID.",
        "input_schema": {
            "type": "object",
            "properties": {"task_id": {"type": "integer"}},
            "required": ["task_id"],
        },
    },
]


class TeammateManager:
    """
    Swarm 团队管理器。

    管理持久化队友的创建、生命周期和状态跟踪。
    队友之间可以通过 MessageBus 直接通信（对等网状拓扑）。
    """

    def __init__(self, bus, task_mgr):
        TEAM_DIR.mkdir(parents=True, exist_ok=True)
        self.bus = bus
        self.task_mgr = task_mgr
        self.config_path = TEAM_DIR / "config.json"
        self.config = self._load()

    def _load(self) -> dict:
        if self.config_path.exists():
            return json.loads(self.config_path.read_text())
        return {"team_name": "default", "members": []}

    def _save(self):
        self.config_path.write_text(json.dumps(self.config, indent=2))

    def _find(self, name: str) -> dict | None:
        for m in self.config["members"]:
            if m["name"] == name:
                return m
        return None

    def spawn(self, name: str, role: str, prompt: str, agent_type: str = "general") -> str:
        """
        创建并启动一个队友线程。

        agent_type 可以指定内置 Agent 类型（explore/plan/general/verification），
        队友的系统提示和工具集将从 definitions.py 获取。
        """
        member = self._find(name)
        if member:
            if member["status"] not in ("idle", "shutdown"):
                return f"Error: '{name}' is currently {member['status']}"
            member["status"] = "working"
            member["role"] = role
        else:
            member = {"name": name, "role": role, "status": "working", "type": agent_type}
            self.config["members"].append(member)
        self._save()
        threading.Thread(
            target=self._loop, args=(name, role, prompt, agent_type), daemon=True,
        ).start()
        return f"Spawned '{name}' (role: {role}, type: {agent_type})"

    def _set_status(self, name: str, status: str):
        member = self._find(name)
        if member:
            member["status"] = status
            self._save()

    def _build_system_prompt(self, name: str, role: str) -> str:
        """
        构建队友的系统提示词，注入团队上下文和同伴列表。

        这是与重构前的关键差异：队友现在知道其他队友的存在，
        可以通过 send_message 直接与任何同伴通信。
        """
        team_name = self.config["team_name"]
        peers = [
            f"  - {m['name']} ({m['role']}): {m['status']}"
            for m in self.config["members"]
            if m["name"] != name
        ]
        peers_text = "\n".join(peers) if peers else "  (no other teammates)"

        return (
            f"You are '{name}', role: {role}, team: {team_name}, working at {WORKDIR}.\n\n"
            f"Your teammates:\n{peers_text}\n\n"
            f"Communication:\n"
            f"- Use send_message to communicate with ANY teammate by name\n"
            f"- Use send_message with to='lead' to report to the main agent\n"
            f"- Check your inbox regularly for messages from teammates\n\n"
            f"Workflow:\n"
            f"- Complete your assigned task using the available tools\n"
            f"- Coordinate with teammates when tasks overlap\n"
            f"- Use idle when you have no more work to do\n"
            f"- You may auto-claim unclaimed tasks from the task board"
        )

    def _build_teammate_tools(self, agent_type: str = "general") -> tuple[list, dict]:
        """
        构建队友的工具集：基于 Agent 类型的核心工具 + 队友专用工具。

        复用 definitions.py 的类型配置——explore 队友只有只读工具，
        general 队友有全部工具。加上队友特有的通信工具。
        """
        from agents.definitions import get_agent_config
        try:
            config = get_agent_config(agent_type)
            allowed_tools = config["allowed_tools"]
        except ValueError:
            allowed_tools = GENERAL_TOOLS
        core_defs, core_handlers = get_filtered_tools(allowed_tools)
        all_defs = core_defs + _TEAM_EXTRA_TOOL_DEFS
        return all_defs, core_handlers

    def _loop(self, name: str, role: str, prompt: str, agent_type: str = "general"):
        """队友的主工作循环（运行在独立线程中）"""
        # 如果指定了 Agent 类型，混合使用该类型的系统提示
        from agents.definitions import get_agent_config
        type_prompt = ""
        try:
            config = get_agent_config(agent_type)
            type_prompt = config["system_prompt"] + "\n\n"
        except ValueError:
            pass

        sys_prompt = type_prompt + self._build_system_prompt(name, role)
        tool_defs, core_handlers = self._build_teammate_tools(agent_type)
        messages = [{"role": "user", "content": prompt}]

        # 队友专用工具处理器（需要闭包访问 self）
        def handle_team_tool(block):
            if block.name == "idle":
                return "Entering idle phase."
            elif block.name == "claim_task":
                return self.task_mgr.claim(block.input["task_id"], name)
            elif block.name == "send_message":
                return self.bus.send(name, block.input["to"], block.input["content"])
            return None  # 不是队友工具

        while True:
            # === 工作阶段 ===
            idle_requested = False
            for _ in range(50):
                # 检查收件箱（来自 lead 或其他队友的消息）
                inbox = self.bus.read_inbox(name)
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})

                try:
                    response = _root_state.llm.chat(sys_prompt, messages, tool_defs)
                except Exception:
                    self._set_status(name, "shutdown")
                    return

                messages.append({"role": "assistant", "content": response.content})
                if response.stop_reason != "tool_use":
                    break

                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue

                    # 尝试队友专用工具
                    team_output = handle_team_tool(block)
                    if team_output is not None:
                        output = team_output
                        if block.name == "idle":
                            idle_requested = True
                    else:
                        # 使用核心工具（从全局注册表复用）
                        handler = core_handlers.get(block.name)
                        try:
                            output = str(handler(**block.input)) if handler else f"Unknown: {block.name}"
                        except Exception as e:
                            output = f"Error: {e}"

                    print(f"  [{name}] {block.name}: {str(output)[:120]}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": truncate_result(str(output)),
                    })
                messages.append({"role": "user", "content": results})
                if idle_requested:
                    break

            # === 空闲阶段：轮询消息和未认领任务 ===
            self._set_status(name, "idle")
            resume = False
            for _ in range(IDLE_TIMEOUT // max(POLL_INTERVAL, 1)):
                time.sleep(POLL_INTERVAL)

                # 检查收件箱（来自 lead 或其他队友）
                inbox = self.bus.read_inbox(name)
                if inbox:
                    for msg in inbox:
                        if msg.get("type") == "shutdown_request":
                            self._set_status(name, "shutdown")
                            return
                        messages.append({"role": "user", "content": json.dumps(msg)})
                    resume = True
                    break

                # 自动认领未分配任务
                unclaimed = []
                if TASKS_DIR.exists():
                    for f in sorted(TASKS_DIR.glob("task_*.json")):
                        t = json.loads(f.read_text())
                        if t.get("status") == "pending" and not t.get("owner") and not t.get("blockedBy"):
                            unclaimed.append(t)
                if unclaimed:
                    task = unclaimed[0]
                    self.task_mgr.claim(task["id"], name)
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
            # 刷新系统提示（队友列表可能已变化）
            sys_prompt = self._build_system_prompt(name, role)

    def list_all(self) -> str:
        if not self.config["members"]:
            return "No teammates."
        lines = [f"Team: {self.config['team_name']}"]
        for m in self.config["members"]:
            lines.append(f"  {m['name']} ({m['role']}): {m['status']}")
        return "\n".join(lines)

    def member_names(self) -> list:
        return [m["name"] for m in self.config["members"]]
