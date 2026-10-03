"""启动 IMEG 图形界面。"""
from __future__ import annotations

import sys
from pathlib import Path

__all__ = ["main"]


def _crash_log_path() -> Path:
    """打包成 EXE 后没有控制台，出错时把 traceback 写到日志文件。"""
    import os
    if getattr(sys, "frozen", False):                     # PyInstaller 打包后
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parents[2]
    try:
        log = base / "imeg_crash.log"
        log.touch(exist_ok=True)
        return log
    except OSError:                                        # 只读目录（比如 Program Files）
        return Path(os.environ.get("TEMP", "/tmp")) / "imeg_crash.log"


def _install_excepthook() -> None:
    import traceback

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        try:
            path = _crash_log_path()
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n===== IMEG {_version()} crash =====\n{text}\n")
            if not getattr(sys, "frozen", False):
                sys.__excepthook__(exc_type, exc, tb)
                return
            # GUI 模式下弹个框，别让用户以为程序没启动
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(None, "IMEG 出错了",
                                     f"已把错误信息写到：\n{path}\n\n{exc}")
            except Exception:
                pass
        except Exception:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def _version() -> str:
    from .. import __version__
    return __version__


def _selftest() -> int:
    """打包后自检：确认所有模块都打进去了（构建脚本会用）。"""
    import importlib
    import platform

    print(f"IMEG {_version()}   python={platform.python_version()}  "
          f"system={platform.system()}  frozen={getattr(sys, 'frozen', False)}")
    ok = True
    for mod in ("numpy", "cv2", "PIL", "imeg.core.image", "imeg.core.alpha",
                "imeg.core.adb", "imeg.core.dm", "imeg.core.ocr", "imeg.core.inputctl",
                "imeg.core.capture.adb_source", "imeg.core.capture.window_source",
                "imeg.core.capture.scrcpy_source", "imeg.core.capture.win32",
                "imeg.ui.main_window", "imeg.ui.widgets", "imeg.ui.panels.color_panel",
                "imeg.ui.panels.findpic_panel", "imeg.ui.panels.transparent_panel",
                "imeg.core.palette", "imeg.resources"):
        try:
            importlib.import_module(mod)
            print(f"  OK   {mod}")
        except Exception as exc:
            ok = False
            print(f"  FAIL {mod}: {exc}")
    try:
        from PySide6.QtWidgets import QApplication
        QApplication([])          # 只是验证 Qt 能起来
        from .main_window import MainWindow
        win = MainWindow()
        print(f"  OK   Qt 界面可构造（{win.windowTitle()}）")
    except Exception as exc:
        ok = False
        print(f"  FAIL Qt 界面: {exc}")
    for extra in ("rapidocr_onnxruntime", "av"):
        try:
            importlib.import_module(extra)
            print(f"  OK   可选依赖 {extra}")
        except Exception:
            print(f"  --   可选依赖 {extra} 未打包（不影响主功能）")
    print("自检" + ("通过" if ok else "失败"))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()
    if "--version" in argv:
        print(_version())
        return 0

    from PySide6.QtWidgets import QApplication

    # Windows 上开启 DPI 感知，否则高分屏截图会被缩水
    try:
        from ..core.capture import win32
        win32.set_dpi_awareness()
    except Exception:
        pass

    _install_excepthook()
    app = QApplication(argv)
    app.setApplicationName("IMEG")
    app.setOrganizationName("IMEG")
    app.setStyle("Fusion")

    qss_path = Path(__file__).with_name("style.qss")
    if qss_path.is_file():
        app.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    from .main_window import MainWindow

    try:
        from ..resources import icon_path
        from PySide6.QtGui import QIcon
        ico = icon_path()
        if ico:
            app.setWindowIcon(QIcon(str(ico)))
    except Exception:
        pass

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
