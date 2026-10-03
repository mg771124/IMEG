"""后台键鼠控制：ADB 注入 或 Windows 后台消息（不抢焦点、不动真鼠标）。"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from .adb import AdbClient

__all__ = ["InputController", "AdbInputController", "WindowInputController",
           "NullInputController", "create_input"]


class InputController(ABC):
    """输入控制接口。坐标一律使用**设备/截图坐标**。"""

    name = "base"

    def __init__(self) -> None:
        self.last_error = ""

    # ------------------------------------------------------------ 鼠标
    @abstractmethod
    def click(self, x: int, y: int, button: str = "left") -> None:
        ...

    def double_click(self, x: int, y: int) -> None:
        self.click(x, y)
        time.sleep(0.05)
        self.click(x, y)

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        self.swipe(x, y, x, y, duration_ms)

    @abstractmethod
    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        ...

    def move_to(self, x: int, y: int) -> None:
        """移动"光标"（ADB 下无实际意义，仅接口兼容）。"""

    def mouse_down(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError(f"{self.name} 不支持按下不抬起")

    def mouse_up(self, x: int, y: int, button: str = "left") -> None:
        raise NotImplementedError(f"{self.name} 不支持抬起")

    def wheel(self, x: int, y: int, delta: int = -3) -> None:
        """滚轮；ADB 下退化成一次纵向滑动。"""
        self.swipe(x, y, x, y - 200 * (1 if delta < 0 else -1), 200)

    # ------------------------------------------------------------ 键盘
    @abstractmethod
    def key(self, key) -> None:
        ...

    @abstractmethod
    def text(self, text: str) -> None:
        ...


# --------------------------------------------------------------------------
@dataclass
class AdbInputController(InputController):
    """走 ``adb shell input``，天然后台、不需要窗口焦点。"""

    serial: str | None = None
    adb: AdbClient | None = None

    name = "adb"

    def __post_init__(self) -> None:
        super().__init__()
        self.adb = self.adb or AdbClient()

    def click(self, x: int, y: int, button: str = "left") -> None:
        if button != "left":
            raise NotImplementedError("ADB 只支持左键点击（右键请用 key(BACK)）")
        self.adb.tap(int(x), int(y), serial=self.serial)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.adb.swipe(x1, y1, x2, y2, duration_ms, serial=self.serial)

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        self.adb.long_press(int(x), int(y), duration_ms, serial=self.serial)

    def key(self, key) -> None:
        self.adb.keyevent(key, serial=self.serial)

    def text(self, text: str) -> None:
        self.adb.text(text, serial=self.serial)


# --------------------------------------------------------------------------
class WindowInputController(InputController):
    """Windows 后台消息键鼠（PostMessage），并把设备坐标映射到窗口坐标。"""

    name = "window"

    def __init__(self, hwnd: int, src_size: tuple[int, int] | None = None,
                 dst_size: tuple[int, int] | None = None,
                 offset: tuple[int, int] = (0, 0), real_mouse: bool = False) -> None:
        super().__init__()
        self.hwnd = int(hwnd)
        self.src_size = src_size                 # 设备/截图分辨率
        self.dst_size = dst_size                 # 窗口客户区尺寸
        self.offset = tuple(int(v) for v in offset)
        self.real_mouse = real_mouse

    def set_mapping(self, src_size: tuple[int, int] | None, dst_size: tuple[int, int] | None,
                    offset: tuple[int, int] = (0, 0)) -> None:
        self.src_size, self.dst_size, self.offset = src_size, dst_size, offset

    def to_window(self, x: int, y: int) -> tuple[int, int]:
        wx, wy = float(x), float(y)
        if self.src_size and self.dst_size and self.src_size[0] and self.src_size[1]:
            wx = wx * self.dst_size[0] / self.src_size[0]
            wy = wy * self.dst_size[1] / self.src_size[1]
        return int(round(wx)) + self.offset[0], int(round(wy)) + self.offset[1]

    def _require(self):
        from .capture import win32
        win32._require_windows()
        return win32

    def move_to(self, x: int, y: int) -> None:
        win32 = self._require()
        win32.mouse_move(self.hwnd, *self.to_window(x, y))

    def click(self, x: int, y: int, button: str = "left") -> None:
        win32 = self._require()
        win32.click(self.hwnd, *self.to_window(x, y), button=button)

    def double_click(self, x: int, y: int) -> None:
        win32 = self._require()
        win32.double_click(self.hwnd, *self.to_window(x, y))

    def mouse_down(self, x: int, y: int, button: str = "left") -> None:
        from .capture import win32
        win32.mouse_down(self.hwnd, *self.to_window(x, y), button=button)

    def mouse_up(self, x: int, y: int, button: str = "left") -> None:
        from .capture import win32
        win32.mouse_up(self.hwnd, *self.to_window(x, y), button=button)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        """后台拖动：按下 → 若干次移动 → 抬起。"""
        steps = max(2, int(duration_ms / 30))
        self.mouse_down(x1, y1)
        for i in range(1, steps + 1):
            t = i / steps
            self.move_to(int(x1 + (x2 - x1) * t), int(y1 + (y2 - y1) * t))
            time.sleep(duration_ms / 1000.0 / steps)
        self.mouse_up(x2, y2)

    def wheel(self, x: int, y: int, delta: int = -3) -> None:
        from .capture import win32
        win32.mouse_wheel(self.hwnd, *self.to_window(x, y), delta=int(delta) * 120)

    def key(self, key) -> None:
        from .capture import win32
        win32.key_press(self.hwnd, key)

    def key_down(self, key) -> None:
        from .capture import win32
        win32.key_down(self.hwnd, key)

    def key_up(self, key) -> None:
        from .capture import win32
        win32.key_up(self.hwnd, key)

    def text(self, text: str) -> None:
        from .capture import win32
        win32.send_text(self.hwnd, str(text))


# --------------------------------------------------------------------------
class NullInputController(InputController):
    """没绑定任何东西时的空实现（只打日志，方便离线调试脚本）。"""

    name = "null"
    log: list[str] = []

    def __init__(self) -> None:
        super().__init__()
        self.log = []

    def _note(self, msg: str) -> None:
        self.log.append(msg)
        if len(self.log) > 500:
            self.log.pop(0)

    def click(self, x: int, y: int, button: str = "left") -> None:
        self._note(f"click {x},{y} ({button})")

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self._note(f"swipe {x1},{y1} -> {x2},{y2} ({duration_ms}ms)")

    def key(self, key) -> None:
        self._note(f"key {key}")

    def text(self, text: str) -> None:
        self._note(f"text {text!r}")


def create_input(kind: str, **kw) -> InputController:
    kind = (kind or "null").lower()
    if kind == "adb":
        return AdbInputController(serial=kw.get("serial"), adb=kw.get("adb"))
    if kind == "window":
        return WindowInputController(hwnd=kw["hwnd"], src_size=kw.get("src_size"),
                                     dst_size=kw.get("dst_size"), offset=kw.get("offset", (0, 0)))
    return NullInputController()
