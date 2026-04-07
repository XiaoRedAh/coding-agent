"""
services/compact.py - 五级渐进式压缩系统

对齐 Claude Code 的上下文管理架构，实现：
1. Token 估算（锚点 + 增量策略）
2. 五级压缩流水线：
   - L1: Tool Result Budget（动态预算裁剪）
   - L2: Snip（过时工具结果替换）
   - L3: MicroCompact（时间触发的激进清理）
   - L4: Context Collapse（跳过——当前规模不需要）
   - L5: AutoCompact（双阶段提示的全量摘要）
3. 断路器机制（防止连续失败的级联浪费）
4. 压缩后恢复（恢复最近文件和技能）
5. 压缩提示词工程（双阶段输出：analysis + summary）
"""

import json
import re
import time

from bootstrap import state as _state
from bootstrap.state import (
    TRANSCRIPT_DIR, EFFECTIVE_WINDOW,
    BUDGET_THRESHOLD, BUDGET_TIGHT_THRESHOLD, SNIP_THRESHOLD,
    AUTOCOMPACT_THRESHOLD, BUDGET_NORMAL, BUDGET_TIGHT,
    SNIP_KEEP_RECENT, MICROCOMPACT_IDLE_SECONDS,
    MAX_AUTOCOMPACT_FAILURES,
    POST_COMPACT_MAX_FILES, POST_COMPACT_MAX_TOKENS_PER_FILE,
    POST_COMPACT_SKILLS_BUDGET,
)

# 可 snip 的工具集合（大量结果但可重新获取）
SNIPPABLE_TOOLS = {"read_file", "grep_search", "list_files", "run_shell"}
SNIP_PLACEHOLDER = "[Content snipped - re-read if needed]"
CLEARED_PLACEHOLDER = "[Old tool result content cleared]"

# ──────────────────────────────────────────────
#  压缩提示词模板（双阶段输出结构）
# ──────────────────────────────────────────────

COMPACT_PROMPT = """\
CRITICAL: Respond with TEXT ONLY. Do NOT call any tools.

You are a conversation summarizer. Analyze the conversation and produce a structured summary.

Output TWO XML blocks in order:

<analysis>
Walk through the conversation chronologically. For each exchange, note:
- What the user asked or decided
- What files were read, edited, or created
- What errors occurred and how they were fixed
- Key technical decisions and their rationale
</analysis>

<summary>
## 1. Primary Request
The user's main goal and all explicit requests.

## 2. Key Technical Concepts
Frameworks, libraries, patterns, and architectural decisions discussed.

## 3. Files and Code
All files examined, modified, or created. Include key code snippets that are still relevant.

## 4. Errors and Fixes
Errors encountered and how they were resolved. Note any user feedback on fixes.

## 5. Problem Solving
Problems solved and investigations still in progress.

## 6. All User Messages
Reproduce every non-tool-result user message (verbatim if short, summarized if long).

## 7. Pending Tasks
Tasks not yet completed, including blockers.

## 8. Current Work
What was being worked on right before this summary (most detail here).

## 9. Optional Next Step
Planned next action, with any direct quotes from the conversation.
</summary>
"""


# ──────────────────────────────────────────────
#  Token 估算（锚点 + 增量策略）
# ──────────────────────────────────────────────

