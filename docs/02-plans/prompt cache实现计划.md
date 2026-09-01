# Prompt Cache 实现计划

---

## 一、当前项目的 Prompt Cache 现状

### 1.1 是否已实现？

**没有。** 当前项目的 API 调用没有使用任何 `cache_control` 标记：

```python
# query.py — 当前的 API 调用
response = client.messages.create(
    model=MODEL,
    system=system_prompt,       # 纯字符串，无 cache_control
    messages=messages,           # 纯消息列表
    tools=tool_defs,             # 纯工具定义
    max_tokens=8000,
)
```

Anthropic API 的 Prompt Cache 需要在请求中**显式标记** `cache_control` 字段才会生效。当前项目没有标记，所以每次请求的 system prompt、工具定义都是**全量重新处理**的。

### 1.2 不实现 Prompt Cache 的影响

以一个 50 轮对话为例（Sonnet 4 价格：$3/M input, $15/M output）：

| 组件 | 每轮 token | 50 轮总量 | 无缓存成本 | 有缓存成本 | 节省 |
|------|----------|---------|----------|----------|------|
| System Prompt | ~3K | 150K | $0.45 | ~$0.05 | 89% |
| 工具定义 | ~2K | 100K | $0.30 | ~$0.03 | 90% |
| 对话前缀 | ~20K avg | 1000K | $3.00 | ~$0.60 | 80% |
| **合计** | | 1250K | **$3.75** | **~$0.68** | **~82%** |

**结论**：50 轮对话可以节省 ~$3，长对话节省更多。对于高频使用者，这是显著的成本优化。

---

## 二、是否有必要实现？

### 2.1 收益分析

| 收益 | 说明 |
|------|------|
| **成本降低 ~80%** | 缓存命中的 token 只收 10% |
| **延迟降低** | 跳过前缀的重复计算 |
| **与 CC 对齐** | CC 的 Prompt Cache 是核心优化之一 |
| **学习价值** | 理解 Anthropic API 的高级特性 |

### 2.2 实现复杂度

| CC 的做法 | 我们需要的 | 复杂度 |
|----------|----------|--------|
| 4 块拆分 + 3 种 scope | 2 块（静态/动态）+ 1 种 scope | 低 |
| DYNAMIC_BOUNDARY 标记 | 直接拆分 | 低 |
| Cache Edits | 不需要（暂无 MicroCompact 路径 B） | 跳过 |
| Break Detection | 不需要（优化阶段再加） | 跳过 |
| TTL 锁存 | 不需要（我们不控制 TTL） | 跳过 |
| Section Cache | 已有简单实现（build_system_prompt 每轮调用一次） | 已有 |

**核心改动量：约 50 行代码。**

### 2.3 结论

**建议实现基础版本。** 改动量极小（~50 行），但收益显著（~80% 成本节省）。

---

## 三、实现计划

### 3.1 核心思路

将 `system` 参数从纯字符串改为**分块数组**，为静态块添加 `cache_control`：

```python
# 当前（无缓存）：
system=system_prompt  # 纯字符串

# 改为（有缓存）：
system=[
    {"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": dynamic_part},  # 无 cache_control
]
```

### 3.2 静态/动态拆分

**静态部分**（跨请求不变，可缓存）：
- 身份定义
- 系统约束
- 任务指引
- 操作安全准则
- 工具使用规则
- 语气与风格
- 输出效率

**动态部分**（每次可能不同，不缓存）：
- 环境信息（cwd, date, git status）
- CLAUDE.md 内容
- Skills 列表
- MCP Instructions
- Memory 指令

### 3.3 实现方案

#### 方案：拆分 system-prompt.md 为两部分

```python
# context.py — build_system_prompt() 改为返回分块数组

def build_system_prompt() -> list[dict]:
    """返回分块的 system prompt（支持 Prompt Cache）"""
    template = Path("system-prompt.md").read_text()
    
    # 静态部分（模板中 {{...}} 占位符之前的内容）
    # 即：Identity + System + Doing tasks + Actions + Tools + Tone + Output
    static_part = extract_static_part(template)
    
    # 动态部分（环境信息、CLAUDE.md、Skills、MCP 等）
    dynamic_part = build_dynamic_part()
    
    return [
        {"type": "text", "text": static_part, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_part},
    ]
```

#### query.py 的改动

```python
# query.py — 使用分块 system prompt
system_prompt = build_system_prompt()  # 返回 list[dict] 而非 str

response = client.messages.create(
    model=MODEL,
    system=system_prompt,  # Anthropic SDK 支持 list[dict] 格式
    messages=messages,
    tools=tool_defs,
    max_tokens=8000,
)
```

### 3.4 system-prompt.md 的拆分

当前模板中，`# Environment` 之前的内容是静态的，之后是动态的：

```markdown
You are Coding Agent...     ← 静态（可缓存）
# System                    ← 静态
# Doing tasks               ← 静态
# Executing actions...      ← 静态
# Using your tools           ← 静态
# Tone and style             ← 静态
# Output efficiency          ← 静态
                            ← ===== 分界线 =====
# Environment               ← 动态（不缓存）
Working directory: {{cwd}}
{{git_context}}
{{claude_md}}
{{skills_info}}
```

### 3.5 实施步骤

```
步骤 1: 修改 context.py
  - build_system_prompt() 返回 list[dict] 格式
  - 静态部分加 cache_control
  - 动态部分不加

步骤 2: 修改 query.py
  - 适配 system 参数为 list[dict]

步骤 3: 修改 agents/coordinator.py
  - Coordinator 的系统提示也改为分块格式

步骤 4: 验证
  - 检查 API 响应的 usage 中 cache_read_tokens 是否大于 0
  - 对比缓存前后的成本差异
```

### 3.6 暂不实现的 CC 功能

| CC 功能 | 暂不实现原因 | 后续优先级 |
|---------|-------------|-----------|
| 3 种 scope (global/org/null) | 只用 ephemeral 足够 | 低 |
| Cache Edits | 需要 MicroCompact 路径 B | 中 |
| Break Detection | 优化阶段再加 | 低 |
| TTL 锁存 | 我们不控制 TTL | 低 |
| Section Cache | 已有（每轮调一次 build_system_prompt） | 已有 |
| 分区排序 | 已实现（内置工具排前面） | 已有 |

### 3.7 效果预估

| 指标 | 改进前 | 改进后 |
|------|--------|--------|
| System Prompt 重复计费 | 每轮全量 | 首轮全量，后续 ~10% |
| 工具定义重复计费 | 每轮全量 | 首轮全量，后续 ~10% |
| 50 轮对话 input 成本 | ~$3.75 | ~$0.68 |
| 延迟 | 全量计算 | 前缀跳过 |
| 代码改动量 | - | ~50 行 |
