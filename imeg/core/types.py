"""基础数据结构：区域、点、匹配结果。"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class Point:
    x: int = 0
    y: int = 0

    def __iter__(self):
        return iter((self.x, self.y))

    def __str__(self) -> str:
        return f"{self.x},{self.y}"


@dataclass(frozen=True)
class Rect:
    """闭区间矩形，与大漠一致：``(x1, y1, x2, y2)`` 四个坐标都包含在内。"""

    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0

    @classmethod
    def from_xywh(cls, x: int, y: int, w: int, h: int) -> "Rect":
        return cls(int(x), int(y), int(x) + int(w) - 1, int(y) + int(h) - 1)

    @classmethod
    def from_size(cls, w: int, h: int) -> "Rect":
        return cls(0, 0, int(w) - 1, int(h) - 1)

    @property
    def w(self) -> int:
        return self.x2 - self.x1 + 1

    @property
    def h(self) -> int:
        return self.y2 - self.y1 + 1

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def is_valid(self) -> bool:
        return self.w > 0 and self.h > 0

    def slice(self) -> tuple[slice, slice]:
        """用于 numpy 切片 ``img[rect.slice()]``（注意先 y 后 x）。"""
        return slice(self.y1, self.y2 + 1), slice(self.x1, self.x2 + 1)

    def clamp(self, w: int, h: int) -> "Rect":
        return Rect(
            max(0, min(self.x1, w - 1)),
            max(0, min(self.y1, h - 1)),
            max(0, min(self.x2, w - 1)),
            max(0, min(self.y2, h - 1)),
        )

    def __str__(self) -> str:
        return f"{self.x1},{self.y1},{self.x2},{self.y2}"


@dataclass
class Match:
    """一次图色匹配的结果。"""

    x: int
    y: int
    w: int = 0
    h: int = 0
    score: float = 1.0
    index: int = -1
    name: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def rect(self) -> Rect:
        return Rect.from_xywh(self.x, self.y, self.w, self.h)

    @property
    def center(self) -> Point:
        return Point(self.x + self.w // 2, self.y + self.h // 2)

    def __str__(self) -> str:
        return f"{self.name or self.index}|{self.x}|{self.y}"


@dataclass
class Frame:
    """一帧截图。"""

    image: np.ndarray  # BGR, uint8
    width: int = 0
    height: int = 0
    seq: int = 0
    timestamp: float = 0.0
    source: str = ""
    meta: dict = field(default_factory=dict)

    @classmethod
    def from_image(cls, image: np.ndarray, **kw) -> "Frame":
        h, w = image.shape[:2]
        return cls(image=image, width=w, height=h, **kw)
