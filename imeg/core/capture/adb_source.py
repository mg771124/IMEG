"""ADB 截图源：连设备/模拟器，后台抓设备真实解析度的画面。"""
from __future__ import annotations

import numpy as np

from ..adb import AdbClient
from ..types import Frame
from .base import CaptureSource

__all__ = ["ADBCaptureSource"]


class ADBCaptureSource(CaptureSource):
    """通过 ``adb exec-out screencap`` 抓图。

    特点：
      * **后台截图** —— 不要求窗口在前台、不要求设备亮屏之外的任何条件
      * 拿到的是**设备真实解析度**（如 1080x2400），不受模拟器窗口缩放影响
      * ``raw=True`` 时走 ``screencap`` 原始 RGBA，比 PNG 快 2~5 倍
    """

    name = "adb"

    def __init__(self, serial: str | None = None, adb: AdbClient | None = None,
                 fps: float = 10.0, display: int | None = None,
                 raw: bool = False, auto_rotate: bool = False,
                 max_width: int = 0) -> None:
        super().__init__(fps=fps)
        self.adb = adb or AdbClient()
        self.serial = serial or self._auto_serial()
        self.display = display
        self.raw = raw
        self.auto_rotate = auto_rotate
        self.max_width = int(max_width)
        self.info: dict = {}

    def _auto_serial(self) -> str | None:
        try:
            devs = [d for d in self.adb.devices() if d.is_online]
        except Exception:
            return None
        return devs[0].serial if devs else None

    # ---------------------------------------------------------------- 生命周期
    def open(self) -> None:
        if not self.serial:
            raise RuntimeError("没有可用设备：先 adb connect 或选择一台设备")
        self.refresh_resolution()
        # 先抓一帧确认可用
        self._frame = self.grab()

    def refresh_resolution(self) -> dict:
        self.info = self.adb.resolution_info(self.serial)
        return self.info

    def device_size(self) -> tuple[int, int] | None:
        """设备逻辑分辨率（wm size）。"""
        if "wm_size" in self.info and self.info["wm_size"]:
            return self.info["wm_size"]
        try:
            return self.adb.wm_size(self.serial)
        except Exception:
            return None

    # ---------------------------------------------------------------- 抓帧
    def grab(self) -> Frame:
        if self.raw:
            try:
                img = self.adb.screencap_raw(self.serial, display=self.display)
            except Exception:
                img = self.adb.screencap(self.serial, display=self.display)
        else:
            img = self.adb.screencap(self.serial, display=self.display)

        rotation = self.info.get("rotation", 0)
        if self.auto_rotate and rotation:
            img = self._fix_rotation(img, rotation)

        if self.max_width and img.shape[1] > self.max_width:
            scale = self.max_width / img.shape[1]
            import cv2
            img = cv2.resize(img, (self.max_width, int(img.shape[0] * scale)),
                             interpolation=cv2.INTER_AREA)

        meta = {"serial": self.serial, "raw": self.raw, "rotation": rotation}
        return Frame.from_image(img, source=self.name, meta=meta)

    @staticmethod
    def _fix_rotation(img: np.ndarray, rotation: int) -> np.ndarray:
        import cv2
        if rotation == 1:
            return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        if rotation == 2:
            return cv2.rotate(img, cv2.ROTATE_180)
        if rotation == 3:
            return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return img

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ADBCaptureSource serial={self.serial} fps={self.fps_target}>"
