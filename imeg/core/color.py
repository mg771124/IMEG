"""颜色与"偏色"解析，兼容大漠插件的颜色字符串格式。

大漠的颜色串格式（这里完整支持）::

    RRGGBB                  单色，无偏色
    RRGGBB-DELTA            带偏色。DELTA 为 2 位(三通道通用)或 6 位(逐通道)十六进制
    RRGGBB-DELTA|RRGGBB-DE.. 多色，任一命中即算命中（FindColorEx / 多点找色用）

例::

    "FFFFFF"            # 纯白
    "FFFFFF-10"         # 白，三通道各允许 ±0x10
    "FFFFFF-101010"     # 同上
    "FFFFFF-0F1E0A"     # 白，R±0x0F G±0x1E B±0x0A
    "FFFFFF-000000|000000-101010"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

_HEX_RE = re.compile(r"^[0-9A-Fa-f]+$")


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    """``"FF8800"`` / ``"#f80"`` -> ``(255, 136, 0)``（顺序为 RGB）。"""
    s = str(text).strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6 or not _HEX_RE.match(s):
        raise ValueError(f"非法颜色 {text!r}，应为 6 位十六进制 RRGGBB")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def rgb_to_hex(rgb) -> str:
    """``(255,136,0)`` -> ``"FF8800"``。"""
    r, g, b = (int(v) & 0xFF for v in rgb)
    return f"{r:02X}{g:02X}{b:02X}"


def _parse_delta(text: str) -> tuple[int, int, int]:
    s = str(text).strip().lstrip("-")
    if not s:
        return (0, 0, 0)
    if len(s) == 2:
        v = int(s, 16)
        return (v, v, v)
    if len(s) == 6 and _HEX_RE.match(s):
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    raise ValueError(f"非法偏色 {text!r}，应为 2 位或 6 位十六进制，如 10 / 101010")


@dataclass(frozen=True)
class ColorSpec:
    """一个颜色 + 偏色。"""

    rgb: tuple[int, int, int]
    tol: tuple[int, int, int] = (0, 0, 0)

    def __post_init__(self) -> None:
        object.__setattr__(self, "rgb", tuple(int(v) & 0xFF for v in self.rgb))
        object.__setattr__(self, "tol", tuple(max(0, min(255, int(v))) for v in self.tol))

    # ---- 便利属性 ----
    @property
    def lower(self) -> np.ndarray:
        return np.array([max(0, c - d) for c, d in zip(self.rgb, self.tol)], np.int16)

    @property
    def upper(self) -> np.ndarray:
        return np.array([min(255, c + d) for c, d in zip(self.rgb, self.tol)], np.int16)

    def to_str(self) -> str:
        tol = "".join(f"{d:02X}" for d in self.tol)
        return f"{rgb_to_hex(self.rgb)}-{tol}"

    def __str__(self) -> str:  # pragma: no cover - 调试用
        return self.to_str()

    def match(self, rgb_arr: np.ndarray) -> np.ndarray:
        """对 ``(..., 3)`` 的 RGB 数组逐像素判断是否命中，返回布尔数组。"""
        arr = np.asarray(rgb_arr, dtype=np.int16)
        lo, hi = self.lower, self.upper
        return (
            (arr[..., 0] >= lo[0]) & (arr[..., 0] <= hi[0])
            & (arr[..., 1] >= lo[1]) & (arr[..., 1] <= hi[1])
            & (arr[..., 2] >= lo[2]) & (arr[..., 2] <= hi[2])
        )


def parse_color(text) -> ColorSpec:
    """解析单个颜色串；也接受 :class:`ColorSpec` 直接传入。"""
    if isinstance(text, ColorSpec):
        return text
    s = str(text).strip()
    if not s:
        raise ValueError("颜色串不能为空")
    parts = s.split("-")
    if len(parts) == 1:
        return ColorSpec(hex_to_rgb(parts[0]), (0, 0, 0))
    if len(parts) == 2:
        return ColorSpec(hex_to_rgb(parts[0]), _parse_delta(parts[1]))
    raise ValueError(f"非法颜色串 {text!r}，格式应为 RRGGBB-DELTA")


def parse_colors(text) -> list[ColorSpec]:
    """解析 ``|`` 分隔的多色串（FindColorEx / 多点找色）。"""
    if isinstance(text, (list, tuple)):
        return [parse_color(c) for c in text]
    s = str(text).strip()
    if not s:
        raise ValueError("颜色串不能为空")
    return [parse_color(part) for part in s.split("|") if part.strip()]


def parse_delta_color(text, default: int = 16) -> tuple[int, int, int]:
    """FindPic 的 ``delta_color``：十六进制串或整数 -> 逐通道容差。"""
    if text is None:
        d = int(default)
        return (d, d, d)
    if isinstance(text, int):
        d = max(0, min(255, int(text)))
        return (d, d, d)
    s = str(text).strip()
    if not s:
        d = int(default)
        return (d, d, d)
    return _parse_delta(s)


def match_any(rgb_arr: np.ndarray, specs: list[ColorSpec]) -> np.ndarray:
    """任一颜色命中即为真。"""
    out = np.zeros(np.asarray(rgb_arr).shape[:-1], dtype=bool)
    for spec in specs:
        out |= spec.match(rgb_arr)
    return out