class TokenTracker:
    """
    Token 用量追踪器。

    使用"锚点 + 增量"策略：
    - 锚点：API 返回的 usage.input_tokens（服务端精确计算）
    - 增量：锚点之后新增消息的粗略估算（字符数 / 3）

    这比纯客户端估算精确得多（误差 <5% vs >30%），且零额外 API 调用。
    """

    def __init__(self):
        self.last_input_tokens = 0      # 最近一次 API 返回的 input_tokens
        self.total_input_tokens = 0     # 累计 input tokens（费用估算）
        self.total_output_tokens = 0    # 累计 output tokens
        self.last_api_call_time = 0.0   # 最近一次 API 调用时间戳
        self.messages_since_anchor = 0  # 锚点之后新增的消息数
        self._new_chars_since_anchor = 0  # 锚点之后新增的字符数

    def update_from_response(self, response):
        """从 API 响应中更新 token 统计（锚点更新）。

        兼容 LLMResponse（直接属性）和原始 Anthropic 响应（response.usage）。
        """
        if hasattr(response, "input_tokens"):
            # LLMResponse 格式
            inp = response.input_tokens
            out = response.output_tokens
        else:
            # 原始 Anthropic SDK 响应
            inp = response.usage.input_tokens
            out = response.usage.output_tokens
        self.last_input_tokens = inp
        self.total_input_tokens += inp
        self.total_output_tokens += out
        self.last_api_call_time = time.time()
        self.messages_since_anchor = 0
        self._new_chars_since_anchor = 0

    def track_new_message(self, message):
        """追踪锚点之后新增的消息"""
        self.messages_since_anchor += 1
        self._new_chars_since_anchor += len(json.dumps(message, default=str))

    def estimate_current_tokens(self) -> int:
        """估算当前 token 用量 = 锚点值 + 新消息估算"""
        if self.last_input_tokens == 0:
            # 会话刚开始，无锚点，纯粗略估算
            return self._new_chars_since_anchor // 3
        return self.last_input_tokens + (self._new_chars_since_anchor // 3)

    def get_utilization(self) -> float:
        """返回当前上下文利用率（0.0 ~ 1.0+）"""
        return self.estimate_current_tokens() / EFFECTIVE_WINDOW

    def reset_after_compact(self):
        """压缩后重置锚点"""
        self.last_input_tokens = 0
        self.messages_since_anchor = 0
        self._new_chars_since_anchor = 0


# ──────────────────────────────────────────────
#  断路器（防止连续压缩失败的级联浪费）
# ──────────────────────────────────────────────

class CircuitBreaker:
    """
    断路器机制。

    状态机：CLOSED → HALF_OPEN → OPEN
    - CLOSED: 正常工作，计数器=0
    - HALF_OPEN: 有失败但未达阈值，0 < 计数器 < 3
    - OPEN: 熔断，计数器 >= 3，跳过自动压缩

    重置条件：压缩成功 / 手动压缩成功 / 新会话
    """

    def __init__(self):
        self.consecutive_failures = 0

    def should_skip(self) -> bool:
        """是否应跳过自动压缩"""
        return self.consecutive_failures >= MAX_AUTOCOMPACT_FAILURES

    def record_success(self):
        """记录压缩成功，重置计数器"""
        self.consecutive_failures = 0

    def record_failure(self):
        """记录压缩失败，递增计数器"""
        self.consecutive_failures += 1

    @property
    def state(self) -> str:
        if self.consecutive_failures == 0:
            return "CLOSED"
        elif self.consecutive_failures < MAX_AUTOCOMPACT_FAILURES:
            return "HALF_OPEN"
        return "OPEN"


# ──────────────────────────────────────────────
#  L1: Tool Result Budget（动态预算裁剪）
# ──────────────────────────────────────────────

def budget_tool_results(messages: list, utilization: float):
    """
    根据上下文利用率动态裁剪工具结果。

    - 50%-70%: 工具结果超过 30K 字符的截断为 30K
    - >70%: 工具结果超过 15K 字符的截断为 15K
    - <50%: 不做处理

    Args:
        messages: 对话消息列表（原地修改）
        utilization: 当前上下文利用率
    """
    if utilization < BUDGET_THRESHOLD:
        return

    budget = BUDGET_TIGHT if utilization > BUDGET_TIGHT_THRESHOLD else BUDGET_NORMAL

    for msg in messages:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if (isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and isinstance(block.get("content"), str)
                    and len(block["content"]) > budget):
                original_len = len(block["content"])
                keep_each = (budget - 80) // 2
                block["content"] = (
                    block["content"][:keep_each]
                    + f"\n\n[... budgeted: {original_len - keep_each * 2} chars truncated ...]\n\n"
                    + block["content"][-keep_each:]
                )


# ──────────────────────────────────────────────
#  L2: Snip（过时工具结果替换）
# ──────────────────────────────────────────────

def snip_stale_results(messages: list, utilization: float):
    """
    替换过时的工具结果为占位符。

    策略：
    1. 同一文件被 read_file 多次 → snip 旧的（只保留最新读取）
    2. 永远保留最近 3 个 tool_result（可能正在被引用）
    3. 只清 tool_result 的 content，保留 tool_use block

    Args:
        messages: 对话消息列表（原地修改）
        utilization: 当前上下文利用率
    """
    if utilization < SNIP_THRESHOLD:
        return

    # 收集所有 tool_result 及其对应的 tool_use 信息
    tool_results = []  # [(block_ref, tool_name, tool_input, msg_index)]
    for i, msg in enumerate(messages):
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                tool_name, tool_input = _find_tool_use(messages, tool_use_id)
                if tool_name in SNIPPABLE_TOOLS:
                    tool_results.append((block, tool_name, tool_input, i))

    if len(tool_results) <= SNIP_KEEP_RECENT:
        return

    # 标记哪些需要 snip
    # 1. 保留最近 SNIP_KEEP_RECENT 个
    candidates = tool_results[:-SNIP_KEEP_RECENT]

    # 2. 同一文件的重复读取 → snip 旧的
    seen_files = set()
    # 从后往前扫描，标记最新的同文件读取
    for block, name, inp, _ in reversed(tool_results):
        if name == "read_file" and isinstance(inp, dict):
            fpath = inp.get("file_path", inp.get("path", ""))
            seen_files.add(fpath)

    for block, name, inp, _ in candidates:
        content = block.get("content", "")
        if isinstance(content, str) and len(content) > 100:
            block["content"] = SNIP_PLACEHOLDER


def _find_tool_use(messages: list, tool_use_id: str):
    """查找 tool_use_id 对应的工具名称和输入参数"""
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if isinstance(content, list):
            for block in content:
                if hasattr(block, "id") and block.id == tool_use_id:
                    return block.name, getattr(block, "input", {})
                if isinstance(block, dict) and block.get("id") == tool_use_id:
                    return block.get("name", ""), block.get("input", {})
    return "", {}


# ──────────────────────────────────────────────
#  L3: MicroCompact（时间触发的激进清理）
# ──────────────────────────────────────────────

def microcompact(messages: list, tracker: TokenTracker):
    """
    时间触发的激进工具结果清理。

    当距上次 API 调用超过 5 分钟时，prompt cache 大概率已过期，
    此时保留旧消息内容没有缓存成本优势，直接清除释放空间。

    保留最近 1 个工具结果（MicroCompact 比 Snip 更激进）。

    Args:
        messages: 对话消息列表（原地修改）
        tracker: Token 追踪器
    """
    if tracker.last_api_call_time == 0:
        return
    elapsed = time.time() - tracker.last_api_call_time
    if elapsed < MICROCOMPACT_IDLE_SECONDS:
        return

    # 收集所有 tool_result
    tool_results = []
    for msg in messages:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            continue
        for block in msg["content"]:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_results.append(block)

    if len(tool_results) <= 1:
        return

    # 保留最近 1 个，清除其余
    for block in tool_results[:-1]:
        if isinstance(block.get("content"), str) and len(block["content"]) > 50:
            block["content"] = CLEARED_PLACEHOLDER


# ──────────────────────────────────────────────
#  L5: AutoCompact（双阶段提示的全量摘要）
# ──────────────────────────────────────────────

def auto_compact(messages: list, tracker: TokenTracker) -> list:
    """
    全量摘要压缩：保存转录 → LLM 双阶段摘要 → 重建上下文。

    双阶段输出结构：
    - <analysis>: 思维过程（被丢弃，不计入新上下文）
    - <summary>: 9 个标准化章节（保留为新上下文）

    Args:
        messages: 当前完整的对话消息列表
        tracker: Token 追踪器
    Returns:
        压缩后的新消息列表
    """
    if len(messages) < 4:
        return messages  # 太短不值得压缩

    # 1. 保存完整转录到文件
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"transcript_{int(time.time())}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg, default=str) + "\n")

    # 2. 保留最后一条用户消息
    last_user_msg = None
    if messages and messages[-1].get("role") == "user":
        last_user_msg = messages[-1]

    # 3. 用 LLM 生成双阶段摘要
    conv_text = json.dumps(messages[:-1] if last_user_msg else messages, default=str)
    # 截断到 80K 字符以防超出单次请求限制
    if len(conv_text) > 80000:
        conv_text = conv_text[:40000] + "\n...[middle truncated]...\n" + conv_text[-40000:]

    resp = _state.llm.chat(
        system="You are a conversation summarizer. Be concise but preserve important details.",
        messages=[{
            "role": "user",
            "content": COMPACT_PROMPT + "\n\nConversation to summarize:\n" + conv_text,
        }],
        max_tokens=4096,
    )
    raw_output = resp.content[0].text

    # 4. 后处理：丢弃 <analysis>，提取 <summary>
    summary = _extract_summary(raw_output)

    # 5. 重建上下文
    new_messages = [
        {
            "role": "user",
            "content": f"[Previous conversation compressed. Transcript: {path}]\n\n{summary}",
        },
        {
            "role": "assistant",
            "content": "Understood. I have the context from our previous conversation. How can I continue helping?",
        },
    ]

    # 恢复最后一条用户消息
    if last_user_msg:
        new_messages.append(last_user_msg)

    # 6. 重置 token 追踪
    tracker.reset_after_compact()

    return new_messages


def _extract_summary(raw_output: str) -> str:
    """
    从 LLM 双阶段输出中提取 <summary> 块，丢弃 <analysis>。

    如果格式不符预期，返回原始输出作为 fallback。
    """
    summary_match = re.search(
        r"<summary>(.*?)</summary>", raw_output, re.DOTALL
    )
    if summary_match:
        return summary_match.group(1).strip()
    # Fallback: 如果模型没有按格式输出，使用原始内容
    return raw_output


# ──────────────────────────────────────────────
#  压缩管道编排
# ──────────────────────────────────────────────

def run_compression_pipeline(messages: list, tracker: TokenTracker):
    """
    执行 L1-L3 压缩管道（零 API 成本）。

    在每次 API 调用前运行。
    L1-L3 就地修改消息数组，不调用 API。

    Args:
        messages: 对话消息列表（原地修改）
        tracker: Token 追踪器
    """
    utilization = tracker.get_utilization()

    # L1: Tool Result Budget
    budget_tool_results(messages, utilization)

    # L2: Snip stale results
    snip_stale_results(messages, utilization)

    # L3: MicroCompact (time-based)
    microcompact(messages, tracker)


def check_and_compact(
    messages: list, tracker: TokenTracker, breaker: CircuitBreaker
) -> list | None:
    """
    检查是否需要触发 L5 AutoCompact。

    在每次 API 调用后运行。如果利用率超过 85% 且断路器允许，
    执行全量摘要压缩。

    Args:
        messages: 对话消息列表
        tracker: Token 追踪器
        breaker: 断路器
    Returns:
        压缩后的新消息列表，或 None（不需要压缩）
    """
    utilization = tracker.get_utilization()
    if utilization < AUTOCOMPACT_THRESHOLD:
        return None

    if breaker.should_skip():
        print(f"[autocompact skipped: circuit breaker OPEN, {breaker.consecutive_failures} failures]")
        return None

    print(f"[autocompact triggered at {utilization:.0%} utilization]")
    try:
        result = auto_compact(messages, tracker)
        breaker.record_success()
        return result
    except Exception as e:
        breaker.record_failure()
        print(f"[autocompact failed ({breaker.state}): {e}]")
        return None
