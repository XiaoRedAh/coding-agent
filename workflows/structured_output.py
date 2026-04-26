from __future__ import annotations

import json
import re


_JSON_BLOCK_RE = re.compile(r"```json\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


def extract_json_object(text: str) -> dict | None:
    """从文本中提取第一个 JSON 对象。

    优先级：
    1. ```json fenced block
    2. 首尾花括号包围的对象
    """
    if not text:
        return None

    fence = _JSON_BLOCK_RE.search(text)
    if fence:
        candidate = fence.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        # 兜底提取：允许模型没按 fenced block 输出
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def ensure_fields(data: dict | None, required_fields: list[str], raw_text: str) -> dict:
    """补齐必填字段，并保留 raw_output 用于排障。"""
    data = data or {}
    for field in required_fields:
        # 约定：字段名以 s 结尾时默认给空列表，其余给空字符串
        data.setdefault(field, [] if field.endswith("s") else "")
    data.setdefault("raw_output", raw_text)
    return data
