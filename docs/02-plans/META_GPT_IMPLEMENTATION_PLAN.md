# MetaGPT 简化版复现实现计划

> 文档版本：v4（采纳用户反馈优化版）

---

## 0. 核心设计原则

1. **每个组件必须被用到** — 建了不用比不建更糟糕
2. **复用现有能力** — run_shell、agent_loop、write_file 等工具已实现，直接复用
3. **同步优先** — 与项目主体保持一致，避免 async/sync 混用
4. **真 Pub-Sub** — Environment 消息路由是 MetaGPT 的灵魂，必须真正使用

---

## 1. 整体架构

### 1.1 与 Coordinator 模式的对比

| 维度 | Coordinator（现有） | MetaGPT（本版） |
|------|---------------------|----------------|
| 拓扑 | 星形，并行派发 Worker | 流水线，顺序执行 |
| 消息传递 | Worker 独立，无共享消息池 | Environment 作为消息路由中枢 |
| 订阅机制 | 无 | Role.watch + msg_buffer |
| 输出约束 | 无 | 角色专属 Markdown 模板 |
| Worker 执行 | agent_loop + 工具 | agent_loop + 工具 |
| 自测机制 | 无 | Executable Feedback 循环 |

### 1.2 核心组件关系

```
┌─────────────────────────────────────────────────────────────────────┐
│                       MetaGPTPipeline                                │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                    Environment                                 │  │
│  │  publish_message(msg) → 遍历 member_addrs 路由到目标 Role      │  │
│  │  - roles: {name → Role}                                       │  │
│  │  - member_addrs: {Role → set of addresses}                    │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              ↑                                       │
│            ┌─────────────────┼─────────────────┐                     │
│            │                 │                 │                     │
│     ┌──────┴──────┐   ┌──────┴──────┐   ┌──────┴──────┐              │
│     │ Analyst     │   │ Engineer    │   │ Tester      │              │
│     │ Designer    │   │             │   │             │              │
│     └──────┬──────┘   └──────┬──────┘   └──────┬──────┘              │
│            │                 │                 │                     │
│     rc.watch={"user_       rc.watch={"Write  rc.watch={"Write      │
│              requirement"}   AnalysisReport"}  Code"}               │
└────────────┼─────────────────┼─────────────────┼─────────────────────┘
             │                 │                 │
             ↓                 ↓                 ↓
        MessagePool        MessagePool       MessagePool
        (msg_buffer)       (msg_buffer)      (msg_buffer)
```

### 1.3 消息流（真 Pub-Sub）

```
用户输入
    ↓
Environment.publish(user_requirement, send_to=*)
    ↓
AnalystDesigner.msg_buffer.push(msg)  ← send_to=* 匹配所有
AnalystDesigner.run() → _observe() 匹配 watch → 执行 → publish(WriteAnalysisReport)
    ↓
Environment.publish(WriteAnalysisReport, send_to={Engineer})
    ↓
Engineer.msg_buffer.push(msg)  ← send_to 包含 Engineer
Engineer.run() → _observe() 匹配 watch → 执行 → publish(WriteCode)
    ↓
Environment.publish(WriteCode, send_to={Tester})
    ↓
Tester.msg_buffer.push(msg)  ← send_to 包含 Tester
Tester.run() → _observe() 匹配 watch → 执行 → publish(TestReport)
    ↓
Pipeline 收集结果，输出报告
```

---

## 2. 目录结构

```
agents/
  ├── __init__.py              # 修改：导出 MetaGPT 相关组件
  ├── coordinator.py            # 不变
  ├── subagent.py               # 不变
  ├── definitions.py            # 不变
  └── metagpt/                  # 新增：MetaGPT 简化版
      ├── __init__.py
      ├── message.py             # Message + MessageType
      ├── environment.py         # Environment（真正用于路由）
      ├── role.py                # Role 基类（同步版）
      ├── action.py              # Action 基类（同步版）
      ├── roles/
      │   ├── __init__.py
      │   ├── analyst.py         # AnalystDesigner（纯 LLM 调用）
      │   ├── engineer.py        # Engineer（走 agent_loop + write_file）
      │   └── tester.py          # Tester（走 agent_loop + run_shell）
      ├── templates/
      │   ├── __init__.py
      │   └── output_templates.py # 三角色输出 Markdown 模板
      └── pipeline.py             # MetaGPTPipeline 主类
```

