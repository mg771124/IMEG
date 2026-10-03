"""后台键鼠面板：adb input 或 Windows 后台消息，都不需要窗口在最前台。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

__all__ = ["InputPanel"]

QUICK_KEYS = ["HOME", "BACK", "MENU", "APP_SWITCH", "POWER", "ENTER", "DEL",
              "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT"]


class InputPanel(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        box_mode = QGroupBox("控制方式")
        form0 = QFormLayout(box_mode)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("跟随截图源（推荐）", "auto")
        self.combo_mode.addItem("ADB input（后台注入，真机/模拟器通用）", "adb")
        self.combo_mode.addItem("Windows 后台消息 PostMessage（不抢焦点）", "window")
        form0.addRow("方式", self.combo_mode)
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(self.apply_mode)
        form0.addRow(b_apply)
        self.lbl_mode = QLabel("当前：跟随截图源")
        self.lbl_mode.setStyleSheet("color:#9aa4b2;font-size:11px;")
        self.lbl_mode.setWordWrap(True)
        form0.addRow(self.lbl_mode)
        root.addWidget(box_mode)

        box_pos = QGroupBox("坐标")
        form = QFormLayout(box_pos)
        row = QHBoxLayout()
        self.spin_x = QSpinBox()
        self.spin_y = QSpinBox()
        for s in (self.spin_x, self.spin_y):
            s.setRange(0, 20000)
        row.addWidget(QLabel("x"))
        row.addWidget(self.spin_x)
        row.addWidget(QLabel("y"))
        row.addWidget(self.spin_y)
        b_mouse = QPushButton("取鼠标位置")
        b_mouse.clicked.connect(self.from_mouse)
        b_center = QPushButton("选区中心")
        b_center.clicked.connect(self.from_selection_center)
        row.addWidget(b_mouse)
        row.addWidget(b_center)
        form.addRow(row)
        root.addWidget(box_pos)

        box_click = QGroupBox("点击 / 滑动")
        grid = QGridLayout(box_click)
        buttons = [
            ("左键单击", lambda: self._run(lambda x, y: self.ctx.dm.LeftClick(x, y))),
            ("双击", lambda: self._run(lambda x, y: self.ctx.dm.DoubleClick(x, y))),
            ("右键", lambda: self._run(lambda x, y: self.ctx.dm.RightClick(x, y))),
            ("中键", lambda: self._run(lambda x, y: self.ctx.dm.MiddleClick(x, y))),
        ]
        for i, (text, fn) in enumerate(buttons):
            b = QPushButton(text)
            b.clicked.connect(fn)
            grid.addWidget(b, 0, i)

        form2 = QFormLayout()
        row2 = QHBoxLayout()
        self.spin_x2 = QSpinBox()
        self.spin_y2 = QSpinBox()
        for s in (self.spin_x2, self.spin_y2):
            s.setRange(0, 20000)
        self.spin_dur = QSpinBox()
        self.spin_dur.setRange(0, 20000)
        self.spin_dur.setValue(300)
        self.spin_dur.setSuffix(" ms")
        row2.addWidget(QLabel("到"))
        row2.addWidget(self.spin_x2)
        row2.addWidget(self.spin_y2)
        row2.addWidget(self.spin_dur)
        form2.addRow("滑动", row2)
        b_swipe = QPushButton("滑动 / 长按（起止点相同就是长按）")
        b_swipe.clicked.connect(self.do_swipe)
        form2.addRow(b_swipe)
        row3 = QHBoxLayout()
        b_up = QPushButton("滚轮上")
        b_down = QPushButton("滚轮下")
        b_up.clicked.connect(lambda: self._run(lambda x, y: self.ctx.dm.WheelUp(x, y)))
        b_down.clicked.connect(lambda: self._run(lambda x, y: self.ctx.dm.WheelDown(x, y)))
        row3.addWidget(b_up)
        row3.addWidget(b_down)
        b_drag = QPushButton("按下并保持（拖）")
        b_release = QPushButton("抬起")
        b_drag.clicked.connect(lambda: self._run(lambda x, y: self.ctx.dm.LeftDown(x, y)))
        b_release.clicked.connect(lambda: self._run(lambda x, y: self.ctx.dm.LeftUp(x, y)))
        row3.addWidget(b_drag)
        row3.addWidget(b_release)
        form2.addRow(row3)
        grid.addLayout(form2, 1, 0, 1, 4)
        box_click.setLayout(grid)
        root.addWidget(box_click)

        box_key = QGroupBox("键盘 / 文本")
        v = QVBoxLayout(box_key)
        grid2 = QGridLayout()
        for i, key in enumerate(QUICK_KEYS):
            b = QPushButton(key)
            b.clicked.connect(lambda _=False, k=key: self.send_key(k))
            grid2.addWidget(b, i // 5, i % 5)
        v.addLayout(grid2)
        row4 = QHBoxLayout()
        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("按键名或 keyevent 码，如 BACK / 4")
        b_key = QPushButton("发送按键")
        b_key.clicked.connect(self.send_key_from_edit)
        row4.addWidget(self.edit_key)
        row4.addWidget(b_key)
        v.addLayout(row4)
        row5 = QHBoxLayout()
        self.edit_text = QLineEdit()
        self.edit_text.setPlaceholderText("要输入的文本（中文走 adb input text / WM_CHAR）")
        b_text = QPushButton("输入文本")
        b_text.clicked.connect(self.send_text)
        row5.addWidget(self.edit_text)
        row5.addWidget(b_text)
        v.addLayout(row5)
        root.addWidget(box_key)
        root.addStretch(1)

    # ---------------------------------------------------------------- 数据
    def _xy(self) -> tuple[int, int]:
        return self.spin_x.value(), self.spin_y.value()

    def from_mouse(self) -> None:
        x, y = self.ctx.last_pos()
        self.spin_x.setValue(x)
        self.spin_y.setValue(y)

    def from_selection_center(self) -> None:
        rect = self.ctx.selection()
        if rect is None:
            self.ctx.msg("先框选一块区域", "warn")
            return
        self.spin_x.setValue((rect.x1 + rect.x2) // 2)
        self.spin_y.setValue((rect.y1 + rect.y2) // 2)

    def _run(self, fn) -> None:
        x, y = self._xy()
        try:
            ok = fn(x, y)
            self.ctx.msg(f"已发送 → ({x}, {y})  [返回 {ok}]", "info")
        except Exception as exc:
            self.ctx.msg(f"发送失败: {exc}", "error")

    def do_swipe(self) -> None:
        try:
            self.ctx.dm.Swipe(self.spin_x.value(), self.spin_y.value(),
                              self.spin_x2.value(), self.spin_y2.value(), self.spin_dur.value())
            self.ctx.msg("滑动已发送", "info")
        except Exception as exc:
            self.ctx.msg(f"滑动失败: {exc}", "error")

    def send_key(self, key: str) -> None:
        try:
            self.ctx.dm.KeyPressStr(key)
            self.ctx.msg(f"按键 {key}", "info")
        except Exception as exc:
            self.ctx.msg(f"按键失败: {exc}", "error")

    def send_key_from_edit(self) -> None:
        text = self.edit_key.text().strip()
        if not text:
            return
        self.send_key(text)

    def send_text(self) -> None:
        text = self.edit_text.text()
        if not text:
            return
        try:
            self.ctx.dm.SendString(text)
            self.ctx.msg(f"已输入 {text!r}", "info")
        except Exception as exc:
            self.ctx.msg(f"输入失败: {exc}", "error")

    def apply_mode(self) -> None:
        mode = self.combo_mode.currentData()
        dm = self.ctx.dm
        try:
            if mode == "auto":
                kind = dm.source.name if dm.source else "null"
                from ...core.inputctl import create_input
                dm.input = create_input("adb" if kind in ("adb", "scrcpy") else
                                        ("window" if kind == "window" else "null"),
                                        serial=getattr(dm.source, "serial", None),
                                        hwnd=getattr(dm.source, "hwnd", 0))
            elif mode == "adb":
                from ...core.inputctl import AdbInputController
                dm.input = AdbInputController(serial=getattr(dm.source, "serial", None))
            else:
                from ...core.inputctl import WindowInputController
                from ...core.capture import win32
                hwnd = getattr(dm.source, "hwnd", 0) or (win32.get_foreground() if win32.WINDOWS else 0)
                src = dm.GetDeviceSize()
                dst = win32.client_rect(hwnd) if win32.WINDOWS else src
                dm.input = WindowInputController(hwnd=hwnd, src_size=src, dst_size=dst)
            self.lbl_mode.setText(f"当前：{type(dm.input).__name__}  {dm.input.name}")
            self.ctx.msg(f"控制方式已切换为 {dm.input.name}", "info")
        except Exception as exc:
            self.ctx.msg(f"切换失败: {exc}", "error")
