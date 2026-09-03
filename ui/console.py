"""
ui/console.py - Windows 控制台兼容层

解决中文 Windows conhost 的两个渲染问题：
1. VT 处理默认关闭 → ANSI 颜色码（\\033[90m 等）不被解析，
   ESC 字节被渲染成小方块，颜色全部失效
2. GBK 代码页字体不含盲文/符号字形 → spinner（⠋⠙）、⚠、✓ 显示为方块

策略：
- setup_console() 在启动时启用 VT 处理（Win10+ conhost 支持）
- 符号统一 ASCII（|/-\\ spinner、[!] 警告、x/+ 状态），
  颜色码启用后即可正常显示 —— 不依赖字体字形的部分全保留
"""

from __future__ import annotations

import os
import sys

# 是否使用 ASCII 符号回退（Windows conhost 的 GBK 字体缺字形）
ASCII_SYMBOLS = os.name == "nt"


def setup_console() -> None:
    """初始化控制台（目前仅 Windows 需要：启用 VT 颜色处理）。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(
                handle, mode.value | 0x0004)
    except Exception:
        # 兜底：os.system("") 也会触发控制台 VT 初始化（colorama 同款技巧）
        try:
            os.system("")
        except Exception:
            pass


def spinner_frames() -> list[str]:
    """spinner 帧序列：Windows 用 ASCII（GBK 字体无盲文字形），其他保留盲文。"""
    if ASCII_SYMBOLS:
        return ["|", "/", "-", "\\"]
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def warn_sym() -> str:
    """权限确认等警告前缀符号。"""
    return "[!]" if ASCII_SYMBOLS else "⚠"


def fail_sym() -> str:
    """失败/拒绝标记。"""
    return "x" if ASCII_SYMBOLS else "✗"


def ok_sym() -> str:
    """成功标记。"""
    return "+" if ASCII_SYMBOLS else "✓"
