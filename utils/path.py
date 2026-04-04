"""
utils/path.py - 路径安全检查

防止路径逃逸攻击，确保所有文件操作限制在工作目录内。
"""

from pathlib import Path

from bootstrap.state import WORKDIR


def safe_path(p: str) -> Path:
    """
    将相对路径解析为绝对路径，并确保不会逃逸出工作目录。

    Args:
        p: 文件路径字符串
    Returns:
        解析后的安全 Path 对象
    Raises:
        ValueError: 路径逃逸出工作目录时抛出
    """
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
