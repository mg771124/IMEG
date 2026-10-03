"""左侧设备/截图源面板：ADB 连接、窗口选择、scrcpy、本地图片。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ...core.adb import AdbClient
from ...core.capture import SOURCE_LABELS, available_sources, create_source, list_windows

__all__ = ["DevicePanel"]


class DevicePanel(QWidget):
    """选择并启动截图源。"""

    sigSourceChanged = Signal(object)   # 新的 CaptureSource（或 None）
    sigMessage = Signal(str, str)       # 消息, 级别(info/warn/error)

    def __init__(self, adb: AdbClient | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.adb = adb or AdbClient()
        self.source = None
        self._build_ui()
        self.refresh_devices()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        box = QGroupBox("截图源")
        form = QFormLayout(box)
        self.combo_source = QComboBox()
        avail = available_sources()
        for key, label in SOURCE_LABELS.items():
            if avail.get(key, True):
                self.combo_source.addItem(label, key)
            else:
                self.combo_source.addItem(f"{label}（当前平台不支持）", key)
        self.combo_source.currentIndexChanged.connect(self._on_source_kind_changed)
        form.addRow("类型", self.combo_source)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_adb_page())
        self.stack.addWidget(self._build_window_page())
        self.stack.addWidget(self._build_scrcpy_page())
        self.stack.addWidget(self._build_static_page())
        form.addRow(self.stack)
        root.addWidget(box)

        ctrl = QGroupBox("运行")
        ctrl_form = QFormLayout(ctrl)
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(1, 60)
        self.spin_fps.setValue(10)
        self.spin_fps.setSuffix(" fps")
        ctrl_form.addRow("抓帧频率", self.spin_fps)

        row = QHBoxLayout()
        self.btn_start = QPushButton("开始")
        self.btn_stop = QPushButton("停止")
        self.btn_stop.setEnabled(False)
        self.btn_start.clicked.connect(self.start_source)
        self.btn_stop.clicked.connect(self.stop_source)
        row.addWidget(self.btn_start)
        row.addWidget(self.btn_stop)
        ctrl_form.addRow(row)
        root.addWidget(ctrl)

        self.info = QLabel("未连接")
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#9aa4b2;font-size:12px;")
        root.addWidget(self.info)
        root.addStretch(1)

    def _build_adb_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.combo_device = QComboBox()
        self.combo_device.setEditable(True)
        form.addRow("设备", self.combo_device)
        row = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新设备")
        self.btn_refresh.clicked.connect(self.refresh_devices)
        self.btn_connect = QPushButton("无线连接")
        self.btn_connect.clicked.connect(self.connect_wifi)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_connect)
        form.addRow(row)
        self.edit_addr = QLineEdit()
        self.edit_addr.setPlaceholderText("192.168.1.8:5555")
        form.addRow("地址", self.edit_addr)
        self.chk_raw = QCheckBox("用 raw 快速截图（screencap 不带 -p，更快）")
        form.addRow(self.chk_raw)
        self.chk_rotate = QCheckBox("按屏幕旋转自动转正")
        form.addRow(self.chk_rotate)
        self.spin_maxw = QSpinBox()
        self.spin_maxw.setRange(0, 7680)
        self.spin_maxw.setValue(0)
        self.spin_maxw.setSpecialValueText("不限")
        form.addRow("最大宽度", self.spin_maxw)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _build_window_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        self.combo_window = QComboBox()
        form.addRow("窗口", self.combo_window)
        row = QHBoxLayout()
        btn = QPushButton("刷新窗口")
        btn.clicked.connect(self.refresh_windows)
        btn_emu = QPushButton("只列模拟器")
        btn_emu.clicked.connect(lambda: self.refresh_windows(emulator_only=True))
        row.addWidget(btn)
        row.addWidget(btn_emu)
        form.addRow(row)
        self.chk_render = QCheckBox("自动定位渲染子窗口（自动裁掉边框/工具栏）")
        self.chk_render.setChecked(True)
        form.addRow(self.chk_render)
        self.chk_restore = QCheckBox("最小化时先还原再截（个别模拟器需要）")
        form.addRow(self.chk_restore)
        size_row = QHBoxLayout()
        self.spin_tw = QSpinBox()
        self.spin_tw.setRange(0, 7680)
        self.spin_th = QSpinBox()
        self.spin_th.setRange(0, 7680)
        self.spin_tw.setSpecialValueText("自动")
        self.spin_th.setSpecialValueText("自动")
        size_row.addWidget(self.spin_tw)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.spin_th)
        form.addRow("设备真实解析度", size_row)
        btn_from_adb = QPushButton("从已连设备读取解析度")
        btn_from_adb.clicked.connect(self.fill_size_from_adb)
        form.addRow(btn_from_adb)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _build_scrcpy_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        row = QHBoxLayout()
        self.edit_jar = QLineEdit()
        self.edit_jar.setPlaceholderText("scrcpy-server.jar 路径（留空自动查找）")
        btn = QPushButton("…")
        btn.setFixedWidth(28)
        btn.clicked.connect(self.pick_jar)
        row.addWidget(self.edit_jar)
        row.addWidget(btn)
        form.addRow("server jar", row)
        self.spin_maxsize = QSpinBox()
        self.spin_maxsize.setRange(0, 4096)
        self.spin_maxsize.setValue(0)
        self.spin_maxsize.setSpecialValueText("原始分辨率")
        form.addRow("最大边长", self.spin_maxsize)
        self.spin_bitrate = QSpinBox()
        self.spin_bitrate.setRange(500_000, 50_000_000)
        self.spin_bitrate.setSingleStep(1_000_000)
        self.spin_bitrate.setValue(8_000_000)
        form.addRow("码率", self.spin_bitrate)
        layout.addLayout(form)
        tip = QLabel("需要 scrcpy-server.jar + pip install av"
                     "（python -m imeg.tools.fetch_scrcpy_server 可自动下载）")
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#8b95a3;font-size:11px;")
        layout.addWidget(tip)
        layout.addStretch(1)
        return page

    def _build_static_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.edit_image = QLineEdit()
        self.edit_image.setPlaceholderText("选择一张截图（离线做模板用）")
        btn = QPushButton("打开图片")
        btn.clicked.connect(self.pick_image)
        row.addWidget(self.edit_image)
        row.addWidget(btn)
        layout.addLayout(row)
        layout.addStretch(1)
        return page

    # ---------------------------------------------------------------- 事件
    def _on_source_kind_changed(self) -> None:
        key = self.combo_source.currentData()
        order = ["adb", "window", "scrcpy", "static"]
        self.stack.setCurrentIndex(order.index(key) if key in order else 0)

    def refresh_devices(self) -> None:
        self.combo_device.clear()
        try:
            devices = [d for d in self.adb.devices() if d.is_online]
        except Exception as exc:
            self.sigMessage.emit(f"adb devices 失败: {exc}", "error")
            return
        for d in devices:
            self.combo_device.addItem(f"{d.model or d.serial}  [{d.serial}]", d.serial)
        if not devices:
            self.combo_device.addItem("（无设备）", "")
        self.sigMessage.emit(f"发现 {len(devices)} 台设备", "info")

    def connect_wifi(self) -> None:
        addr = self.edit_addr.text().strip()
        if not addr:
            self.sigMessage.emit("请先填地址，如 192.168.1.8:5555", "warn")
            return
        if ":" not in addr:
            addr += ":5555"
        try:
            out = self.adb.connect(addr)
            self.sigMessage.emit(out, "info")
            self.refresh_devices()
        except Exception as exc:
            self.sigMessage.emit(str(exc), "error")

    def refresh_windows(self, emulator_only: bool = False) -> None:
        self.combo_window.clear()
        try:
            windows = list_windows(emulator_only=emulator_only)
        except Exception as exc:
            self.sigMessage.emit(f"枚举窗口失败: {exc}", "error")
            return
        for w in windows:
            self.combo_window.addItem(f"{w.title[:40]}  {w.w}x{w.h}", w.hwnd)
        if not windows:
            self.combo_window.addItem("（无窗口 / 非 Windows 平台）", 0)
        self.sigMessage.emit(f"发现 {len(windows)} 个窗口", "info")

    def fill_size_from_adb(self) -> None:
        serial = self.combo_device.currentData() or None
        try:
            size = self.adb.wm_size(serial)
        except Exception as exc:
            self.sigMessage.emit(str(exc), "error")
            return
        if size:
            self.spin_tw.setValue(size[0])
            self.spin_th.setValue(size[1])
            self.sigMessage.emit(f"设备解析度 {size[0]}x{size[1]}", "info")

    def pick_jar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 scrcpy-server.jar", "", "JAR (*.jar)")
        if path:
            self.edit_jar.setText(path)

    def pick_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.bmp *.jpg *.jpeg)")
        if path:
            self.edit_image.setText(path)

    # ---------------------------------------------------------------- 启动
    def _kwargs(self) -> dict:
        kind = self.combo_source.currentData()
        fps = float(self.spin_fps.value())
        if kind == "adb":
            return {"kind": "adb", "fps": fps,
                    "serial": self.combo_device.currentData() or None,
                    "raw": self.chk_raw.isChecked(),
                    "auto_rotate": self.chk_rotate.isChecked(),
                    "max_width": self.spin_maxw.value()}
        if kind == "window":
            target = None
            if self.spin_tw.value() and self.spin_th.value():
                target = (self.spin_tw.value(), self.spin_th.value())
            return {"kind": "window", "fps": fps,
                    "hwnd": int(self.combo_window.currentData() or 0),
                    "auto_render_window": self.chk_render.isChecked(),
                    "restore_if_minimized": self.chk_restore.isChecked(),
                    "target_size": target,
                    "adb_serial": self.combo_device.currentData() or None}
        if kind == "scrcpy":
            return {"kind": "scrcpy", "fps": fps,
                    "serial": self.combo_device.currentData() or None,
                    "server_jar": self.edit_jar.text().strip() or None,
                    "max_size": self.spin_maxsize.value(),
                    "bit_rate": self.spin_bitrate.value()}
        return {"kind": "static", "fps": fps, "path": self.edit_image.text().strip()}

    def start_source(self) -> None:
        self.stop_source()
        kw = self._kwargs()
        kind = kw.pop("kind")
        try:
            self.source = create_source(kind, adb=self.adb, **kw)
            self.source.start()
            if not self.source.wait_frame(timeout=8):
                raise RuntimeError(self.source.stats.last_error or "取不到第一帧画面")
        except Exception as exc:
            self.sigMessage.emit(f"启动失败: {exc}", "error")
            self.source = None
            return
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.sigMessage.emit(f"{SOURCE_LABELS[kind]} 已启动", "info")
        self.sigSourceChanged.emit(self.source)

    def stop_source(self) -> None:
        if self.source is not None:
            try:
                self.source.stop()
            except Exception:
                pass
            self.source = None
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.info.setText("未连接")

    def refresh_info(self) -> None:
        if self.source is None:
            return
        w, h = self.source.size()
        dev = self.source.device_size()
        st = self.source.stats
        dev_text = f"{dev[0]}x{dev[1]}" if dev else "未知"
        self.info.setText(
            f"画面 {w}x{h}    设备解析度 {dev_text}\n"
            f"FPS {st.fps:.1f}    帧数 {st.frames}    单帧 {st.last_cost_ms:.0f}ms\n"
            f"{('错误: ' + st.last_error) if st.last_error else ''}")
