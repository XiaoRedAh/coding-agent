"""
services 包 - 服务层

提供跨模块共享的核心服务：
- compact: 上下文压缩（token 估算、微压缩、自动压缩）
- bus: 消息总线（基于文件的消息传递）
- tasks: 持久化任务管理
- background: 异步后台命令执行
"""
