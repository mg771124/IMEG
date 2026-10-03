"""模拟器窗口捕获源：不连 ADB 也能拿到"去掉边框的画面"，并还原设备真实解析度。

关键点：

* 用 ``PrintWindow(PW_RENDERFULLCONTENT)`` **后台截图**，窗口被挡住/不在前台都行
* 自动找到模拟器里的"渲染子窗口"，把标题栏、工具栏、黑边全部裁掉
* 如果你填了"设备真实解析度"（或从已连的 ADB 读到），会把画面缩放回该分辨率，
  这样同一套图色脚本在 ADB 源和窗口源之间可以无缝切换
"""
from __future__ import annotations

from .. import adb as adb_mod
from ..types import Frame
from . import win32
from .base import CaptureSource

__all__ = ["WindowCaptureSource", "list_windows", "WINDOWS_OS"]

WINDOWS_OS = win32.WINDOWS


def list_windows(emulator_only: bool = False):
    """列出窗口（Windows 专属）。非 Windows 返回空列表。"""
    if not win32.WINDOWS:
        return []
    return win32.find_emulator_windows() if emulator_only else win32.enum_windows()


class WindowCaptureSource(CaptureSource):
    """截取某个 Windows 窗口（通常是模拟器）的画面。"""

    name = "window"

    def __init__(self, hwnd: int, fps: float = 15.0,
                 crop: tuple[int, int, int, int] | None = None,
                 target_size: tuple[int, int] | None = None,
                 client_only: bool = True, auto_render_window: bool = True,
                 restore_if_minimized: bool = False,
                 adb: adb_mod.AdbClient | None = None, adb_serial: str | None = None) -> None:
        super().__init__(fps=fps)
        self.hwnd = int(hwnd)
        self.crop = tuple(int(v) for v in crop) if crop else None
        self.target_size = tuple(int(v) for v in target_size) if target_size else None
        self.client_only = client_only
        self.auto_render_window = auto_render_window
        self.restore_if_minimized = restore_if_minimized
        self.adb = adb
        self.adb_serial = adb_serial
        self.render_hwnd: int | None = None

    # ---------------------------------------------------------------- 辅助
    def resolve_render_window(self) -> int:
        """返回真正用来截图的窗口句柄（渲染子窗口优先）。"""
        if self.auto_render_window:
            child = win32.detect_render_window(self.hwnd)
            if child is not None:
                self.render_hwnd = child.hwnd
                return child.hwnd
        self.render_hwnd = None
        return self.hwnd

    def suggest_device_size(self) -> tuple[int, int] | None:
        """猜设备真实解析度：优先用户设定，其次从已连接的 ADB 设备读 wm size。"""
        if self.target_size:
            return self.target_size
        if self.adb and self.adb_serial:
            try:
                return self.adb.wm_size(self.adb_serial)
            except Exception:
                return None
        return None

    def window_size(self) -> tuple[int, int]:
        if not win32.WINDOWS:
            return (0, 0)
        return win32.client_rect(self.hwnd)

    # ---------------------------------------------------------------- 生命周期
    def open(self) -> None:
        if not win32.WINDOWS:
            raise RuntimeError("窗口捕获仅支持 Windows")
        win32.set_dpi_awareness()
        self.resolve_render_window()
        self._frame = self.grab()

    def device_size(self) -> tuple[int, int] | None:
        return self.suggest_device_size()

    def grab(self) -> Frame:
        hwnd = self.render_hwnd or self.resolve_render_window()
        img = win32.capture(hwnd, client_only=self.client_only,
                            restore_if_minimized=self.restore_if_minimized,
                            crop=self.crop)
        scale = 1.0
        target = self.suggest_device_size()
        if target and (img.shape[1], img.shape[0]) != target:
            import cv2
            scale = target[0] / img.shape[1]
            img = cv2.resize(img, target, interpolation=cv2.INTER_AREA)
        return Frame.from_image(img, source=self.name,
                                meta={"hwnd": hwnd, "scale": scale,
                                      "target_size": target, "crop": self.crop})

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WindowCaptureSource hwnd=0x{self.hwnd:X} fps={self.fps_target}>"
