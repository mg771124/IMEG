"""找图面板：模板管理 + FindPic / FindPicEx（透明图自动生效）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ...core.image import draw_matches, save_image
from ...core.types import Rect

__all__ = ["FindPicPanel"]

DIR_HINTS = ("0 左上→右下", "1 中心→外围", "2 右下→左上", "3 右上→左下", "4 左下→右上", "5 外围→中心")


class FindPicPanel(QWidget):
    def __init__(self, ctx, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        self.results = []
        self._build_ui()

    # ---------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        box_dir = QGroupBox("模板目录（dm.SetPath）")
        form = QFormLayout(box_dir)
        row = QHBoxLayout()
        self.edit_path = QLineEdit(str(Path.home() / ".imeg" / "pic"))
        btn_browse = QPushButton("浏览")
        btn_browse.clicked.connect(self.browse_path)
        btn_use = QPushButton("应用")
        btn_use.clicked.connect(self.apply_path)
        row.addWidget(self.edit_path)
        row.addWidget(btn_browse)
        row.addWidget(btn_use)
        form.addRow(row)
        root.addWidget(box_dir)

        box_tpl = QGroupBox("模板")
        v = QVBoxLayout(box_tpl)
        self.list_tpl = QListWidget()
        self.list_tpl.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_tpl.setMaximumHeight(140)
        v.addWidget(self.list_tpl)
        row2 = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新列表")
        self.btn_new = QPushButton("从选区新建")
        self.btn_open = QPushButton("导入图片")
        self.btn_del = QPushButton("删除")
        self.btn_refresh.clicked.connect(self.refresh_templates)
        self.btn_new.clicked.connect(self.new_from_selection)
        self.btn_open.clicked.connect(self.import_image)
        self.btn_del.clicked.connect(self.delete_template)
        for b in (self.btn_refresh, self.btn_new, self.btn_open, self.btn_del):
            row2.addWidget(b)
        v.addLayout(row2)
        chk = QHBoxLayout()
        self.chk_transparent = QPushButton("把选中模板做成透明图 →")
        self.chk_transparent.setToolTip("切到「透明图」页签，用选区/模板抠背景")
        chk.addWidget(self.chk_transparent)
        v.addLayout(chk)
        root.addWidget(box_tpl)

        box_param = QGroupBox("参数")
        form2 = QFormLayout(box_param)
        self.spin_sim = QDoubleSpinBox()
        self.spin_sim.setRange(0.1, 1.0)
        self.spin_sim.setSingleStep(0.05)
        self.spin_sim.setValue(0.9)
        form2.addRow("相似度 sim", self.spin_sim)
        self.edit_delta = QLineEdit("101010")
        self.edit_delta.setToolTip("颜色容差，十六进制：101010 = 三通道各 ±0x10")
        form2.addRow("颜色容差", self.edit_delta)
        self.combo_dir = QComboBox()
        self.combo_dir.addItems(DIR_HINTS)
        form2.addRow("查找方向", self.combo_dir)
        self.spin_alpha = QSpinBox()
        self.spin_alpha.setRange(0, 255)
        self.spin_alpha.setValue(128)
        self.spin_alpha.setToolTip("alpha 小于该值的像素视为透明，不参与匹配")
        form2.addRow("透明阈值", self.spin_alpha)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 5000)
        self.spin_max.setValue(50)
        form2.addRow("最多结果", self.spin_max)
        self.combo_region = QComboBox()
        self.combo_region.addItems(["全屏", "只查选区"])
        form2.addRow("范围", self.combo_region)
        root.addWidget(box_param)

        row3 = QHBoxLayout()
        self.btn_find = QPushButton("找图 (FindPic)")
        self.btn_find_ex = QPushButton("找全部 (FindPicEx)")
        self.btn_find.clicked.connect(lambda: self.run(ex=False))
        self.btn_find_ex.clicked.connect(lambda: self.run(ex=True))
        row3.addWidget(self.btn_find)
        row3.addWidget(self.btn_find_ex)
        root.addLayout(row3)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["模板", "x", "y", "相似度"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.cellDoubleClicked.connect(self.on_result_picked)
        root.addWidget(self.table, 1)

        row4 = QHBoxLayout()
        self.btn_click = QPushButton("点击所选结果")
        self.btn_save = QPushButton("保存标注图")
        self.btn_click.clicked.connect(self.click_result)
        self.btn_save.clicked.connect(self.save_marked)
        row4.addWidget(self.btn_click)
        row4.addWidget(self.btn_save)
        root.addLayout(row4)

        self.out = QLabel("")
        self.out.setWordWrap(True)
        self.out.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.out.setStyleSheet("color:#8bd28b;font-family:Consolas,monospace;font-size:11px;")
        root.addWidget(self.out)

    # ---------------------------------------------------------------- 目录/模板
    def browse_path(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择模板目录", self.edit_path.text())
        if path:
            self.edit_path.setText(path)
            self.apply_path()

    def apply_path(self) -> None:
        ok = self.ctx.dm.SetPath(self.edit_path.text())
        self.ctx.msg(f"SetPath -> {self.ctx.dm.GetPath()} ({'成功' if ok else '失败'})",
                     "info" if ok else "error")
        self.refresh_templates()

    def refresh_templates(self) -> None:
        self.list_tpl.clear()
        path = Path(self.ctx.dm.GetPath())
        if not path.is_dir():
            return
        for f in sorted(path.glob("*")):
            if f.suffix.lower() not in (".png", ".bmp", ".jpg", ".jpeg"):
                continue
            if f.name.startswith("capture_"):   # 自己截的图不算模板
                continue
            self.list_tpl.addItem(QListWidgetItem(f.name))

    def _selected_names(self) -> list[str]:
        return [item.text() for item in self.list_tpl.selectedItems()]

    def new_from_selection(self) -> None:
        img = self.ctx.selection_image()
        if img is None:
            self.ctx.msg("先在画面上框选一块区域", "warn")
            return
        path = Path(self.ctx.dm.GetPath())
        path.mkdir(parents=True, exist_ok=True)
        target = path / f"tpl_{len(list(path.glob('tpl_*.png'))) + 1}.png"
        save_image(str(target), img)
        self.ctx.msg(f"已保存模板 {target}", "info")
        self.refresh_templates()

    def import_image(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "导入模板图片", "", "图片 (*.png *.bmp *.jpg)")
        path = Path(self.ctx.dm.GetPath())
        path.mkdir(parents=True, exist_ok=True)
        for f in files:
            try:
                from ...core.image import load_image
                save_image(str(path / Path(f).name), load_image(f))
            except Exception as exc:
                self.ctx.msg(f"导入失败 {f}: {exc}", "error")
        self.refresh_templates()

    def delete_template(self) -> None:
        path = Path(self.ctx.dm.GetPath())
        for name in self._selected_names():
            try:
                (path / name).unlink()
            except Exception as exc:
                self.ctx.msg(str(exc), "error")
        self.refresh_templates()

    # ---------------------------------------------------------------- 查找
    def run(self, ex: bool = False) -> None:
        names = self._selected_names() or [self.list_tpl.item(i).text()
                                           for i in range(self.list_tpl.count())]
        if not names:
            self.ctx.msg("先选一个模板（可多选，等价于 a.png|b.png）", "warn")
            return
        region = self.ctx.selection() if self.combo_region.currentIndex() == 1 else None
        sim = self.spin_sim.value()
        delta = self.edit_delta.text().strip() or "101010"
        direction = self.combo_dir.currentIndex()
        alpha = self.spin_alpha.value()

        r = region or Rect(0, 0, 0, 0)
        try:
            if ex:
                text = self.ctx.dm.FindPicEx(
                    r.x1, r.y1, r.x2, r.y2, pic_name="|".join(names), delta_color=delta,
                    sim=sim, direction=direction, max_results=self.spin_max.value(),
                    alpha_threshold=alpha)
                self.out.setText(f"FindPicEx: {text or '(无结果)'}")
            else:
                text = self.ctx.dm.FindPic(
                    r.x1, r.y1, r.x2, r.y2, pic_name="|".join(names), delta_color=delta,
                    sim=sim, direction=direction, alpha_threshold=alpha)
                self.out.setText(f"FindPic: {text}")
        except Exception as exc:
            self.ctx.msg(f"查找失败: {exc}", "error")
            return

        matches = self.ctx.dm.find_pic_list(
            "|".join(names), sim=sim, delta=delta, region=region,
            max_results=self.spin_max.value())
        self.results = matches
        self._fill_table(matches)
        self.ctx.canvas.clear_boxes()
        self.ctx.canvas.add_boxes([(m.x, m.y, m.w, m.h) for m in matches])
        self.ctx.msg(f"找到 {len(matches)} 个结果（sim>={sim}）", "info")
        if not matches:
            best = self._best_score("|".join(names), region, delta)
            if best is not None:
                self.ctx.msg(f"提示：最高相似度只有 {best:.3f}，试着降低 sim 或调大颜色容差", "warn")

    def _best_score(self, pic_name: str, region: Rect | None, delta) -> float | None:
        """找不到时用 sim=0 跑一遍，看看最好的位置有多像 —— 调试找图很有用。"""
        try:
            matches = self.ctx.dm.find_pic_list(pic_name, sim=0.0, delta=delta,
                                                region=region, max_results=1)
            return matches[0].score if matches else None
        except Exception:
            return None

    def _fill_table(self, matches) -> None:
        self.table.setRowCount(len(matches))
        for i, m in enumerate(matches):
            self.table.setItem(i, 0, QTableWidgetItem(m.name or str(m.index)))
            self.table.setItem(i, 1, QTableWidgetItem(str(m.x)))
            self.table.setItem(i, 2, QTableWidgetItem(str(m.y)))
            self.table.setItem(i, 3, QTableWidgetItem(f"{m.score:.3f}"))

    def on_result_picked(self, row: int, _col: int) -> None:
        if 0 <= row < len(self.results):
            m = self.results[row]
            self.ctx.canvas.clear_boxes()
            self.ctx.canvas.add_boxes([(m.x, m.y, m.w, m.h)], color=(255, 200, 0))

    def click_result(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.results):
            self.ctx.msg("先选中一行结果", "warn")
            return
        m = self.results[row]
        self.ctx.dm.input.click(m.center.x, m.center.y)
        self.ctx.msg(f"点击 ({m.center.x}, {m.center.y})", "info")

    def save_marked(self) -> None:
        img = self.ctx.frame()
        if img is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存标注图", "marked.png", "PNG (*.png)")
        if path:
            save_image(path, draw_matches(img, self.results))
            self.ctx.msg(f"已保存 {path}", "info")