---

## 3. 核心组件详解

### 3.1 Message 和 MessageType

```python
# agents/metagpt/message.py

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid

class MessageType(str, Enum):
    """消息类型枚举，与 Role.watch 对应"""
    USER_REQUIREMENT = "user_requirement"
    WRITE_ANALYSIS_REPORT = "WriteAnalysisReport"  # Analyst 发布
    WRITE_CODE = "WriteCode"                       # Engineer 发布
    RUN_TESTS = "RunTests"                         # Tester 发布

MESSAGE_ROUTE_TO_ALL = "*"

@dataclass
class Message:
    """结构化消息"""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    content: str = ""                    # 消息文本内容
    role: str = "system"                 # system/user/assistant
    cause_by: str = ""                   # 产生此消息的 Action 名称
    sent_from: str = ""                  # 发送者角色名
    send_to: set[str] = field(default_factory=lambda: {MESSAGE_ROUTE_TO_ALL})
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def dump(self) -> str:
        import json
        return json.dumps({
            "id": self.id,
            "content": self.content,
            "role": self.role,
            "cause_by": self.cause_by,
            "sent_from": self.sent_from,
            "send_to": list(self.send_to),
            "timestamp": self.timestamp.isoformat(),
        }, ensure_ascii=False)
```

### 3.2 Environment（真用于路由）

```python
# agents/metagpt/environment.py

from typing import Dict, Set, Optional
import threading
from agents.metagpt.message import Message, MESSAGE_ROUTE_TO_ALL

class Environment:
    """
    环境：管理角色和消息路由

    核心职责：
    1. 维护 roles 字典
    2. 维护 member_addrs（角色 → 可接收地址）
    3. publish_message() 实现真正的消息路由
    """

    def __init__(self):
        self.roles: Dict[str, "Role"] = {}
        self.member_addrs: Dict["Role", Set[str]] = {}
        self._lock = threading.Lock()

    def add_role(self, role: "Role"):
        """添加角色到环境"""
        with self._lock:
            self.roles[role.name] = role
            role.set_environment(self)
            # 默认订阅：自己的名字 + 广播地址
            self.member_addrs[role] = {role.name, MESSAGE_ROUTE_TO_ALL}

    def set_addresses(self, role: "Role", addresses: Set[str]):
        """设置角色的订阅地址"""
        with self._lock:
            self.member_addrs[role] = addresses

    def publish_message(self, message: Message) -> bool:
        """
        发布消息到目标角色

        路由逻辑：
        - 如果消息 send_to 包含 MESSAGE_ROUTE_TO_ALL，发给所有角色
        - 否则发给 send_to 与 member_addrs 有交集的角色
        """
        with self._lock:
            found = False
            for role, addrs in self.member_addrs.items():
                if self._is_send_to(message, addrs):
                    role.put_message(message)
                    found = True
            return found

    def _is_send_to(self, message: Message, addrs: Set[str]) -> bool:
        """检查消息是否应该发送给这个地址集合"""
        if MESSAGE_ROUTE_TO_ALL in addrs:
            return True
        # 有交集就发送
        if message.send_to & addrs:
            return True
        return False

    def get_role(self, name: str) -> Optional["Role"]:
        return self.roles.get(name)
```

### 3.3 Role 基类（同步版）

