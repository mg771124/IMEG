"""离屏渲染 UI 预览图（沙箱/无显示器环境下用它生成截图）。

    python tools/render_ui_preview.py out.png [--tab transparent|findpic]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def make_demo_frame(w: int = 720, h: int = 1560) -> np.ndarray:
    """造一张"手机界面"截图，用来演示找图/找色/透明图。"""
    import cv2

    img = np.zeros((h, w, 3), np.uint8)
    for y in range(h):  # 渐变背景
        t = y / h
        img[y, :] = (int(28 + 26 * t), int(32 + 30 * t), int(46 + 40 * t))

    cv2.rectangle(img, (0, 0), (w, 72), (36, 40, 52), -1)          # 状态栏
    cv2.putText(img, "09:41", (28, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (235, 238, 245), 2)
    cv2.putText(img, "IMEG DEMO", (w // 2 - 90, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (200, 210, 225), 2)
    cv2.rectangle(img, (w - 96, 24), (w - 30, 50), (120, 200, 140), 2)
    cv2.rectangle(img, (w - 92, 28), (w - 34, 46), (120, 200, 140), -1)

    cv2.putText(img, "FindPic / FindColor", (40, 168), cv2.FONT_HERSHEY_SIMPLEX, 1.15,
                (240, 242, 248), 2)
    cv2.putText(img, "ADB background capture", (40, 212), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (150, 165, 185), 1)

    # 几个"按钮"，用于找图/找色
    palette = [(66, 133, 244), (219, 68, 55), (244, 180, 0), (15, 157, 88)]
    for i, color in enumerate(palette):
        x = 40 + (i % 2) * 340
        y = 280 + (i // 2) * 190
        cv2.rectangle(img, (x, y), (x + 300, y + 150), color, -1)
        cv2.rectangle(img, (x, y), (x + 300, y + 150), (255, 255, 255), 2)
        cv2.putText(img, f"BTN {i + 1}", (x + 90, y + 88), cv2.FONT_HERSHEY_SIMPLEX,
                    1.0, (255, 255, 255), 2)

    # 一个"圆角图标 + 纯色底"，适合演示透明图抠图
    cx, cy, r = w // 2, 800, 150
    cv2.circle(img, (cx, cy), r + 26, (245, 245, 248), -1)
    cv2.circle(img, (cx, cy), r, (52, 152, 219), -1)
    cv2.putText(img, "A", (cx - 44, cy + 56), cv2.FONT_HERSHEY_SIMPLEX, 3.2, (255, 255, 255), 8)

    cv2.rectangle(img, (40, 1030), (w - 40, 1104), (58, 63, 78), -1)
    cv2.putText(img, "192.168.1.8:5555  connected", (60, 1078), cv2.FONT_HERSHEY_SIMPLEX,
                0.65, (190, 200, 215), 1)
    for i in range(5):
        y = 1140 + i * 76
        cv2.rectangle(img, (40, y), (w - 40, y + 58), (44, 48, 60), -1)
        cv2.circle(img, (86, y + 29), 18, (110, 190, 220), -1)
        cv2.putText(img, f"list item {i + 1}", (124, y + 38), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (205, 212, 225), 1)
    return img


def render(out_path: str, tab: str = "transparent") -> str:
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QApplication

    from imeg.core.capture import create_source
    from imeg.core.image import save_image
    from imeg.ui.main_window import MainWindow

    frame = make_demo_frame()
    tmp = Path("/tmp/imeg_demo_frame.png")
    save_image(str(tmp), frame)

    app = QApplication([])
    qss = Path(ROOT / "imeg/ui/style.qss")
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    app.setStyle("Fusion")

    win = MainWindow()
    win.resize(1600, 940)

    source = create_source("static", path=str(tmp))
    source.start()
    win.dm.source = source
    win.canvas.set_image(source.image(), keep_view=False)

    if tab == "transparent":
        # 透明图：把中间那个圆形图标（白色圆底）抠成透明
        win.tabs.setCurrentWidget(win.panel_transparent)
        panel = win.panel_transparent
        panel._set_source(frame[640:960, 210:510].copy())
        panel.slider_tol.setValue(40)
        panel.generate()
    else:
        win.tabs.setCurrentWidget(win.panel_findpic)
        win.panel_findpic.refresh_templates()
        win.canvas.set_selection(QRect(40, 280, 300, 150))
        win.canvas.add_boxes([(40, 280, 300, 150)], color=(0, 255, 120))
        win.canvas.add_boxes([(380, 280, 300, 150)], color=(0, 255, 120))
        win.canvas.add_boxes([(40, 470, 300, 150)], color=(0, 255, 120))
        win.canvas.add_boxes([(380, 470, 300, 150)], color=(0, 255, 120))

    win.show()
    for _ in range(4):
        app.processEvents()
    win.canvas.fit_view()
    app.processEvents()
    win.log("预览模式：静态演示画面（真实使用请选择 ADB / 窗口 / scrcpy 源）", "ok")
    win.log("画面 720x1560    设备解析度 720x1560", "info")
    for _ in range(3):
        app.processEvents()

    pix = win.grab()
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out))
    return str(out)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "/home/user/IMEG/docs/ui-preview.png"
    tab = "findpic" if "--tab" in sys.argv and "findpic" in sys.argv else "transparent"
    print(render(out, tab=tab))
