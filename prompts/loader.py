"""
prompts/loader.py - 提示词资产加载器（P1）

与 agents/registry.py 同构的三级覆盖机制，优先级从低到高：
1. {本项目}/prompts/                内置资产（随项目分发）
2. ~/.xiaoagent/prompts/            用户全局覆盖
3. {workdir}/.xiaoagent/prompts/    项目级覆盖

资产布局（相对路径即资产名）：
- base.md                 主系统提示词模板（context/prompt.py 使用）
- fragments/*.md          可复用指令片段（如 fragments/memory.md 记忆写入规则）
- workflow/*.md           工作流角色模板（workflows/prompting.py 使用）

覆盖语义：按相对路径逐级查找，最高优先级存在的文件胜出。
用户级/项目级还可以**新增**资产（内置没有的文件直接生效），
例如项目自定义 fragments/my_style.md。

设计约定：
- project_dir 懒读取 state.PROJECT_DIR（每次 load 时解析），
  因此 monkeypatch state 后无需重建加载器。
- rel_path 由代码写死调用（不接受用户输入），无路径穿越风险。
"""

from __future__ import annotations

from pathlib import Path

# 内置资产目录（本文件所在目录）
PROMPTS_DIR = Path(__file__).parent


class PromptLoader:
    """提示词资产加载器（内置 + 用户级 + 项目级，同名后者覆盖前者）。"""

    def __init__(self, builtin_dir=None, user_dir=None, project_dir=None):
        """
        Args:
            builtin_dir: 内置目录（默认 prompts/，一般不传）
            user_dir: 用户级目录（默认 ~/.xiaoagent/prompts/，
                      可传任意不存在路径用于测试隔离）
            project_dir: 项目级目录（默认懒读取 state.PROJECT_DIR / "prompts"，
                      显式传入则固定）
        """
        self.builtin_dir = Path(builtin_dir) if builtin_dir is not None else PROMPTS_DIR
        self.user_dir = (
            Path(user_dir) if user_dir is not None
            else Path.home() / ".xiaoagent" / "prompts"
        )
        self._explicit_project_dir = project_dir

    @property
    def project_dir(self) -> Path:
        """项目级目录（懒解析：每次读取当前 state.PROJECT_DIR）。"""
        if self._explicit_project_dir is not None:
            return Path(self._explicit_project_dir)
        from runtime import state as _state
        return _state.PROJECT_DIR / "prompts"

    # ── 查询 ──

    def find(self, rel_path: str) -> Path | None:
        """返回胜出的资产文件路径（项目级 > 用户级 > 内置），无则 None。"""
        for directory in (self.project_dir, self.user_dir, self.builtin_dir):
            candidate = Path(directory) / rel_path
            if candidate.is_file():
                return candidate
        return None

    def exists(self, rel_path: str) -> bool:
        return self.find(rel_path) is not None

    def load(self, rel_path: str) -> str:
        """加载资产文本（UTF-8）。所有来源均不存在时抛 FileNotFoundError。"""
        path = self.find(rel_path)
        if path is None:
            raise FileNotFoundError(
                f"Prompt asset not found in any source: {rel_path} "
                f"(searched: {self.project_dir}, {self.user_dir}, {self.builtin_dir})")
        return path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────
#  默认加载器（模块级单例，可重建）
# ──────────────────────────────────────────────

_default_loader: PromptLoader | None = None


def default_loader() -> PromptLoader:
    """获取默认加载器（懒构建；project_dir 每次调用时动态解析 state）。"""
    global _default_loader
    if _default_loader is None:
        _default_loader = PromptLoader()
    return _default_loader


def rebuild_default(builtin_dir=None, user_dir=None, project_dir=None) -> PromptLoader:
    """重建默认加载器（测试隔离用：显式传入各目录）。"""
    global _default_loader
    _default_loader = PromptLoader(
        builtin_dir=builtin_dir, user_dir=user_dir, project_dir=project_dir)
    return _default_loader


def load_prompt(rel_path: str) -> str:
    """便捷入口：经默认加载器加载资产。"""
    return default_loader().load(rel_path)
