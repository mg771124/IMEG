"""找色 / 多点找色面板。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.color import parse_color, rgb_to_hex
from ...core.types import Rect
from ..widgets import ColorChip

__all__ = ["ColorPanel"]

DIR_HINTS = ("0 左上→右下", "1 中心→外围", "2 右下→左上", "3 右上→左下", "4 左下→右上", "5 外围→中心")


class ColorPanel(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.base_point = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ------------------------------------------------------------ 找色
        box = QGroupBox("找色 (FindColor)")
        form = QFormLayout(box)
        row = QHBoxLayout()
        self.edit_color = QLineEdit("FFFFFF-101010")
        self.edit_color.textChanged.connect(self._sync_chip)
        self.chip = ColorChip("FFFFFF-101010")
        row.addWidget(self.edit_color, 1)
        row.addWidget(self.chip)
        form.addRow("颜色+偏色", row)

        row_btn = QHBoxLayout()
        b_pick = QPushButton("取鼠标处颜色")
        b_pick.clicked.connect(self.pick_hover)
        b_avg = QPushButton("选区平均色")
        b_avg.clicked.connect(self.pick_selection_avg)
        b_swap = QPushButton("前后景互换")
        b_swap.clicked.connect(self.swap_fg_bg)
        row_btn.addWidget(b_pick)
        row_btn.addWidget(b_avg)
        row_btn.addWidget(b_swap)
        form.addRow(row_btn)

        self.combo_dir = QComboBox()
        self.combo_dir.addItems(DIR_HINTS)
        form.addRow("方向", self.combo_dir)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 5000)
        self.spin_max.setValue(20)
        form.addRow("最多结果", self.spin_max)
        self.combo_region = QComboBox()
        self.combo_region.addItems(["全屏", "只查选区"])
        form.addRow("范围", self.combo_region)

        row2 = QHBoxLayout()
        b_find = QPushButton("找色")
        b_find_ex = QPushButton("找色Ex")
        b_find.clicked.connect(lambda: self.run_find(ex=False))
        b_find_ex.clicked.connect(lambda: self.run_find(ex=True))
        row2.addWidget(b_find)
        row2.addWidget(b_find_ex)
        form.addRow(row2)
        root.addWidget(box)

        # ------------------------------------------------------------ 多点找色
        box2 = QGroupBox("多点找色 (FindMultiColor)")
        v2 = QVBoxLayout(box2)
        row3 = QHBoxLayout()
        self.btn_base = QPushButton("① 设为基准点")
        self.btn_offset = QPushButton("② 添加偏移点")
        self.btn_clear_offsets = QPushButton("清空")
        self.btn_base.clicked.connect(self.set_base)
        self.btn_offset.clicked.connect(self.add_offset)
        self.btn_clear_offsets.clicked.connect(self.clear_offsets)
        for b in (self.btn_base, self.btn_offset, self.btn_clear_offsets):
            row3.addWidget(b)
        v2.addLayout(row3)
        self.lbl_base = QLabel("基准点：未设置")
        self.lbl_base.setStyleSheet("color:#9aa4b2;font-size:11px;")
        v2.addWidget(self.lbl_base)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["dx", "dy", "颜色"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v2.addWidget(self.table, 1)

        form2 = QFormLayout()
        self.spin_sim = QDoubleSpinBox()
        self.spin_sim.setRange(0.1, 1.0)
        self.spin_sim.setSingleStep(0.05)
        self.spin_sim.setValue(1.0)
        self.spin_sim.setToolTip("命中点数 / 总点数，1.0 表示所有点都要对上")
        form2.addRow("相似度", self.spin_sim)
        v2.addLayout(form2)
        b_multi = QPushButton("多点找色")
        b_multi.clicked.connect(self.run_multi)
        v2.addWidget(b_multi)
        root.addWidget(box2, 1)

        self.out = QLabel("")
        self.out.setWordWrap(True)
        self.out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.out.setStyleSheet("color:#8bd28b;font-family:Consolas,monospace;font-size:11px;")
        root.addWidget(self.out)

    # ---------------------------------------------------------------- 颜色编辑
    def _sync_chip(self) -> None:
        text = self.edit_color.text().strip()
        try:
            parse_color(text)
            self.chip.set_text(text)
        except Exception:
            pass

    def pick_hover(self) -> None:
        x, y = self.ctx.last_pos()
        hexcolor = self.ctx.color_at(x, y)
        tol = self.edit_color.text().split("-")[-1] if "-" in self.edit_color.text() else "101010"
        self.edit_color.setText(f"{hexcolor}-{tol}")

    def pick_selection_avg(self) -> None:
        img = self.ctx.selection_image()
        if img is None:
            self.ctx.msg("先框选一块区域", "warn")
            return
        avg = img.reshape(-1, 3).mean(axis=0)
        b, g, r = (int(v) for v in avg)
        tol = self.edit_color.text().split("-")[-1] if "-" in self.edit_color.text() else "101010"
        self.edit_color.setText(f"{rgb_to_hex((r, g, b))}-{tol}")

    def swap_fg_bg(self) -> None:
        """把"背景色-偏色"翻成"前景色"：常用于黑字白底互相切换。"""
        text = self.edit_color.text().strip()
        try:
            spec = parse_color(text)
        except Exception as exc:
            self.ctx.msg(str(exc), "error")
            return
        inv = tuple(255 - c for c in spec.rgb)
        self.edit_color.setText(f"{rgb_to_hex(inv)}-{spec.to_str().split('-')[-1]}")

    # ---------------------------------------------------------------- 找色
    def region(self) -> Rect | None:
        return self.ctx.selection() if self.combo_region.currentIndex() == 1 else None

    def run_find(self, ex: bool = False) -> None:
        r = self.region() or Rect(0, 0, 0, 0)
        color = self.edit_color.text().strip()
        direction = self.combo_dir.currentIndex()
        try:
            text = (self.ctx.dm.FindColorEx(r.x1, r.y1, r.x2, r.y2, color, direction,
                                            self.spin_max.value()) if ex
                    else self.ctx.dm.FindColor(r.x1, r.y1, r.x2, r.y2, color, direction))
        except Exception as exc:
            self.ctx.msg(f"找色失败: {exc}", "error")
            return
        self.out.setText(f"{'FindColorEx' if ex else 'FindColor'}: {text or '(无结果)'}")

        img = self.ctx.frame()
        if img is None:
            return
        from ...core.image import find_color
        pts = find_color(img, color, region=self.region(), direction=direction,
                         max_results=self.spin_max.value())
        self.ctx.canvas.clear_boxes()
        self.ctx.canvas.add_markers([(p.x, p.y) for p in pts])
        self.ctx.msg(f"找到 {len(pts)} 个点", "info")

    # ---------------------------------------------------------------- 多点找色
    def set_base(self) -> None:
        x, y = self.ctx.last_pos()
        self.base_point = (x, y)
        color = self.ctx.color_at(x, y)
        self.edit_color.setText(f"{color}-101010")
        self.lbl_base.setText(f"基准点：({x}, {y})  颜色 {color}")
        self.ctx.canvas.clear_boxes()
        self.ctx.canvas.add_markers([(x, y)], color=(0, 200, 255), size=13)

    def add_offset(self) -> None:
        if self.base_point is None:
            self.ctx.msg("先点「设为基准点」", "warn")
            return
        x, y = self.ctx.last_pos()
        dx, dy = x - self.base_point[0], y - self.base_point[1]
        color = self.ctx.color_at(x, y)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(str(dx)))
        self.table.setItem(row, 1, QTableWidgetItem(str(dy)))
        self.table.setItem(row, 2, QTableWidgetItem(f"{color}-101010"))
        self.ctx.canvas.add_markers([(x, y)], color=(255, 220, 0))

    def clear_offsets(self) -> None:
        self.table.setRowCount(0)
        self.base_point = None
        self.lbl_base.setText("基准点：未设置")

    def offset_spec(self) -> str:
        parts = []
        for row in range(self.table.rowCount()):
            dx = self.table.item(row, 0).text().strip() if self.table.item(row, 0) else "0"
            dy = self.table.item(row, 1).text().strip() if self.table.item(row, 1) else "0"
            color = self.table.item(row, 2).text().strip() if self.table.item(row, 2) else ""
            if color:
                parts.append(f"{dx}|{dy}|{color}")
        return ",".join(parts)

    def run_multi(self) -> None:
        if self.base_point is None:
            self.ctx.msg("先设基准点并添加偏移点", "warn")
            return
        r = self.region() or Rect(0, 0, 0, 0)
        spec = self.offset_spec()
        try:
            text = self.ctx.dm.FindMultiColor(r.x1, r.y1, r.x2, r.y2,
                                              self.edit_color.text().strip(), spec,
                                              self.spin_sim.value(), self.combo_dir.currentIndex())
        except Exception as exc:
            self.ctx.msg(f"多点找色失败: {exc}", "error")
            return
        self.out.setText(f"FindMultiColor: {text}")
        if text != "-1|-1":
            x, y = (int(v) for v in text.split("|"))
            self.ctx.canvas.clear_boxes()
            self.ctx.canvas.add_markers([(x, y)], color=(0, 255, 0), size=15)
            self.ctx.msg(f"命中 ({x}, {y})", "info")
        else:
            self.ctx.msg("没命中：可以降低相似度，或检查偏移点颜色", "warn")