```python
# agents/metagpt/role.py

from typing import List, Set, Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from agents.metagpt.environment import Environment
    from agents.metagpt.action import Action

class RoleContext:
    """角色运行时上下文"""
    def __init__(self):
        self.msg_buffer: List["Message"] = []
        self.memory: List["Message"] = []
        self.watch: Set[str] = set()       # 关注的消息类型
        self.state: int = -1
        self.env: Optional["Environment"] = None

class Role:
    """
    角色基类

    核心方法：
    - run(): 从 msg_buffer 取消息 → 执行 Action → 发布结果到 Environment
    - put_message(msg): 将消息放入接收队列
    - publish_message(msg): 将消息发布到环境
    - _observe(): 从 msg_buffer 筛选关注的消息
    """

    def __init__(self, name: str, profile: str, goal: str, constraints: str = ""):
        self.name = name
        self.profile = profile
        self.goal = goal
        self.constraints = constraints
        self.actions: List["Action"] = []
        self.rc = RoleContext()
        self._llm = None

    def set_environment(self, env: "Environment"):
        self.rc.env = env

    def set_llm(self, llm):
        self._llm = llm

    def _get_prefix(self) -> str:
        return f"You are {self.profile}, named {self.name}, your goal is {self.goal}."

    def put_message(self, msg: "Message"):
        """将消息放入接收队列"""
        self.rc.msg_buffer.append(msg)

    def publish_message(self, msg: "Message"):
        """将消息发布到环境"""
        if not self.rc.env:
            return
        msg.sent_from = self.name
        self.rc.env.publish_message(msg)

    def _observe(self) -> List["Message"]:
        """
        观察消息队列，筛选关注的消息

        过滤条件（两个都要满足）：
        1. cause_by 在 watch 中（由特定 Action 产生）
        2. send_to 包含自己的名字（定向消息）
        """
        if not self.rc.msg_buffer:
            return []

        news = self.rc.msg_buffer
        self.rc.msg_buffer = []

        # 过滤出关注的消息
        self.rc.news = [
            n for n in news
            if (n.cause_by in self.rc.watch or self.name in n.send_to)
        ]

        # 加入记忆
        self.rc.memory.extend(self.rc.news)

        return self.rc.news

    def run(self) -> "Message":
        """
        角色主循环：从 msg_buffer 取消息 → 执行 Action → 发布结果
        """
        # 观察：获取需要处理的消息
        if not self._observe():
            return None  # 没有新消息

        # 执行动作
        if not self.actions:
            return Message(content="No actions available", role="assistant", sent_from=self.name)

        response = self.actions[0].run(self.rc.memory)

        # 发布响应消息到 Environment（由 Environment 路由）
        self.publish_message(response)

        return response
```

### 3.4 Action 基类

```python
# agents/metagpt/action.py

from abc import ABC, abstractmethod
from typing import List
from agents.metagpt.message import Message

class Action(ABC):
    """Action 是角色的原子操作单元"""

    name: str = ""

    def __init__(self, llm=None):
        self._llm = llm

    def set_llm(self, llm):
        self._llm = llm

    @abstractmethod
    def run(self, memory: List[Message]) -> Message:
        """执行 Action，返回结果 Message"""
        raise NotImplementedError
```

---

## 4. 三角色实现

### 4.1 角色职责总览

| 角色 | 订阅（watch） | 发布 | 执行方式 | 输出 |
|------|--------------|------|---------|------|
| AnalystDesigner | user_requirement | WriteAnalysisReport | 直接 LLM 调用 | analysis_report.md |
| Engineer | WriteAnalysisReport | WriteCode | agent_loop + write_file | code/ 目录文件 |
| Tester | WriteCode | RunTests | agent_loop + run_shell | test_report.md |

### 4.2 AnalystDesigner

```python
# agents/metagpt/roles/analyst.py

from typing import List
from agents.metagpt.role import Role, RoleContext
from agents.metagpt.action import Action
from agents.metagpt.message import Message, MessageType
from agents.metagpt.templates.output_templates import ANALYST_TEMPLATE

class WriteAnalysisReport(Action):
    """生成需求分析报告"""

    name = MessageType.WRITE_ANALYSIS_REPORT.value

    def run(self, memory: List[Message]) -> Message:
        # 获取用户原始需求
        user_requirement = ""
        for msg in memory:
            if msg.cause_by == MessageType.USER_REQUIREMENT.value:
                user_requirement = msg.content
                break

        if not user_requirement:
            return Message(
                content="Error: No user requirement found",
                role="assistant",
                cause_by=self.name
            )

        # 调用 LLM 生成分析报告
        from bootstrap import state
        prompt = f"""## User Requirement
{user_requirement}

{ANALYST_TEMPLATE}

请按照上述模板生成 analysis_report.md 文件内容。"""

        response = state.llm.chat(
            system=f"You are an Analyst Designer. {self._llm._get_prefix() if hasattr(self._llm, '_get_prefix') else ''}",
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            stream=False,
        )

        return Message(
            content=response.content if hasattr(response, 'content') else str(response),
            role="assistant",
            cause_by=self.name,
            send_to={MessageType.WRITE_CODE.value},  # 定向发给 Engineer
            metadata={"files": ["analysis_report.md"]}
        )


class AnalystDesigner(Role):
    """分析师/设计者角色"""

    def __init__(self, llm=None):
        super().__init__(
            name="AnalystDesigner",
            profile="Analyst Designer",
            goal="Analyze requirements and produce comprehensive analysis and plan"
        )
        self._llm = llm
        self.rc.watch = {MessageType.USER_REQUIREMENT.value}
        self.actions = [WriteAnalysisReport(llm)]

    def set_llm(self, llm):
        self._llm = llm
        for action in self.actions:
            action.set_llm(llm)
```

