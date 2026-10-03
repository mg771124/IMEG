"""主窗口：左边设备源、中间画面、右边功能页签、底部日志。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSplitter, QStatusBar, QTabWidget, QToolBar, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core.adb import AdbClient
from ..core.dm import Dm
from ..core.image import save_image
from .context import UiContext
from .panels.color_panel import ColorPanel
from .panels.device_panel import DevicePanel
from .panels.findpic_panel import FindPicPanel
from .panels.input_panel import InputPanel
from .panels.ocr_panel import OcrPanel
from .panels.script_panel import ScriptPanel
from .panels.transparent_panel import TransparentPanel
from .widgets import ImageView, LogConsole

__all__ = ["MainWindow"]

COLORS = {"info": "#c8ccd4", "warn": "#e2b93b", "error": "#ff6b6b", "ok": "#8bd28b"}


class MainWindow(QMainWindow):
    def __init__(self, adb: AdbClient | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"IMEG — 大漠风格图色工具  v{__version__}")
        self.resize(1440, 900)

        self.adb = adb or AdbClient()
        self.dm = Dm(input_ctrl=None, path=str(Path.home() / ".imeg" / "pic"))
        self.canvas = ImageView()
        self.log_view = LogConsole()
        self.ctx = UiContext(self.dm, self.canvas, self.log, self.status)

        self._last_seq = -1
        self._build_ui()
        self._bind_signals()
        self._start_timers()
        # 首帧尺寸要等布局完成才知道，所以延迟一次自动适应
        QTimer.singleShot(60, self.fit)

    # ---------------------------------------------------------------- 构建
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.device_panel = DevicePanel(adb=self.adb)
        self.device_panel.setMinimumWidth(300)
        splitter.addWidget(self.device_panel)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(4, 4, 4, 4)
        center_layout.setSpacing(4)

        bar = QHBoxLayout()
        self.btn_fit = QPushButton("适应窗口")
        self.btn_one = QPushButton("1:1")
        self.btn_save_frame = QPushButton("保存当前帧")
        self.btn_clear = QPushButton("清除标注")
        self.lbl_size = QLabel("—")
        self.lbl_size.setStyleSheet("color:#9aa4b2;")
        for w, fn in ((self.btn_fit, self.fit), (self.btn_one, self.one_to_one),
                      (self.btn_save_frame, self.save_frame), (self.btn_clear, self.clear_marks)):
            w.setFixedHeight(26)
            w.clicked.connect(fn)
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.lbl_size)
        center_layout.addLayout(bar)
        center_layout.addWidget(self.canvas, 1)

        self.lbl_status = QLabel("x=0  y=0  #000000")
        self.lbl_status.setStyleSheet("color:#9aa4b2;font-family:Consolas,monospace;font-size:12px;")
        center_layout.addWidget(self.lbl_status)
        splitter.addWidget(center)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(400)
        self.panel_findpic = FindPicPanel(self.ctx)
        self.panel_color = ColorPanel(self.ctx)
        self.panel_transparent = TransparentPanel(self.ctx)
        self.panel_input = InputPanel(self.ctx)
        self.panel_ocr = OcrPanel(self.ctx)
        self.panel_script = ScriptPanel(self.ctx)
        self.tabs.addTab(self.panel_findpic, "找图")
        self.tabs.addTab(self.panel_color, "找色/多点")
        self.tabs.addTab(self.panel_transparent, "透明图")
        self.tabs.addTab(self.panel_input, "键鼠")
        self.tabs.addTab(self.panel_ocr, "OCR")
        self.tabs.addTab(self.panel_script, "脚本")
        # 找图面板上的"去做透明图"按钮切到透明图页签
        self.panel_findpic.chk_transparent.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.panel_transparent))
        splitter.addWidget(self.tabs)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([320, 760, 420])

        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.log_view)
        self.log_view.setFixedHeight(130)
        self.setCentralWidget(holder)

        self.setStatusBar(QStatusBar())

        toolbar = QToolBar("主")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        act_open = QAction("打开图片", self)
        act_open.triggered.connect(self.open_image)
        act_save = QAction("保存画面", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.save_frame)
        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.close)
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.about)
        for a in (act_open, act_save, act_about, act_quit):
            toolbar.addAction(a)

    def _bind_signals(self) -> None:
        self.device_panel.sigSourceChanged.connect(self.on_source_changed)
        self.device_panel.sigMessage.connect(self.log)
        self.canvas.sigHover.connect(self.on_hover)
        self.canvas.sigContext.connect(self.show_canvas_menu)

    def _start_timers(self) -> None:
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    # ---------------------------------------------------------------- 日志/状态
    def log(self, text: str, level: str = "info") -> None:
        self.log_view.append_line(str(text), COLORS.get(level, COLORS["info"]))

    def status(self, text: str) -> None:
        self.statusBar().showMessage(str(text), 5000)

    # ---------------------------------------------------------------- 画面
    def attach_input(self, source) -> None:
        """截图源换了，键鼠控制方式跟着换（ADB 走 input，窗口走后台消息）。"""
        from ..core.capture import win32
        from ..core.inputctl import create_input
        kind = source.name if source else "null"
        if kind == "window" and win32.WINDOWS:
            hwnd = getattr(source, "hwnd", 0)
            ctrl = create_input("window", hwnd=hwnd,
                                src_size=source.device_size() or source.size(),
                                dst_size=win32.client_rect(hwnd))
        else:
            route = "adb" if kind in ("adb", "scrcpy") else "null"
            ctrl = create_input(route, serial=getattr(source, "serial", None))
        self.dm.input = ctrl
        self.panel_input.lbl_mode.setText(
            f"当前：{type(ctrl).__name__}  {ctrl.name}"
            + (f"  hwnd=0x{getattr(source, 'hwnd', 0):X}" if kind == "window" else ""))

    def on_source_changed(self, source) -> None:
        self.dm.source = source
        self._last_seq = -1
        if source is not None:
            self.attach_input(source)
            w, h = source.size()
            dev = source.device_size()
            self.lbl_size.setText(f"画面 {w}x{h}    设备解析度 {dev[0]}x{dev[1]}" if dev
                                  else f"画面 {w}x{h}")
            self.log(f"已绑定截图源: {source.name}", "ok")
            self.canvas.set_image(source.image(), keep_view=False)
            QTimer.singleShot(60, self.fit)
        else:
            self.lbl_size.setText("—")

    def tick(self) -> None:
        source = self.dm.source
        if source is None:
            return
        frame = source.frame()
        if frame is not None and frame.seq != self._last_seq:
            self._last_seq = frame.seq
            self.canvas.set_image(frame.image)
        self.device_panel.refresh_info()

    def fit(self) -> None:
        self.canvas.fit_view()

    def one_to_one(self) -> None:
        self.canvas.set_zoom(1.0)

    def clear_marks(self) -> None:
        self.canvas.clear_boxes()
        self.canvas.clear_selection()

    def save_frame(self) -> None:
        img = self.canvas.image()
        if img is None:
            self.log("当前没有画面", "warn")
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存画面", "frame.png", "PNG (*.png)")
        if path:
            save_image(path, img)
            self.log(f"已保存 {path}", "ok")

    def open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开图片", "", "图片 (*.png *.bmp *.jpg *.jpeg)")
        if not path:
            return
        try:
            from ..core.capture import create_source
            source = create_source("static", path=path)
            source.start()
            self.dm.source = source
            self.canvas.set_image(source.image(), keep_view=False)
            self.log(f"已载入 {path}（离线模式，可做模板/透明图）", "ok")
        except Exception as exc:
            self.log(f"打开失败: {exc}", "error")

    def on_hover(self, x: int, y: int, rgb: tuple[int, int, int]) -> None:
        self.ctx.hover = (x, y, tuple(int(v) for v in rgb))
        self.lbl_status.setText(f"x={x:<5} y={y:<5} #{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}")

    def show_canvas_menu(self, x: int, y: int) -> None:
        menu = QMenu(self)
        act_copy = menu.addAction(f"复制坐标 ({x}, {y})")
        act_color = menu.addAction("复制该点颜色")
        act_click = menu.addAction("点击该点")
        act_base = menu.addAction("设为多点找色基准点")
        act_xy = menu.addAction("填到键鼠面板")
        act_palette = menu.addAction("记录到配色表")
        chosen = menu.exec(self.canvas.mapToGlobal(self.canvas.mapFromScene(x, y)))
        if not chosen:
            return
        if chosen is act_copy:
            QApplication.clipboard().setText(f"{x},{y}")
        elif chosen is act_color:
            QApplication.clipboard().setText(self.ctx.color_at(x, y))
        elif chosen is act_click:
            self.dm.input.click(x, y)
            self.log(f"点击 ({x}, {y})", "ok")
        elif chosen is act_base:
            self.tabs.setCurrentWidget(self.panel_color)
            self.ctx.hover = (x, y, self.ctx.hover[2])
            self.panel_color.set_base()
        elif chosen is act_xy:
            self.tabs.setCurrentWidget(self.panel_input)
            self.panel_input.spin_x.setValue(x)
            self.panel_input.spin_y.setValue(y)
        elif chosen is act_palette:
            self.tabs.setCurrentWidget(self.panel_color)
            self.panel_color.chk_batch.setChecked(True)
            self.ctx.hover = (x, y, self.ctx.hover[2])
            self.panel_color.capture_point(x, y)

    def about(self) -> None:
        QMessageBox.information(
            self, "关于 IMEG",
            f"IMEG v{__version__}\n\n"
            "大漠风格的图色/控制工具：\n"
            "  • ADB 连线 + 后台截图（真实解析度）\n"
            "  • 不连 ADB：直接抓模拟器窗口，自动裁掉边框\n"
            "  • scrcpy 投屏流（低延迟）\n"
            "  • 透明图制作 + FindPic/FindColor/FindMultiColor\n"
            "  • 后台键鼠、OCR、脚本控制台\n\n"
            "ADB 后台截图和 Windows 窗口捕获都是不需要窗口在最前台的。")

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.device_panel.stop_source()
        except Exception:
            pass
        super().closeEvent(event)
