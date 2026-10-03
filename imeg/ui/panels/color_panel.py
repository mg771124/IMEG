"""找色 / 多点找色面板。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.color import parse_color, rgb_to_hex
from ...core.palette import Palette, export_palette, import_palette
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

        # ------------------------------------------------------------ 配色产出
        box3 = QGroupBox("配色产出（导出给中控台 / 脚本）")
        v3 = QVBoxLayout(box3)
        self.chk_batch = QCheckBox("批量取色：Ctrl + 左键点画面即记录一个点")
        self.chk_batch.setToolTip("连着点就能快速产出一整套配色，不用一个个手填")
        v3.addWidget(self.chk_batch)
        self.list_palette = QListWidget()
        self.list_palette.setMaximumHeight(120)
        v3.addWidget(self.list_palette)

        row4 = QHBoxLayout()
        b_add = QPushButton("加入当前色")
        b_del = QPushButton("删除")
        b_clear2 = QPushButton("清空")
        b_add.clicked.connect(self.palette_add_current)
        b_del.clicked.connect(self.palette_remove)
        b_clear2.clicked.connect(self.palette_clear)
        for b in (b_add, b_del, b_clear2):
            row4.addWidget(b)
        v3.addLayout(row4)

        row5 = QHBoxLayout()
        b_export = QPushButton("导出…")
        b_import = QPushButton("导入…")
        b_copy = QPushButton("复制大漠串")
        b_export.clicked.connect(self.palette_export)
        b_import.clicked.connect(self.palette_import)
        b_copy.clicked.connect(self.palette_copy)
        for b in (b_export, b_import, b_copy):
            row5.addWidget(b)
        v3.addLayout(row5)
        root.addWidget(box3)

        self.palette = Palette()
        try:
            self.ctx.canvas.sigPick.connect(self.capture_point)
        except Exception:
            pass

    # ---------------------------------------------------------------- 配色产出
    def _device_info(self) -> dict:
        try:
            return self.ctx.dm.GetBindInfo()
        except Exception:
            return {}

    def capture_point(self, x: int, y: int) -> None:
        """批量取色：记录一个点（颜色 + 坐标）。"""
        if not self.chk_batch.isChecked():
            return
        color = self.ctx.color_at(x, y)
        tol = self.edit_color.text().split("-")[-1] if "-" in self.edit_color.text() else "101010"
        spec = f"{color}-{tol}"
        try:
            parse_color(spec)
        except Exception:
            spec = color
        name = f"色{len(self.palette) + 1}"
        self.palette.add(name=name, color=spec, offsets=self.offset_spec(), point=(x, y))
        self._refresh_palette_list()
        self.ctx.msg(f"已记录 {name} {spec} @({x},{y})", "info")

    def palette_add_current(self) -> None:
        x, y = self.ctx.last_pos()
        self.palette.add(name=f"色{len(self.palette) + 1}",
                         color=self.edit_color.text().strip(),
                         offsets=self.offset_spec(), point=(x, y))
        self._refresh_palette_list()

    def palette_remove(self) -> None:
        for item in self.list_palette.selectedItems():
            self.palette.remove(self.list_palette.row(item))
        self._refresh_palette_list()

    def palette_clear(self) -> None:
        self.palette.colors.clear()
        self._refresh_palette_list()

    def _refresh_palette_list(self) -> None:
        self.list_palette.clear()
        for c in self.palette.colors:
            pt = f"@({c.point[0]},{c.point[1]})" if c.point else ""
            tag = " [多点]" if c.is_multi else ""
            self.list_palette.addItem(f"{c.name}  {c.color}  {pt}{tag}")

    def palette_export(self) -> None:
        if not len(self.palette):
            self.ctx.msg("配色表是空的（先批量取几个点）", "warn")
            return
        self.palette.device = self._device_info()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配色", "palette.json", "JSON (*.json);;CSV (*.csv);;大漠文本 (*.txt)")
        if not path:
            return
        export_palette(self.palette, path)
        self.ctx.msg(f"已导出 {len(self.palette)} 条配色 -> {path}", "ok")

    def palette_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入配色", "", "配色文件 (*.json *.csv *.txt);;所有文件 (*)")
        if not path:
            return
        try:
            self.palette = import_palette(path)
        except Exception as exc:
            self.ctx.msg(f"导入失败: {exc}", "error")
            return
        self._refresh_palette_list()
        self.ctx.msg(f"已导入 {len(self.palette)} 条配色", "info")

    def palette_copy(self) -> None:
        if not len(self.palette):
            self.ctx.msg("配色表是空的", "warn")
            return
        QApplication.clipboard().setText(self.palette.to_text())
        self.ctx.msg("已复制（TAB 分隔：名称 / 颜色 / 偏移串 / 坐标 / 备注）", "info")

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