### 4.3 Engineer（走 agent_loop + write_file）

```python
# agents/metagpt/roles/engineer.py

from typing import List
from agents.metagpt.role import Role
from agents.metagpt.action import Action
from agents.metagpt.message import Message, MessageType
from agents.metagpt.templates.output_templates import ENGINEER_PROMPT

class WriteCode(Action):
    """编写代码（走 agent_loop + write_file）"""

    name = MessageType.WRITE_CODE.value

    def run(self, memory: List[Message]) -> Message:
        # 获取分析报告
        analysis_report = ""
        for msg in memory:
            if msg.cause_by == MessageType.WRITE_ANALYSIS_REPORT.value:
                analysis_report = msg.content
                break

        if not analysis_report:
            return Message(
                content="Error: No analysis report found",
                role="assistant",
                cause_by=self.name
            )

        # 复用 agent_loop 驱动 Engineer 调用 write_file 工具
        from query import agent_loop
        from services.compact import TokenTracker, CircuitBreaker

        messages = [{
            "role": "user",
            "content": f"""## Analysis Report (from AnalystDesigner)
{analysis_report}

## Your Task
Implement the project based on the analysis report above.

Requirements:
1. Create all files listed in the "模块划分" section
2. Write COMPLETE, production-ready code (no TODOs)
3. Use write_file tool to create each file in the code/ directory
4. After writing all files, run tests using run_shell tool

Output format:
- For each file: Use write_file with path like "code/filename.py"
- Then use run_shell to run: pytest code/ -v

Start implementing now."""
        }]

        # 调用 agent_loop，Engineer 可以调用 write_file, run_shell 等工具
        tracker, breaker = agent_loop(messages, max_turns=30)

        # 从消息历史中收集写入的文件
        files_written = self._collect_written_files(messages)

        return Message(
            content=f"Code generated: {len(files_written)} files created",
            role="assistant",
            cause_by=self.name,
            send_to={MessageType.RUN_TESTS.value},
            metadata={"files": files_written}
        )

    def _collect_written_files(self, messages: list) -> List[str]:
        """从消息历史中收集 write_file 操作的文件名"""
        files = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                # 匹配 write_file 工具调用的结果
                if "write_file" in content and "success" in content.lower():
                    # 简单提取文件名
                    import re
                    matches = re.findall(r'code/[\w/]+\.py', content)
                    files.extend(matches)
        # 去重
        return list(set(files))
```

### 4.4 Tester（走 agent_loop + run_shell）

