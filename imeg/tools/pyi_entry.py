"""PyInstaller 打包用的**启动器**（不要在运行源码时直接用它）。

为什么要有这个文件？

    PyInstaller 会把入口脚本当"顶层脚本"来分析（相当于 __name__ == "__main__"、
    没有包上下文）。如果直接拿 imeg/ui/app.py 当入口，它里面的
    ``from .main_window import MainWindow`` 这类**相对导入**就解析不出全名，
    结果整个 imeg.ui.*、imeg.core.dm / ocr / inputctl 都不会被打进 EXE，
    运行时才报 ModuleNotFoundError。

    所以这里用一个"只用绝对导入"的小脚本做入口，让 imeg 包整体被正常分析。
    改入口文件时请务必保持绝对导入（from imeg.ui.app import main）。
"""
from __future__ import annotations

import sys

from imeg.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
