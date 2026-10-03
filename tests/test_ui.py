"""离屏 UI 冒烟测试：把各个面板真的点一遍，确保没有运行时错误。

需要能 import PySide6（Linux 无显示器时设置 QT_QPA_PLATFORM=offscreen）。
"""
from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from imeg.core.capture import StaticCaptureSource  # noqa: E402
from imeg.core.image import save_image  # noqa: E402
from imeg.ui.main_window import MainWindow  # noqa: E402


def make_frame(w=400, h=300):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 40, 40)                 # BGR 深灰底
    img[50:110, 100:160] = (0, 0, 255)    # RGB FF0000 红块
    img[200:240, 300:340] = (255, 0, 0)   # RGB 0000FF 蓝块
    return img


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(app, tmp_path):
    frame = make_frame()
    path = tmp_path / "screen.png"
    save_image(str(path), frame)

    window = MainWindow()
    window.resize(1400, 900)
    source = StaticCaptureSource(str(path))
    source.start()
    window.dm.source = source
    window.dm.SetPath(str(tmp_path))
    window.canvas.set_image(source.image(), keep_view=False)
    window.show()
    for _ in range(3):
        app.processEvents()
    window.canvas.fit_view()
    app.processEvents()
    yield window
    window.close()


def test_canvas_shows_frame(win):
    assert win.canvas.image().shape == (300, 400, 3)
    assert win.canvas.image_size() == (400, 300)


def test_selection_and_template(win, tmp_path):
    win.canvas.set_selection(QRect(100, 50, 60, 60))   # 红块
    assert win.ctx.selection() is not None
    panel = win.panel_findpic
    panel.edit_path.setText(str(tmp_path / "pic"))   # 单独放模板，别把整张截图也当模板
    panel.apply_path()
    win.canvas.set_selection(QRect(100, 50, 60, 60))
    panel.new_from_selection()
    panel.refresh_templates()
    assert panel.list_tpl.count() >= 1

    panel.spin_sim.setValue(0.8)
    panel.combo_region.setCurrentIndex(0)
    panel.run(ex=False)
    assert len(panel.results) >= 1
    assert (panel.results[0].x, panel.results[0].y) == (100, 50)
    assert "0|100|50" in panel.out.text()

    panel.run(ex=True)
    assert panel.table.rowCount() >= 1


def test_color_panel(win):
    panel = win.panel_color
    panel.edit_color.setText("FF0000-101010")
    panel.run_find(ex=False)
    assert "100|50" in panel.out.text()

    # 多点找色：基准点 + 一个偏移点
    win.ctx.hover = (100, 50, (255, 0, 0))
    panel.set_base()
    assert panel.base_point == (100, 50)
    win.ctx.hover = (110, 60, (255, 0, 0))
    panel.add_offset()
    assert panel.table.rowCount() == 1
    panel.run_multi()
    assert panel.out.text().startswith("FindMultiColor: 100|50")


def test_transparent_panel(win, tmp_path):
    panel = win.panel_transparent
    panel._set_source(make_frame())
    assert panel.source is not None
    panel.list_colors.clear()
    panel._add_color((40, 40, 40))         # 背景深灰
    panel.slider_tol.setValue(10)
    panel.generate()
    from imeg.core.image import split_alpha
    _, alpha = split_alpha(panel.result)
    assert alpha[10, 10] == 0              # 背景变透明
    assert alpha[80, 130] == 255           # 红块保留

    out = tmp_path / "tpl_alpha.png"
    panel.result = panel.result
    from imeg.core.alpha import save_template
    save_template(str(out), panel.result)
    assert out.is_file()


def test_input_panel_null_controller(win):
    panel = win.panel_input
    panel.spin_x.setValue(10)
    panel.spin_y.setValue(20)
    panel.apply_mode()                     # auto -> null（静态源）
    assert panel.lbl_mode.text().startswith("当前：")
    win.ctx.hover = (33, 44, (0, 0, 0))
    panel.from_mouse()
    assert (panel.spin_x.value(), panel.spin_y.value()) == (33, 44)


def test_script_panel(win):
    panel = win.panel_script
    panel.input.setText('dm.GetColor(120, 70)')
    panel.run_line()
    assert "FF0000" in panel.output.toPlainText()

    from pathlib import Path
    save_image(str(Path(win.dm.GetPath()) / "tpl_1.png"), make_frame()[50:110, 100:160])
    panel.input.setText('dm.FindPic(0,0,0,0,"tpl_1.png","101010",0.8,0)')
    panel.run_line()
    assert "0|100|50" in panel.output.toPlainText()

    panel.editor.setPlainText("print('hello from script')\nw, h = dm.GetClientSize()\nprint(w, h)\n")
    panel.run_script()
    assert "hello from script" in panel.output.toPlainText()
    assert "400 300" in panel.output.toPlainText()


def test_ocr_panel_fontlib(win, tmp_path):
    import cv2

    def render(text, size=40):
        img = np.zeros((size * 2, size * 2, 3), np.uint8)
        cv2.putText(img, text, (int(size * 0.4), int(size * 1.3)),
                    cv2.FONT_HERSHEY_SIMPLEX, size / 30.0, (255, 255, 255), 3, cv2.LINE_AA)
        return img

    dict_dir = tmp_path / "fontlib"
    panel = win.panel_ocr
    panel.edit_dict.setText(str(dict_dir))
    from imeg.core.ocr import FontLib
    lib = FontLib(str(dict_dir))
    for ch in "OK":
        lib.add(ch, render(ch), thresh=1)

    panel.combo_backend.setCurrentIndex(3)   # fontlib
    panel.apply_backend()
    assert panel.engine().current.name == "fontlib"

    win.dm.source = StaticCaptureSource(str(_save(render("OK"), tmp_path)))
    panel.edit_color.setText("FFFFFF-303030")
    panel.combo_region.setCurrentIndex(0)
    panel.run()
    assert panel.table.rowCount() >= 2
    assert "".join(panel.table.item(i, 0).text() for i in range(panel.table.rowCount())) == "OK"


def _save(img, tmp_path) -> str:
    p = tmp_path / "ocr.png"
    save_image(str(p), img)
    return str(p)
