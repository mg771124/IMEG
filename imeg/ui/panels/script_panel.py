"""脚本控制台：直接写大漠风格的 Python（``dm.FindPic(...)`` 等）。"""
from __future__ import annotations

import contextlib
import io
import time
import traceback
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from ...core.types import Rect

__all__ = ["ScriptPanel"]

SNIPPETS = {
    "找图 → 点击": '''ret = dm.FindPic(0, 0, 0, 0, "tpl_1.png", "101010", 0.9, 0)
print("FindPic:", ret)
if ret != "-1|-1|-1":
    _, x, y = ret.split("|")
    dm.LeftClick(int(x) + 10, int(y) + 10)
''',
    "循环找图直到出现": '''import time
for i in range(60):
    ret = dm.FindPic(0, 0, 0, 0, "tpl_1.png", "101010", 0.9, 0)
    if ret != "-1|-1|-1":
        _, x, y = ret.split("|")
        print("第", i, "次找到:", x, y)
        dm.LeftClick(int(x), int(y))
        break
    time.sleep(0.5)
else:
    print("超时没找到")
''',
    "多点找色": '''print(dm.FindMultiColor(0, 0, 0, 0, "FFFFFF-101010", "5|5|FF0000,10|10|00FF00", 1.0, 0))
''',
    "截图 + 取色": '''w, h = dm.GetClientSize()
print("画面尺寸", w, h)
print("中心点颜色", dm.GetColor(w // 2, h // 2))
print(dm.Capture(0, 0, w - 1, h - 1, "screen.png"))
''',
    "透明图找图（alpha 自动忽略）": '''ret = dm.FindPic(0, 0, 0, 0, "tpl_alpha.png", "101010", 0.9, 0, alpha_threshold=128)
print("透明图 FindPic:", ret)
''',
}


class _Writer(io.TextIOBase):
    def __init__(self, sink) -> None:
        self.sink = sink

    def write(self, s: str) -> int:
        if s.strip():
            self.sink(s.rstrip("\n"))
        return len(s)

    def flush(self) -> None:  # pragma: no cover
        pass


class ScriptPanel(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.ns = {}
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(2000)
        self.output.setStyleSheet(
            "QPlainTextEdit{background:#16181c;color:#c8ccd4;font-family:Consolas,monospace;font-size:12px;}")
        root.addWidget(self.output, 1)

        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('直接写 Python，例如 dm.FindPic(0,0,0,0,"tpl_1.png","101010",0.9,0)')
        self.input.returnPressed.connect(self.run_line)
        b_run = QPushButton("执行")
        b_run.clicked.connect(self.run_line)
        row.addWidget(self.input, 1)
        row.addWidget(b_run)
        root.addLayout(row)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("多行脚本写这里，点「运行脚本」执行")
        self.editor.setMaximumHeight(160)
        self.editor.setStyleSheet(
            "QPlainTextEdit{background:#1d2026;color:#dfe3ea;font-family:Consolas,monospace;font-size:12px;}")
        root.addWidget(self.editor)

        row2 = QHBoxLayout()
        self.combo_snippet = QComboBox()
        self.combo_snippet.addItem("插入示例…")
        self.combo_snippet.addItems(SNIPPETS)
        self.combo_snippet.currentTextChanged.connect(self.insert_snippet)
        b_exec = QPushButton("运行脚本")
        b_open = QPushButton("打开 .py")
        b_save = QPushButton("保存 .py")
        b_clear = QPushButton("清空输出")
        b_exec.clicked.connect(self.run_script)
        b_open.clicked.connect(self.open_script)
        b_save.clicked.connect(self.save_script)
        b_clear.clicked.connect(self.output.clear)
        for w in (self.combo_snippet, b_exec, b_open, b_save, b_clear):
            row2.addWidget(w)
        root.addLayout(row2)

        tip = QLabel("可用变量：dm（大漠风格对象）、np、cv2、Rect、ctx（界面上下文）、sleep")
        tip.setStyleSheet("color:#8b95a3;font-size:11px;")
        root.addWidget(tip)

    # ---------------------------------------------------------------- 命名空间
    def namespace(self) -> dict:
        if not self.ns:
            import cv2
            self.ns = {
                "dm": self.ctx.dm,
                "ctx": self.ctx,
                "np": np,
                "cv2": cv2,
                "Rect": Rect,
                "sleep": time.sleep,
                "print": self.print,
            }
        self.ns["dm"] = self.ctx.dm
        return self.ns

    def print(self, *args, **kwargs) -> None:
        sep = kwargs.get("sep", " ")
        self.output.appendPlainText(sep.join(str(a) for a in args))

    # ---------------------------------------------------------------- 执行
    def run_line(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.output.appendPlainText(f">>> {text}")
        self.input.clear()
        self._exec(text, single=True)

    def run_script(self) -> None:
        text = self.editor.toPlainText().strip()
        if not text:
            self.ctx.msg("脚本是空的", "warn")
            return
        self.output.appendPlainText("--- 运行脚本 ---")
        self._exec(text, single=False)

    def _exec(self, text: str, single: bool = True) -> None:
        ns = self.namespace()
        writer = _Writer(self.output.appendPlainText)
        try:
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                if single:
                    try:
                        result = eval(text, ns)
                        if result is not None:
                            self.output.appendPlainText(repr(result))
                    except SyntaxError:
                        exec(text, ns)
                else:
                    exec(compile(text, "<script>", "exec"), ns)
        except Exception:
            self.output.appendPlainText(traceback.format_exc())

    # ---------------------------------------------------------------- 文件
    def insert_snippet(self, name: str) -> None:
        if name in SNIPPETS:
            self.editor.setPlainText(SNIPPETS[name])
            self.combo_snippet.setCurrentIndex(0)

    def open_script(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开脚本", "", "Python (*.py)")
        if path:
            self.editor.setPlainText(Path(path).read_text(encoding="utf-8"))

    def save_script(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存脚本", "script.py", "Python (*.py)")
        if path:
            Path(path).write_text(self.editor.toPlainText(), encoding="utf-8")
            self.ctx.msg(f"已保存 {path}", "info")
