"""通用控件：图像画布（缩放/选区/取色）、日志台、带滑杆的数值输入。"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsScene, QGraphicsView,
    QHBoxLayout, QLabel, QSlider, QTextEdit, QWidget,
)

from ..core.image import ensure_bgr

__all__ = ["ImageView", "LogConsole", "SpinSlider", "ColorChip"]


def _to_qimage(arr: np.ndarray) -> QImage:
    """numpy BGR/BGRA -> QImage（会拷贝一份，避免悬垂指针）。"""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    if arr.ndim == 3 and arr.shape[2] == 4:
        img = QImage(arr.data, w, h, 4 * w, QImage.Format.Format_ARGB32)
    else:
        img = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_BGR888)
    return img.copy()


class ImageView(QGraphicsView):
    """显示截图，支持缩放、框选、悬停取色。"""

    sigHover = Signal(int, int, tuple)          # 图像坐标 + (r,g,b)
    sigSelection = Signal(QRect)                # 选区（图像坐标，含右下端点）
    sigContext = Signal(int, int)               # 右键点击位置
    sigPick = Signal(int, int)                  # Ctrl+左键：取一个点（批量采色用）

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pix_item = QGraphicsPixmapItem()
        self._pix_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._scene.addItem(self._pix_item)
        self._overlay_item = QGraphicsPixmapItem()
        self._overlay_item.setTransformationMode(Qt.TransformationMode.FastTransformation)
        self._overlay_item.setVisible(False)
        self._scene.addItem(self._overlay_item)

        self._sel_item = QGraphicsRectItem()
        self._sel_item.setPen(QPen(QColor(0, 200, 255), 1.5, Qt.PenStyle.DashLine))
        self._sel_item.setBrush(QBrush(QColor(0, 200, 255, 40)))
        self._sel_item.setZValue(10)
        self._sel_item.setVisible(False)
        self._scene.addItem(self._sel_item)

        self._boxes: list[QGraphicsRectItem] = []
        self._crosshair: list[QGraphicsRectItem] = []

        self._image: np.ndarray | None = None
        self._start = QPointF()
        self._selecting = False
        self._space_down = False
        self._scale = 1.0
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.setBackgroundBrush(QColor(28, 30, 34))
        self.setFrameShape(QFrame.Shape.NoFrame)

    # ---------------------------------------------------------------- 图像
    def set_image(self, arr: np.ndarray, keep_view: bool = True) -> None:
        """显示一帧（BGR 或 BGRA）。"""
        if arr is None:
            return
        self._image = arr
        pix = QPixmap.fromImage(_to_qimage(ensure_bgr(arr)))
        self._pix_item.setPixmap(pix)
        self._scene.setSceneRect(QRectF(pix.rect()))
        if not keep_view:
            self.fit_view()

    def set_overlay(self, arr: np.ndarray | None) -> None:
        """叠加一层（例如透明图棋盘格合成预览），``None`` 关闭。"""
        if arr is None:
            self._overlay_item.setVisible(False)
            self._overlay_item.setPixmap(QPixmap())
            return
        self._overlay_item.setPixmap(QPixmap.fromImage(_to_qimage(ensure_bgr(arr))))
        self._overlay_item.setVisible(True)

    def image(self) -> np.ndarray | None:
        return self._image

    def image_size(self) -> tuple[int, int]:
        if self._image is None:
            return (0, 0)
        return int(self._image.shape[1]), int(self._image.shape[0])

    # ---------------------------------------------------------------- 视图
    def fit_view(self) -> None:
        if self._image is None:
            return
        self.fitInView(self._pix_item, Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.transform().m11()

    def set_zoom(self, scale: float) -> None:
        self.resetTransform()
        self.scale(scale, scale)
        self._scale = scale

    # ---------------------------------------------------------------- 结果框
    def clear_boxes(self) -> None:
        for item in self._boxes + self._crosshair:
            self._scene.removeItem(item)
        self._boxes.clear()
        self._crosshair.clear()

    def add_boxes(self, rects, color=(0, 255, 0), tag: str = "") -> None:
        """在画面上画匹配框。``rects`` 为 ``(x, y, w, h)`` 序列。"""
        for x, y, w, h in rects:
            item = QGraphicsRectItem(QRectF(float(x), float(y), float(w), float(h)))
            item.setPen(QPen(QColor(*color), 2))
            item.setZValue(20)
            self._scene.addItem(item)
            self._boxes.append(item)

    def add_markers(self, points, color=(255, 80, 80), size: int = 9) -> None:
        for x, y in points:
            item = QGraphicsRectItem(QRectF(x - size / 2, y - size / 2, size, size))
            item.setPen(QPen(QColor(*color), 2))
            item.setZValue(21)
            self._scene.addItem(item)
            self._crosshair.append(item)

    # ---------------------------------------------------------------- 选区
    def selection(self) -> QRect | None:
        if not self._sel_item.isVisible():
            return None
        r = self._sel_item.rect()
        w, h = self.image_size()
        x1, y1 = max(0, int(r.left())), max(0, int(r.top()))
        x2, y2 = min(w - 1, int(r.right())), min(h - 1, int(r.bottom()))
        if x2 <= x1 or y2 <= y1:
            return None
        return QRect(x1, y1, x2 - x1 + 1, y2 - y1 + 1)

    def set_selection(self, rect: QRect | None) -> None:
        if rect is None:
            self._sel_item.setVisible(False)
            return
        self._sel_item.setRect(QRectF(rect))
        self._sel_item.setVisible(True)

    def clear_selection(self) -> None:
        self._sel_item.setVisible(False)

    # ---------------------------------------------------------------- 事件
    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = self.mapToScene(event.position().toPoint())
        if event.button() == Qt.MouseButton.MiddleButton or self._space_down:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            super().mousePressEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.sigPick.emit(int(pos.x()), int(pos.y()))
                return
            self._start = pos
            self._selecting = True
            self._sel_item.setRect(QRectF(pos, pos))
            self._sel_item.setVisible(True)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pos = self.mapToScene(event.position().toPoint())
        if self._selecting:
            rect = QRectF(self._start, pos).normalized()
            self._sel_item.setRect(rect)
        x, y = int(pos.x()), int(pos.y())
        w, h = self.image_size()
        rgb = (0, 0, 0)
        if self._image is not None and 0 <= x < w and 0 <= y < h:
            b, g, r = (int(v) for v in self._image[y, x, :3])
            rgb = (r, g, b)
            self.sigHover.emit(x, y, rgb)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._selecting and event.button() == Qt.MouseButton.LeftButton:
            self._selecting = False
            rect = self.selection()
            if rect is None:
                self._sel_item.setVisible(False)
            else:
                self._sel_item.setRect(QRectF(rect))
                self.sigSelection.emit(rect)
        if self.dragMode() == QGraphicsView.DragMode.ScrollHandDrag:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._image is None:
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.scale(factor, factor)
        self._scale = self.transform().m11()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        pos = self.mapToScene(event.position().toPoint())
        self.sigContext.emit(int(pos.x()), int(pos.y()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_down = True
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._space_down = False
        super().keyReleaseEvent(event)


class LogConsole(QTextEdit):
    """底部的日志台。"""

    def __init__(self, parent: QWidget | None = None, max_lines: int = 800) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.max_lines = max_lines
        self.setStyleSheet("QTextEdit{background:#16181c;color:#c8ccd4;font-family:Consolas,monospace;font-size:12px;}")

    def append_line(self, text: str, color: str | None = None) -> None:
        from PySide6.QtGui import QTextCursor
        color = color or "#c8ccd4"
        self.moveCursor(QTextCursor.MoveOperation.End)
        self.insertHtml(f'<span style="color:{color}">{text}</span><br>')
        if self.document().blockCount() > self.max_lines:
            cursor = QTextCursor(self.document())
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
        self.ensureCursorVisible()


class SpinSlider(QWidget):
    """滑杆 + 数值显示的一体化控件。"""

    valueChanged = Signal(int)

    def __init__(self, label: str, minimum: int = 0, maximum: int = 100, value: int = 0,
                 suffix: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.suffix = suffix
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label)
        self.label.setMinimumWidth(72)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        self.value_label = QLabel(f"{value}{suffix}")
        self.value_label.setMinimumWidth(56)
        layout.addWidget(self.label)
        layout.addWidget(self.slider, 1)
        layout.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_change)

    def _on_change(self, value: int) -> None:
        self.value_label.setText(f"{value}{self.suffix}")
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, value: int) -> None:
        self.slider.setValue(int(value))


class ColorChip(QLabel):
    """小色块 + 颜色串。"""

    def __init__(self, text: str = "FFFFFF-000000", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(22)
        self.setFrameShape(QFrame.Shape.Box)
        self.setAutoFillBackground(True)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        from ..core.color import hex_to_rgb, parse_color
        self._text = str(text)
        try:
            r, g, b = hex_to_rgb(parse_color(self._text).to_str().split("-")[0])
        except Exception:
            r = g = b = 128
        self.setStyleSheet(
            f"background:rgb({r},{g},{b});color:{'#000' if (r + g + b) > 380 else '#fff'};"
            "padding:2px 6px;font-family:Consolas,monospace;")
        self.setText(self._text)

    def text(self) -> str:
        return self._text
