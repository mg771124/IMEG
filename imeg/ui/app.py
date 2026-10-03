"""启动 IMEG 图形界面。"""
from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    from PySide6.QtWidgets import QApplication

    argv = list(sys.argv if argv is None else argv)

    # Windows 上开启 DPI 感知，否则高分屏截图会被缩水
    try:
        from ..core.capture import win32
        win32.set_dpi_awareness()
    except Exception:
        pass

    app = QApplication(argv)
    app.setApplicationName("IMEG")
    app.setOrganizationName("IMEG")
    app.setStyle("Fusion")

    qss_path = Path(__file__).with_name("style.qss")
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    from .main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