```python
# agents/metagpt/roles/tester.py

from typing import List
from agents.metagpt.role import Role
from agents.metagpt.action import Action
from agents.metagpt.message import Message, MessageType
from agents.metagpt.templates.output_templates import TESTER_PROMPT

class RunTests(Action):
    """运行测试（走 agent_loop + run_shell）"""

    name = MessageType.RUN_TESTS.value

    def run(self, memory: List[Message]) -> Message:
        # 获取代码输出
        code_files = []
        for msg in memory:
            if msg.cause_by == MessageType.WRITE_CODE.value:
                code_files = msg.metadata.get("files", [])
                break

        # 复用 agent_loop 驱动 Tester 调用 run_shell 工具
        from query import agent_loop
        from services.compact import TokenTracker, CircuitBreaker

        messages = [{
            "role": "user",
            "content": f"""## Code Output
{len(code_files)} files: {code_files}

## Your Task
1. Review the code files using read_file tool
2. Run tests using run_shell: pytest code/ -v --tb=short
3. Analyze test results
4. If tests fail, try to fix using edit_file tool
5. Generate a test report summarizing:
   - Number of tests passed/failed
   - Any errors found
   - Code quality observations

Format your final report as:
# 测试报告
## 1. 测试概览
- 测试文件数: X
- 总测试用例数: Y
- 通过: Z
- 失败: W
## 2. 测试结果
[Details]
## 3. 总结
[Pass/Fail with reasoning]"""
        }]

        # 调用 agent_loop，Tester 可以调用 run_shell, read_file, edit_file 等工具
        tracker, breaker = agent_loop(messages, max_turns=20)

        # 提取最终报告（最后一条 assistant 消息）
        report = self._extract_report(messages)

        return Message(
            content=report,
            role="assistant",
            cause_by=self.name,
            metadata={"test_summary": self._parse_summary(messages)}
        )

    def _extract_report(self, messages: list) -> str:
        """从消息历史中提取测试报告"""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content", "")
                if "测试报告" in content or "# 测试报告" in content:
                    return content
        # 如果没找到，返回最后一条消息
        if messages and isinstance(messages[-1], dict):
            return messages[-1].get("content", "No report generated")
        return "No report generated"

    def _parse_summary(self, messages: list) -> dict:
        """解析测试摘要"""
        # 简化实现：尝试从消息中提取数字
        summary = {"total": 0, "passed": 0, "failed": 0}
        for msg in messages:
            if isinstance(msg, dict):
                content = msg.get("content", "")
                import re
                # 匹配 "X passed" 或 "通过: Y"
                passed = re.search(r'(\d+)\s*(?:passed|通过)', content)
                failed = re.search(r'(\d+)\s*(?:failed|失败)', content)
                if passed:
                    summary["passed"] = int(passed.group(1))
                if failed:
                    summary["failed"] = int(failed.group(1))
        return summary
```

---

## 5. 输出模板

```python
# agents/metagpt/templates/output_templates.py

ANALYST_TEMPLATE = """\
## Output Format
Output a SINGLE document: `analysis_report.md` with the following structure:

# 项目分析报告

## 1. 需求分析
### 1.1 产品目标
- Goal 1
- Goal 2

### 1.2 用户故事
- As a [role], I want [feature] so that [benefit]

### 1.3 需求池
- P0 (Must have): ...
- P1 (Should have): ...

## 2. 项目实现方案
### 2.1 技术选型
[Specify: language, framework, key libraries]

### 2.2 系统架构
[High-level architecture in 3-5 bullet points]

### 2.3 模块划分
| 文件 | 职责 | 依赖 |
|------|------|------|
| code/main.py | ... | ... |

## 3. 项目实现计划
### 3.1 任务列表
- Task: main.py - [key classes/functions] - 依赖: none

### 3.2 执行顺序
1. main.py

## Constraints
- Use Chinese for document content
- Do NOT write any code
- Be concise but complete"""

ENGINEER_PROMPT = """\
You are an Engineer — a senior software engineer writing clean, efficient, well-tested code.

## Input
You will receive an analysis report from the Analyst. Read it carefully.

## Your Task
1. Implement each file listed in the task list
2. Write corresponding unit tests
3. Run tests to verify correctness

## Code Standards
- Follow PEP8 for Python
- Use meaningful names
- Include type hints
- Write docstrings for public functions

## Output Format
For each file, use write_file tool:
- path: code/[filename].py
- content: complete, production-ready code

After all files, run: pytest code/ -v

## Constraints
- Write COMPLETE code, no TODOs
- Each file should be self-contained"""

TESTER_PROMPT = """\
You are a Tester — a QA engineer validating software quality.

## Input
You will receive code files from the Engineer.

## Your Task
1. Explore the code structure using read_file
2. Run tests using run_shell: pytest code/ -v --tb=short
3. Analyze results
4. If tests fail, try to fix using edit_file

## Output Format
Generate test_report.md with:

# 测试报告

## 1. 测试概览
- 测试文件数: X
- 总测试用例数: Y
- 通过: Z
- 失败: W

## 2. 测试结果详情
[For each failed test: test name and error message]

## 3. 总结
Pass / Fail

## Constraints
- Run ALL tests
- Report ALL failures"""
```

---

## 6. Pipeline（同步，真用 Pub-Sub）

