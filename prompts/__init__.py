"""prompts 包 — 提示词资产目录 + 加载器。

布局：
- base.md                 主系统提示词模板
- fragments/*.md          可复用指令片段（memory.md = 记忆写入规则）
- workflow/*.md           工作流角色模板
- loader.py               三级覆盖加载器（P1）
"""
