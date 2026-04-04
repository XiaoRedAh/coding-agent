"""
tools/CompressTool.py - 上下文压缩工具

手动触发对话上下文压缩。实际压缩逻辑在 query.py 中处理，
此工具仅作为信号标记。
"""

DEFINITION = {
    "name": "compress",
    "description": "Manually compress conversation context.",
    "input_schema": {"type": "object", "properties": {}},
}


def handle() -> str:
    """返回压缩信号（实际压缩在 query.py 中执行）"""
    return "Compressing..."
