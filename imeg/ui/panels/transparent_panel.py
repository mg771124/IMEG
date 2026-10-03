"""透明图制作：点一下背景色 → 调容差 → 出带 alpha 的 PNG 模板。

生成的 PNG 在 FindPic 时会自动把透明区排除在匹配之外（跟大漠透明图一致）。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ...core.alpha import (
    TransparentOptions, alpha_stats, checkerboard, composite_preview, guess_background,
    make_transparent, save_template,
)
from ...core.color import rgb_to_hex
from ...core.image import ensure_bgr, load_image, save_image

__all__ = ["TransparentPanel"]


class _PreviewLabel(QLabel):
    """可点击的预览图（点击取背景色）。"""

    clicked = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(200)
        self.setStyleSheet("background:#202328;border:1px solid #333;")
        self._src_size: tuple[int, int] | None = None

    def set_pixmap(self, arr: np.ndarray) -> None:
        arr = np.ascontiguousarray(ensure_bgr(arr))
        h, w = arr.shape[:2]
        self._src_size = (w, h)
        qimg = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_BGR888).copy()
        self.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.width() - 4, 320, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._src_size is None or self.pixmap() is None:
            return
        pm = self.pixmap()
        x0 = (self.width() - pm.width()) // 2
        y0 = (self.height() - pm.height()) // 2
        px, py = int(event.position().x()) - x0, int(event.position().y()) - y0
        if not (0 <= px < pm.width() and 0 <= py < pm.height()):
            return
        sx = int(px * self._src_size[0] / pm.width())
        sy = int(py * self._src_size[1] / pm.height())
        self.clicked.emit(sx, sy)


class TransparentPanel(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.source: np.ndarray | None = None     # 原图 BGR
        self.result: np.ndarray | None = None     # BGRA
        self._build_ui()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        box_src = QGroupBox("① 载入图像")
        v = QVBoxLayout(box_src)
        row = QHBoxLayout()
        b_sel = QPushButton("从画面选区")
        b_frame = QPushButton("整帧画面")
        b_file = QPushButton("打开图片…")
        b_sel.clicked.connect(self.load_selection)
        b_frame.clicked.connect(self.load_frame)
        b_file.clicked.connect(self.load_file)
        for b in (b_sel, b_frame, b_file):
            row.addWidget(b)
        v.addLayout(row)
        root.addWidget(box_src)

        self.preview = _PreviewLabel()
        self.preview.clicked.connect(self.on_preview_click)
        tip = QLabel("👆 在预览图上点一下想抠掉的背景色")
        tip.setStyleSheet("color:#9aa4b2;font-size:11px;")
        root.addWidget(tip)
        root.addWidget(self.preview)

        box_bg = QGroupBox("② 背景色（可多个）")
        v2 = QVBoxLayout(box_bg)
        self.list_colors = QListWidget()
        self.list_colors.setMaximumHeight(84)
        v2.addWidget(self.list_colors)
        row2 = QHBoxLayout()
        b_guess = QPushButton("自动猜背景色")
        b_del = QPushButton("删除选中")
        b_clear = QPushButton("清空")
        b_guess.clicked.connect(self.auto_guess)
        b_del.clicked.connect(self.remove_color)
        b_clear.clicked.connect(self.clear_colors)
        for b in (b_guess, b_del, b_clear):
            row2.addWidget(b)
        v2.addLayout(row2)
        root.addWidget(box_bg)

        box_opt = QGroupBox("③ 参数")
        form = QFormLayout(box_opt)
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("只抠边缘连通区（推荐，主体内部同色不受影响）", "edge")
        self.combo_mode.addItem("全局同色都变透明（纯色底按钮/文字）", "global")
        form.addRow("范围", self.combo_mode)
        self.slider_tol = QSpinBox()
        self.slider_tol.setRange(0, 255)
        self.slider_tol.setValue(32)
        self.slider_tol.setSuffix(" （色差容差）")
        form.addRow("容差", self.slider_tol)
        self.combo_metric = QComboBox()
        self.combo_metric.addItem("三通道最大色差", "max")
        self.combo_metric.addItem("RGB 欧氏距离", "euclid")
        form.addRow("色差算法", self.combo_metric)
        self.spin_edge = QSpinBox()
        self.spin_edge.setRange(-20, 20)
        self.spin_edge.setValue(0)
        self.spin_edge.setToolTip(">0 保留更多主体（收缩透明区），<0 透明区外扩")
        form.addRow("边缘调整", self.spin_edge)
        self.spin_feather = QSpinBox()
        self.spin_feather.setRange(0, 50)
        self.spin_feather.setValue(0)
        self.spin_feather.setSuffix(" /10 像素")
        self.spin_feather.setToolTip("羽化半径 = 数值/10 像素，让边缘不那么硬")
        form.addRow("羽化", self.spin_feather)
        self.chk_soft = QCheckBox("接近背景色的像素给半透明（抗锯齿更好）")
        form.addRow(self.chk_soft)
        root.addWidget(box_opt)

        row3 = QHBoxLayout()
        b_gen = QPushButton("④ 生成透明图")
        b_gen.clicked.connect(self.generate)
        b_save = QPushButton("保存为模板")
        b_save.clicked.connect(self.save)
        b_copy = QPushButton("存回剪贴板")
        b_copy.clicked.connect(self.copy_to_clipboard)
        for b in (b_gen, b_save, b_copy):
            row3.addWidget(b)
        root.addLayout(row3)

        self.stats = QLabel("尚未生成")
        self.stats.setStyleSheet("color:#8bd28b;font-size:11px;")
        self.stats.setWordWrap(True)
        root.addWidget(self.stats)
        root.addStretch(1)

        # 参数变化时自动预览
        self.slider_tol.valueChanged.connect(self.generate)
        self.combo_mode.currentIndexChanged.connect(self.generate)
        self.combo_metric.currentIndexChanged.connect(self.generate)
        self.spin_edge.valueChanged.connect(self.generate)
        self.spin_feather.valueChanged.connect(self.generate)
        self.chk_soft.stateChanged.connect(self.generate)

    # ---------------------------------------------------------------- 载入
    def load_selection(self) -> None:
        img = self.ctx.selection_image()
        if img is None:
            self.ctx.msg("先在画面上框选一块区域", "warn")
            return
        self._set_source(img)

    def load_frame(self) -> None:
        img = self.ctx.frame()
        if img is None:
            self.ctx.msg("当前没有画面", "warn")
            return
        self._set_source(img.copy())

    def load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开图片", "", "图片 (*.png *.bmp *.jpg)")
        if not path:
            return
        try:
            self._set_source(load_image(path))
        except Exception as exc:
            self.ctx.msg(f"读取失败: {exc}", "error")

    def _set_source(self, img: np.ndarray) -> None:
        self.source = ensure_bgr(img)
        self.preview.set_pixmap(self.source)
        self.list_colors.clear()
        self.result = None
        self.auto_guess()
        self.generate()

    # ---------------------------------------------------------------- 背景色
    def on_preview_click(self, x: int, y: int) -> None:
        if self.source is None:
            return
        h, w = self.source.shape[:2]
        x, y = max(0, min(int(x), w - 1)), max(0, min(int(y), h - 1))
        b, g, r = (int(v) for v in self.source[y, x])
        self._add_color((r, g, b))

    def _add_color(self, rgb: tuple[int, int, int]) -> None:
        text = rgb_to_hex(rgb)
        for i in range(self.list_colors.count()):
            if self.list_colors.item(i).text() == text:
                return
        item = QListWidgetItem(text)
        item.setBackground(self._qcolor(rgb))
        item.setForeground(Qt.GlobalColor.black if sum(rgb) > 380 else Qt.GlobalColor.white)
        self.list_colors.addItem(item)
        self.generate()

    @staticmethod
    def _qcolor(rgb):
        from PySide6.QtGui import QColor
        return QColor(*rgb)

    def auto_guess(self) -> None:
        if self.source is None:
            return
        self._add_color(guess_background(self.source))

    def remove_color(self) -> None:
        for item in self.list_colors.selectedItems():
            self.list_colors.takeItem(self.list_colors.row(item))
        self.generate()

    def clear_colors(self) -> None:
        self.list_colors.clear()
        self.generate()

    def _targets(self) -> list[tuple[int, int, int]]:
        out = []
        for i in range(self.list_colors.count()):
            text = self.list_colors.item(i).text()
            out.append((int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)))
        return out

    # ---------------------------------------------------------------- 生成
    def generate(self) -> None:
        if self.source is None:
            return
        opts = TransparentOptions(
            targets=self._targets() or [guess_background(self.source)],
            tolerance=self.slider_tol.value(),
            mode=self.combo_mode.currentData(),
            metric=self.combo_metric.currentData(),
            feather=self.spin_feather.value() / 10.0,
            edge_adjust=self.spin_edge.value(),
            soft=self.chk_soft.isChecked(),
        )
        try:
            self.result = make_transparent(self.source, opts)
        except Exception as exc:
            self.ctx.msg(f"生成失败: {exc}", "error")
            return
        self.preview.set_pixmap(composite_preview(self.result, checkerboard(
            self.result.shape[1], self.result.shape[0])))
        st = alpha_stats(self.result)
        self.stats.setText(
            f"{st['width']}x{st['height']}    不透明 {st['opaque']} px "
            f"({st['opaque_ratio'] * 100:.1f}%)    透明 {st['transparent']} px")

    def save(self) -> None:
        if self.result is None:
            self.ctx.msg("先生成透明图", "warn")
            return
        from pathlib import Path
        default = str(Path(self.ctx.dm.GetPath()) / "tpl_alpha.png")
        path, _ = QFileDialog.getSaveFileName(self, "保存透明图模板", default, "PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        save_template(path, self.result, crop=True)
        self.ctx.msg(f"已保存透明图模板 {path}（透明区在找图时自动忽略）", "info")

    def copy_to_clipboard(self) -> None:
        if self.result is None:
            return
        from PySide6.QtWidgets import QApplication
        from tempfile import NamedTemporaryFile
        import os
        with NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp = f.name
        save_image(tmp, self.result)
        try:
            from PySide6.QtGui import QImage
            QApplication.clipboard().setImage(QImage(tmp))
            self.ctx.msg("已把透明图复制到剪贴板", "info")
        finally:
            os.unlink(tmp)
