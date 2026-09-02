"""
services/tracing.py - 会话级结构化事件追踪（可观测性）

设计：结构化事件日志（JSONL）+ 内存聚合报告，不引外部依赖。

写入位置：{workdir}/.xiaoagent/transcripts/session-{时间戳}.jsonl
每个会话一个文件，每行一个 JSON 事件。

事件类型（由各接线点产生）：
- session_start      会话开始（workdir / model）
- llm_response       一次成功的 LLM 调用（tokens_in/out、延迟）
- llm_error          LLM 调用失败（错误类型）
- tool_call          一次工具调用（工具名、延迟、成败、结果大小、是否写记忆）
- memory_write       检测到记忆写入（第一层引导有效性的直接指标）
- compact            上下文压缩触发（级别、前后 token 估算）
- agent_spawn        子 Agent 派生（类型、是否后台）
- agent_done         子 Agent 结束（类型、延迟、轮次）

开关：config tracing.enabled（默认 true）。

接线方式：agents/session.py 与 agents/subagent.py 的钩子调用
tracer.event(...)；本模块不依赖循环骨架，纯被动记录。
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from runtime import state
from runtime.state import settings


def _now_ts() -> float:
    return time.time()


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Tracer:
    """会话事件追踪器：线程安全地追加 JSONL 事件。"""

    def __init__(self, path: Path | None = None, enabled: bool | None = None):
        """
        Args:
            path: JSONL 输出路径（默认 TRANSCRIPT_DIR/session-{ts}.jsonl）
            enabled: 是否启用（默认读 config tracing.enabled）
        """
        self._lock = threading.Lock()
        self._events: list[dict] = []          # 内存副本（聚合报告用）
        self._path: Path | None = path
        if enabled is not None:
            self._enabled = enabled
        elif path is not None:
            self._enabled = True               # 显式传路径 = 测试/定制场景
        else:
            self._enabled = settings.tracing.enabled

        if self._enabled:
            self._init_file()
            self.event("session_start", workdir=str(state.WORKDIR),
                       model=str(getattr(state, "MODEL", "") or ""))

    # ── 初始化 ──

    def _init_file(self):
        if self._path is None:
            self._path = state.TRANSCRIPT_DIR / (
                f"session-{datetime.now().strftime('%Y%m%d-%H%M%S')}.jsonl")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 会话头：独立首行，便于 grep
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(
                    {"event": "_meta", "created_at": _utc_iso()},
                    ensure_ascii=False) + "\n")
        except OSError:
            self._enabled = False  # 磁盘不可写则静默关闭，绝不影响主流程

    # ── 记录 ──

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def enabled(self) -> bool:
        return self._enabled

    def event(self, name: str, **fields) -> None:
        """追加一个事件。任何内部异常都吞掉（追踪不能打断主流程）。"""
        if not self._enabled:
            return
        entry = {"event": name, "ts": round(_now_ts(), 3), **fields}
        self._events.append(entry)
        try:
            with self._lock:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except (OSError, ValueError, TypeError):
            pass

    # ── 聚合报告 ──

    def summary(self) -> dict:
        """聚合当前会话的事件，输出统计摘要。"""
        events = [e for e in self._events if e.get("event") != "_meta"]

        llm_calls = [e for e in events if e["event"] == "llm_response"]
        llm_errors = [e for e in events if e["event"] == "llm_error"]
        tool_calls = [e for e in events if e["event"] == "tool_call"]
        memory_writes = [e for e in events if e["event"] == "memory_write"]
        compacts = [e for e in events if e["event"] == "compact"]
        agents = [e for e in events if e["event"] == "agent_done"]

        # 按工具聚合：次数 / 失败数 / 总延迟
        tools: dict[str, dict] = {}
        for e in tool_calls:
            name = str(e.get("tool", "unknown"))
            slot = tools.setdefault(
                name, {"count": 0, "errors": 0, "total_ms": 0.0})
            slot["count"] += 1
            slot["total_ms"] += float(e.get("latency_ms", 0) or 0)
            if e.get("ok") is False:
                slot["errors"] += 1

        return {
            "events_total": len(events),
            "llm_calls": len(llm_calls),
            "llm_errors": len(llm_errors),
            "tokens_in": sum(int(e.get("tokens_in", 0) or 0) for e in llm_calls),
            "tokens_out": sum(int(e.get("tokens_out", 0) or 0) for e in llm_calls),
            "llm_total_ms": round(sum(float(e.get("latency_ms", 0) or 0) for e in llm_calls), 1),
            "tool_calls": len(tool_calls),
            "tools": tools,
            "memory_writes": len(memory_writes),
            "compacts": len(compacts),
            "agents": [
                {"agent_type": e.get("agent_type"), "turns": e.get("turns"),
                 "latency_ms": e.get("latency_ms")} for e in agents
            ],
            "trace_path": str(self._path) if self._path else None,
        }

    def format_summary(self) -> str:
        """人可读的会话统计（/stats 命令输出）。"""
        s = self.summary()
        lines = [
            f"Session stats ({s['events_total']} events)",
            f"  LLM: {s['llm_calls']} calls, {s['llm_errors']} errors, "
            f"{s['tokens_in']:,} in / {s['tokens_out']:,} out tokens, "
            f"{s['llm_total_ms']/1000:.1f}s",
            f"  Tools: {s['tool_calls']} calls "
            f"({sum(t['errors'] for t in s['tools'].values())} errors)",
        ]
        for name, t in sorted(s["tools"].items(),
                              key=lambda kv: -kv[1]["count"]):
            lines.append(
                f"    {name}: {t['count']}x, {t['errors']} err, "
                f"{t['total_ms']/1000:.1f}s")
        lines.append(f"  Memory writes: {s['memory_writes']}")
        lines.append(f"  Compactions: {s['compacts']}")
        if s["agents"]:
            lines.append(f"  Sub-agents: {len(s['agents'])}")
            for a in s["agents"]:
                lines.append(
                    f"    {a['agent_type']}: {a['turns']} turns, "
                    f"{(a['latency_ms'] or 0)/1000:.1f}s")
        if s["trace_path"]:
            lines.append(f"  Trace: {s['trace_path']}")
        return "\n".join(lines)


# ──────────────────────────────────────────────
#  模块级单例（会话内共享，可重置）
# ──────────────────────────────────────────────

_default_tracer: Tracer | None = None
_tracer_lock = threading.Lock()


def get_tracer() -> Tracer:
    """获取当前会话的 Tracer（懒构建）。禁用时返回关闭态实例（no-op）。"""
    global _default_tracer
    if _default_tracer is None:
        with _tracer_lock:
            if _default_tracer is None:
                _default_tracer = Tracer()
    return _default_tracer


def reset_tracer(path: Path | None = None, enabled: bool | None = None) -> Tracer:
    """重置 Tracer（新会话 / 测试隔离用）。"""
    global _default_tracer
    with _tracer_lock:
        _default_tracer = Tracer(path=path, enabled=enabled)
    return _default_tracer


def trace(name: str, **fields) -> None:
    """便捷入口：经默认 Tracer 记录事件（未初始化/禁用时为 no-op）。"""
    get_tracer().event(name, **fields)
