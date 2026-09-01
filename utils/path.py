"""
utils/path.py - 路径安全检查

防止路径逃逸攻击，确保所有文件操作限制在工作目录内。

S2 重构：动态读取 bootstrap.state.WORKDIR（属性访问），
使运行时切换/测试隔离只需 patch 一处。
"""

from pathlib import Path

from bootstrap import state


def safe_path(p: str) -> Path:
    """
    将相对路径解析为绝对路径，并确保不会逃逸出工作目录。

    工作目录先 resolve() 再比较：Windows 下临时目录可能返回 8.3 短路径
    （如 C:\\Users\\XSX401~1\\...），而文件路径 resolve() 后是长路径，
    直接比较会误判为逃逸。

    Args:
        p: 文件路径字符串
    Returns:
        解析后的安全 Path 对象
    Raises:
        ValueError: 路径逃逸出工作目录时抛出
    """
    workdir = state.WORKDIR
    path = (workdir / p).resolve()
    if not path.is_relative_to(workdir.resolve()):
        raise ValueError(f"Path escapes workspace: {p}")
    return path
