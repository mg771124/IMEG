"""OCR 面板：大漠风格的 Ocr / FindStr，支持 rapidocr / tesseract / 自己的字库。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.ocr import OcrEngine
from ...core.types import Rect

__all__ = ["OcrPanel"]


class OcrPanel(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.results = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        box = QGroupBox("引擎")
        form = QFormLayout(box)
        self.combo_backend = QComboBox()
        self.combo_backend.addItem("auto（按可用性自动选）", "auto")
        self.combo_backend.addItem("rapidocr（推荐，中文最好，需 pip install rapidocr-onnxruntime）", "rapidocr")
        self.combo_backend.addItem("tesseract（需安装 tesseract-ocr）", "tesseract")
        self.combo_backend.addItem("fontlib 字库（零依赖，用自己的字符模板）", "fontlib")
        form.addRow("后端", self.combo_backend)
        b_apply = QPushButton("应用")
        b_apply.clicked.connect(self.apply_backend)
        form.addRow(b_apply)
        self.lbl_avail = QLabel("")
        self.lbl_avail.setStyleSheet("color:#9aa4b2;font-size:11px;")
        form.addRow(self.lbl_avail)
        root.addWidget(box)

        row_dict = QHBoxLayout()
        self.edit_dict = QLineEdit(str(Path.home() / ".imeg" / "fontlib"))
        b_dict = QPushButton("字库目录…")
        b_dict.clicked.connect(self.pick_dict)
        row_dict.addWidget(self.edit_dict)
        row_dict.addWidget(b_dict)
        form.addRow("字库目录", row_dict)
        root.addWidget(box)

        box2 = QGroupBox("识别参数")
        form2 = QFormLayout(box2)
        self.edit_color = QLineEdit("FFFFFF-303030")
        self.edit_color.setToolTip("只保留与之相近的像素（大漠 Ocr 的颜色过滤），留空则不过滤")
        form2.addRow("文字颜色", self.edit_color)
        self.spin_sim = QDoubleSpinBox()
        self.spin_sim.setRange(0.1, 1.0)
        self.spin_sim.setSingleStep(0.05)
        self.spin_sim.setValue(0.9)
        form2.addRow("颜色相似度", self.spin_sim)
        self.combo_region = QComboBox()
        self.combo_region.addItems(["全屏", "只识别选区"])
        form2.addRow("范围", self.combo_region)
        b_run = QPushButton("识别 (Ocr)")
        b_run.clicked.connect(self.run)
        form2.addRow(b_run)
        root.addWidget(box2)

        box3 = QGroupBox("找字 (FindStr)")
        form3 = QFormLayout(box3)
        self.edit_find = QLineEdit()
        self.edit_find.setPlaceholderText("要找的文字，多个用 | 分隔")
        form3.addRow("目标", self.edit_find)
        b_find = QPushButton("找字")
        b_find.clicked.connect(self.run_find)
        form3.addRow(b_find)
        root.addWidget(box3)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文字", "x", "y", "置信度"])
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        box4 = QGroupBox("扩充字库（把选区存成一个字符）")
        row4 = QHBoxLayout()
        self.edit_char = QLineEdit()
        self.edit_char.setPlaceholderText("字符，如 中")
        self.edit_char.setMaximumWidth(80)
        b_save_char = QPushButton("把当前选区存进字库")
        b_save_char.clicked.connect(self.save_glyph)
        row4.addWidget(self.edit_char)
        row4.addWidget(b_save_char)
        box4.setLayout(row4)
        root.addWidget(box4)

        self.out = QLabel("")
        self.out.setWordWrap(True)
        self.out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.out.setStyleSheet("color:#8bd28b;font-family:Consolas,monospace;font-size:11px;")
        root.addWidget(self.out)

        self.refresh_available()

    # ---------------------------------------------------------------- 引擎
    def engine(self) -> OcrEngine:
        dm = self.ctx.dm
        if dm.ocr is None:
            dm.ocr = OcrEngine(backend="auto", dict_dir=self.edit_dict.text())
        return dm.ocr

    def refresh_available(self) -> None:
        try:
            avail = self.engine().available()
        except Exception:
            avail = []
        self.lbl_avail.setText(f"当前环境可用: {', '.join(avail) or '（无，请 pip install rapidocr-onnxruntime）'}")

    def apply_backend(self) -> None:
        name = self.combo_backend.currentData()
        engine = self.engine()
        try:
            engine.backends["fontlib"].lib.dict_dir = Path(self.edit_dict.text())
            engine.set_backend(name)
            self.ctx.msg(f"OCR 后端 -> {engine.current.info()}", "info")
            self.refresh_available()
        except Exception as exc:
            self.ctx.msg(f"切换失败: {exc}", "error")

    def pick_dict(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择字库目录", self.edit_dict.text())
        if path:
            self.edit_dict.setText(path)

    # ---------------------------------------------------------------- 识别
    def region(self) -> Rect | None:
        return self.ctx.selection() if self.combo_region.currentIndex() == 1 else None

    def run(self) -> None:
        r = self.region() or Rect(0, 0, 0, 0)
        color = self.edit_color.text().strip()
        try:
            text = self.ctx.dm.Ocr(r.x1, r.y1, r.x2, r.y2, color, self.spin_sim.value())
        except Exception as exc:
            self.ctx.msg(f"识别失败: {exc}", "error")
            return
        self.out.setText(f"Ocr: {text or '(无结果)'}")
        img = self.ctx.frame()
        if img is None:
            return
        try:
            self.results = self.engine().recognize(img, region=self.region(),
                                                   color=color or None, sim=self.spin_sim.value())
        except Exception as exc:
            self.ctx.msg(str(exc), "error")
            return
        self.table.setRowCount(len(self.results))
        for i, res in enumerate(self.results):
            self.table.setItem(i, 0, QTableWidgetItem(res.text))
            self.table.setItem(i, 1, QTableWidgetItem(str(res.x)))
            self.table.setItem(i, 2, QTableWidgetItem(str(res.y)))
            self.table.setItem(i, 3, QTableWidgetItem(f"{res.score:.2f}"))
        self.ctx.canvas.clear_boxes()
        self.ctx.canvas.add_boxes([(r_.x, r_.y, r_.w, r_.h) for r_ in self.results],
                                  color=(120, 200, 255))
        self.ctx.msg(f"识别到 {len(self.results)} 个文本块", "info")

    def run_find(self) -> None:
        target = self.edit_find.text().strip()
        if not target:
            self.ctx.msg("先填要找的文字", "warn")
            return
        r = self.region() or Rect(0, 0, 0, 0)
        try:
            text = self.ctx.dm.FindStr(r.x1, r.y1, r.x2, r.y2, target,
                                       self.edit_color.text().strip(), self.spin_sim.value())
        except Exception as exc:
            self.ctx.msg(f"找字失败: {exc}", "error")
            return
        self.out.setText(f"FindStr: {text}")
        if text != "-1|-1|-1":
            _, x, y = text.split("|")
            self.ctx.canvas.clear_boxes()
            self.ctx.canvas.add_markers([(int(x), int(y))], color=(0, 255, 120), size=15)
            self.ctx.msg(f"命中 ({x}, {y})", "info")
        else:
            self.ctx.msg("没找到", "warn")

    def save_glyph(self) -> None:
        ch = self.edit_char.text().strip()
        if len(ch) != 1:
            self.ctx.msg("填一个字符（比如 中）", "warn")
            return
        img = self.ctx.selection_image()
        if img is None:
            self.ctx.msg("先框选这个字符", "warn")
            return
        engine = self.engine()
        try:
            engine.backends["fontlib"].lib.dict_dir = Path(self.edit_dict.text())
            path = engine.backends["fontlib"].lib.add(ch, img, thresh=1)
            self.ctx.msg(f"已把「{ch}」存入字库: {path}", "info")
        except Exception as exc:
            self.ctx.msg(f"保存失败: {exc}", "error")