```python
# agents/metagpt/pipeline.py

from agents.metagpt.environment import Environment
from agents.metagpt.roles.analyst import AnalystDesigner
from agents.metagpt.roles.engineer import Engineer
from agents.metagpt.roles.tester import Tester
from agents.metagpt.message import Message, MessageType, MESSAGE_ROUTE_TO_ALL

class MetaGPTPipeline:
    """
    MetaGPT 简化版流水线

    核心设计：
    1. Environment 作为消息路由中枢
    2. 每个 Role 的 run() 从 msg_buffer 取消息，通过 _observe() 过滤
    3. 执行结果通过 publish_message() 发回 Environment
    4. Pipeline 按顺序驱动，但消息传递靠 Pub-Sub 机制
    """

    def __init__(self, llm):
        self.llm = llm
        self.env = Environment()

        # 创建角色
        self.analyst = AnalystDesigner(llm)
        self.engineer = Engineer(llm)
        self.tester = Tester(llm)

        # 注册角色到环境
        self.env.add_role(self.analyst)
        self.env.add_role(self.engineer)
        self.env.add_role(self.tester)

    def run(self, user_requirement: str) -> dict:
        """
        运行流水线（同步）

        Args:
            user_requirement: 用户需求描述

        Returns:
            dict: 包含各角色输出的字典
        """
        results = {}

        # Step 1: 发布用户需求到 Environment（触发 Analyst）
        self.env.publish_message(Message(
            content=user_requirement,
            role="user",
            cause_by=MessageType.USER_REQUIREMENT.value,
            send_to={MESSAGE_ROUTE_TO_ALL},
        ))

        # Step 2: Analyst 执行
        # - _observe() 从 msg_buffer 找到 user_requirement 消息
        # - 执行 WriteAnalysisReport action
        # - publish_message() 将结果发回 Environment
        print("[1/3] AnalystDesigner is analyzing...")
        analyst_msg = self.analyst.run()
        results["analysis"] = analyst_msg.content
        print(f"  → Analysis report generated ({len(analyst_msg.content)} chars)")

        # Step 3: Engineer 执行
        # - _observe() 从 msg_buffer 找到 WriteAnalysisReport 消息
        # - 执行 WriteCode action（内部调用 agent_loop）
        # - publish_message() 将结果发回 Environment
        print("[2/3] Engineer is coding...")
        engineer_msg = self.engineer.run()
        results["code"] = engineer_msg.content
        results["code_files"] = engineer_msg.metadata.get("files", [])
        print(f"  → Code generated: {len(results['code_files'])} files")

        # Step 4: Tester 执行
        # - _observe() 从 msg_buffer 找到 WriteCode 消息
        # - 执行 RunTests action（内部调用 agent_loop）
        # - publish_message() 将结果发回 Environment
        print("[3/3] Tester is testing...")
        tester_msg = self.tester.run()
        results["test"] = tester_msg.content
        results["test_summary"] = tester_msg.metadata.get("test_summary", {})
        print(f"  → Test report generated")

        return results
```

---

## 7. 集成点

### 7.1 需要修改的文件

| 文件 | 修改内容 |
|------|---------|
| `agents/__init__.py` | 添加 `from agents.metagpt import MetaGPTPipeline` |
| `query.py` | 在 `agent_loop()` 开头添加 MetaGPT 模式短路 |
| `main.py` | 初始化时打印 MetaGPT 模式提示 |

### 7.2 query.py 集成

```python
# query.py 修改

from agents.coordinator import is_coordinator_mode

def agent_loop(messages, tracker=None, breaker=None, max_turns=None):
    # ★ MetaGPT 模式短路
    if os.getenv("META_GPT_MODE", "").lower() in ("1", "true"):
        from agents.metagpt import MetaGPTPipeline
        from bootstrap import state

        user_input = messages[-1]["content"] if messages else ""
        pipeline = MetaGPTPipeline(state.llm)
        results = pipeline.run(user_input)

        # 将结果格式化为消息
        output = f"""=== MetaGPT Pipeline Complete ===

## Analysis
{results.get('analysis', '')[:500]}...

## Code
{results.get('code', '')[:500]}...

## Test
{results.get('test', '')[:500]}...
"""
        messages.append({"role": "assistant", "content": output})
        return tracker or TokenTracker(), breaker or CircuitBreaker()

    # 原有逻辑...
```

### 7.3 main.py 集成

