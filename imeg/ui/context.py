"""面板与主窗口之间的共享上下文。"""
from __future__ import annotations

from typing import Callable

from ..core.dm import Dm
from ..core.types import Rect

__all__ = ["UiContext"]


class UiContext:
    """把主窗口的能力打包给各个面板用。"""

    def __init__(self, dm: Dm, canvas, log: Callable[[str, str], None],
                 status: Callable[[str], None]) -> None:
        self.dm = dm
        self.canvas = canvas
        self.log = log
        self.status = status
        self.hover: tuple[int, int, tuple[int, int, int]] = (0, 0, (0, 0, 0))

    # ---------------------------------------------------------------- 画面
    def frame(self):
        try:
            return self.dm._frame()
        except Exception:
            return None

    def selection(self) -> Rect | None:
        rect = self.canvas.selection()
        if rect is None:
            return None
        return Rect(rect.x(), rect.y(), rect.x() + rect.width() - 1, rect.y() + rect.height() - 1)

    def selection_image(self):
        img = self.frame()
        rect = self.selection()
        if img is None or rect is None:
            return None
        rect = rect.clamp(img.shape[1], img.shape[0])
        return img[rect.slice()].copy() if rect.is_valid() else None

    def msg(self, text: str, level: str = "info") -> None:
        self.log(str(text), level)

    # ---------------------------------------------------------------- 鼠标
    def last_pos(self) -> tuple[int, int]:
        return self.hover[0], self.hover[1]

    def last_color_hex(self) -> str:
        from ..core.color import rgb_to_hex
        return rgb_to_hex(self.hover[2])

    def color_at(self, x: int, y: int) -> str:
        from ..core.color import rgb_to_hex
        img = self.frame()
        if img is None:
            return "000000"
        h, w = img.shape[:2]
        x, y = max(0, min(int(x), w - 1)), max(0, min(int(y), h - 1))
        b, g, r = (int(v) for v in img[y, x, :3])
        return rgb_to_hex((r, g, b))
