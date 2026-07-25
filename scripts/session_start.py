#!/usr/bin/env python3
"""旧任务兼容空壳：让已缓存旧 SessionStart Hook 的任务安静退出。

新任务的配置已经不再调用本文件。等所有旧任务关闭后可删除；这里不得重新加入
文档注入、周报写入或其他启动副作用。
"""

raise SystemExit(0)