```python
# main.py 修改

def main():
    init()
    try:
        if os.getenv("META_GPT_MODE", "").lower() in ("1", "true"):
            print("[MetaGPT mode] Use this mode for SOP-based multi-agent collaboration.")
            print("  See docs/META_GPT_IMPLEMENTATION_PLAN.md for details.")
        run_repl()
    finally:
        if state.mcp:
            state.mcp.close_all()
```

---

## 8. 不实现的功能

| 功能 | 原因 |
|------|------|
| Sandbox/SandboxPool | 项目已有 run_shell 工具，可复用。第一阶段不重复造轮子。 |
| async/await | 与项目主体同步架构保持一致 |
| instruct_content 复杂解析 | 结构化通过 Markdown 模板保证，输出纯文本 |
| Environment 以外的消息持久化 | 第一阶段只跑内存中的消息流 |

---

## 9. 实现计划

### Phase 1：核心基础设施（1 天）

| 任务 | 描述 | 文件 |
|------|------|------|
| Message 定义 | Message + MessageType | `agents/metagpt/message.py` |
| Environment | 消息路由 | `agents/metagpt/environment.py` |
| Role 基类 | run/put_message/_observe | `agents/metagpt/role.py` |
| Action 基类 | 抽象基类 | `agents/metagpt/action.py` |
| 输出模板 | 三角色模板 | `agents/metagpt/templates/output_templates.py` |

### Phase 2：角色实现（1-2 天）

| 任务 | 描述 | 文件 |
|------|------|------|
| AnalystDesigner | 纯 LLM 调用 | `agents/metagpt/roles/analyst.py` |
| Engineer | 走 agent_loop + write_file | `agents/metagpt/roles/engineer.py` |
| Tester | 走 agent_loop + run_shell | `agents/metagpt/roles/tester.py` |

### Phase 3：流水线集成（0.5 天）

| 任务 | 描述 | 文件 |
|------|------|------|
| Pipeline | 串联三角色 | `agents/metagpt/pipeline.py` |
| 集成点 | query.py/main.py | 修改现有文件 |

### Phase 4：测试（0.5 天）

| 任务 | 描述 |
|------|------|
| 端到端测试 | 完整流程测试 |
| 修复问题 | 根据测试结果修复 |

---

## 10. 核心机制总结

### 10.1 通信机制

| 组件 | 作用 | 是否真正使用 |
|------|------|-------------|
| Environment | 消息路由中枢 | ✅ 真用 |
| publish_message() | 遍历 member_addrs 路由 | ✅ 真用 |
| Role.msg_buffer | 接收消息队列 | ✅ 真用 |
| Role.watch | 过滤关注的消息 | ✅ 真用 |
| Role._observe() | 筛选 msg_buffer | ✅ 真用 |

### 10.2 执行流程

```
Pipeline.run(user_requirement)
    ↓
env.publish_message(user_requirement, send_to=*)
    ↓
Analyst.run()
    ├── _observe() → 从 msg_buffer 取到 user_requirement
    ├── WriteAnalysisReport.run() → 生成报告
    └── publish_message(WriteAnalysisReport)
        ↓
env.publish_message(WriteAnalysisReport, send_to={Engineer})
    ↓
Engineer.run()
    ├── _observe() → 从 msg_buffer 取到 WriteAnalysisReport
    ├── WriteCode.run() → agent_loop + write_file
    └── publish_message(WriteCode)
        ↓
env.publish_message(WriteCode, send_to={Tester})
    ↓
Tester.run()
    ├── _observe() → 从 msg_buffer 取到 WriteCode
    ├── RunTests.run() → agent_loop + run_shell
    └── publish_message(RunTests)
```

### 10.3 可行性分析

**可行的原因**：

1. **真用 Pub-Sub** — Environment 作为路由中枢，每个组件都参与消息流
2. **复用 agent_loop** — Engineer/Tester 实际调用工具，不是 LLM 文本生成
3. **同步架构** — 与项目主体一致，无需 asyncio 桥接
4. **最小化新增** — 复用 run_shell、write_file 等现有工具

**风险点**：

1. **agent_loop 嵌套调用** — Engineer.run() 内部调用 agent_loop，messages 状态可能复杂
2. **错误处理** — 角色执行失败需要优雅降级
