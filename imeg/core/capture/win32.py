"""Windows 原生 API 封装（纯 ctypes，不需要 pywin32）。

提供两块能力:

* **后台截图**：``PrintWindow(PW_RENDERFULLCONTENT)`` —— 窗口被遮挡、最小化、
  不在前台也能拿到画面（这正是大漠 ``BindWindow(dx/gdi)`` 干的事）
* **后台键鼠**：``PostMessage`` 发 WM_* 消息，不抢焦点、不移动真鼠标

非 Windows 平台导入本模块不会报错，但调用函数会抛 :class:`RuntimeError`。
"""
from __future__ import annotations

import ctypes
import os
import time
from dataclasses import dataclass

import numpy as np

WINDOWS = os.name == "nt"
__all__ = [
    "WINDOWS", "WindowInfo", "set_dpi_awareness", "enum_windows", "find_windows",
    "enum_child_windows", "window_rect", "client_rect", "client_screen_rect",
    "capture", "is_supported", "EMULATOR_HINTS",
    # 输入
    "post_mouse", "click", "double_click", "mouse_move", "mouse_wheel",
    "key_down", "key_up", "key_press", "send_char", "send_text",
    "set_foreground", "get_foreground",
]

if WINDOWS:  # pragma: no cover - 只在 Windows 上执行
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
    except OSError:
        shcore = None
else:  # pragma: no cover
    user32 = gdi32 = kernel32 = shcore = None


def is_supported() -> bool:
    return WINDOWS


def _require_windows() -> None:
    if not WINDOWS:
        raise RuntimeError("窗口捕获/后台键鼠是 Windows 专属功能（当前系统: %s）" % os.name)


# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
SW_RESTORE = 9

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_CHAR = 0x0102
WM_SETTEXT = 0x000C
WM_CLOSE = 0x0010
MK_LBUTTON, MK_RBUTTON, MK_MBUTTON = 0x0001, 0x0002, 0x0010

#: 常见模拟器的窗口特征（窗口类名 / 标题关键字），用于自动识别
EMULATOR_HINTS: dict[str, dict] = {
    "LDPlayer": {"class": ["LDPlayerMainFrame", "LDPlayer"], "title": ["雷电模拟器", "LDPlayer"]},
    "MuMu": {"class": ["Qt5QWindowIcon", "Qt5152QWindowIcon", "MainWindowWindowClass"],
             "title": ["MuMu", "MuMu模拟器", "mumu"]},
    "Nox": {"class": ["Qt5QWindowToolSaveBits", "Qt5152QWindowToolSaveBits"],
            "title": ["Nox", "夜神模拟器", "nox"]},
    "BlueStacks": {"class": ["HwndWrapper[Bluestacks.exe;;", "BlueStacks"],
                   "title": ["BlueStacks", "蓝叠"]},
    "MEmu": {"class": ["Qt5QWindowIcon"], "title": ["MEmu", "逍遥安卓"]},
    "WSA": {"class": ["ApplicationFrameWindow"], "title": ["Windows Subsystem for Android"]},
}

#: 模拟器渲染子窗口的类名（找到它就能拿到"纯画面"，自动去掉边框/工具栏）
RENDER_CLASS_HINTS = (
    "RenderWindow", "render", "subWin", "SubWin", "Qt5QWindowIcon",
    "Qt5QWindowToolSaveBits", "QWidgetClassWindow", "WindowsForms10.Window",
)


@dataclass
class WindowInfo:
    hwnd: int
    title: str = ""
    class_name: str = ""
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    pid: int = 0

    @property
    def w(self) -> int:
        return self.right - self.left

    @property
    def h(self) -> int:
        return self.bottom - self.top

    def __str__(self) -> str:
        return f"{self.title or '(无标题)'} [{self.class_name}] {self.w}x{self.h} hwnd=0x{self.hwnd:X}"


def set_dpi_awareness() -> None:
    """开启 Per-Monitor DPI 感知 —— 不开启的话在高分屏上截图会只有 1/2 或 1/1.5 分辨率。"""
    _require_windows()
    try:
        if shcore is not None:
            shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------------
# 窗口枚举
# --------------------------------------------------------------------------
def _setup_win_funcs() -> None:
    if not WINDOWS:
        return
    user32.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.EnumWindows.restype = ctypes.c_bool
    user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.PrintWindow.restype = ctypes.c_bool


_setup_win_funcs()

if WINDOWS:  # pragma: no cover
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
else:  # pragma: no cover
    WNDENUMPROC = None


def _window_info(hwnd: int) -> WindowInfo:
    buf_t = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf_t, 512)
    buf_c = ctypes.create_unicode_buffer(512)
    user32.GetClassNameW(hwnd, buf_c, 512)
    left, top, right, bottom = window_rect(hwnd)
    pid = ctypes.c_ulong(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return WindowInfo(int(hwnd), buf_t.value, buf_c.value, left, top, right, bottom, int(pid.value))


def enum_windows(visible_only: bool = True) -> list[WindowInfo]:
    """列出所有顶层窗口。"""
    _require_windows()
    result: list[WindowInfo] = []

    @WNDENUMPROC
    def _cb(hwnd, lparam):  # noqa: ANN001
        if visible_only and not user32.IsWindowVisible(hwnd):
            return True
        try:
            info = _window_info(hwnd)
        except Exception:
            return True
        if info.w > 0 and info.h > 0:
            result.append(info)
        return True

    user32.EnumWindows(_cb, 0)
    return result


def enum_child_windows(hwnd: int) -> list[WindowInfo]:
    _require_windows()
    result: list[WindowInfo] = []

    @WNDENUMPROC
    def _cb(child, lparam):  # noqa: ANN001
        try:
            result.append(_window_info(child))
        except Exception:
            pass
        return True

    user32.EnumChildWindows(ctypes.c_void_p(int(hwnd)), _cb, 0)
    return result


def find_windows(title: str = "", class_name: str = "", visible_only: bool = True) -> list[WindowInfo]:
    """按标题/类名关键字过滤窗口（大小写不敏感）。"""
    out = []
    for w in enum_windows(visible_only):
        if title and title.lower() not in w.title.lower():
            continue
        if class_name and class_name.lower() not in w.class_name.lower():
            continue
        out.append(w)
    return out


def find_emulator_windows() -> list[WindowInfo]:
    """自动识别常见模拟器窗口。"""
    out: list[WindowInfo] = []
    seen: set[int] = set()
    for name, hint in EMULATOR_HINTS.items():
        for key in ("class", "title"):
            for pattern in hint[key]:
                for w in find_windows(**{("class_name" if key == "class" else "title"): pattern}):
                    if w.hwnd not in seen:
                        seen.add(w.hwnd)
                        w.title = f"{w.title}  ⟵ {name}"
                        out.append(w)
    return out


def detect_render_window(hwnd: int) -> WindowInfo | None:
    """在模拟器窗口里找真正的"画面"子窗口（边框/工具栏不算）。

    找不到返回 ``None``，此时调用方一般退化为整个客户区。
    """
    _require_windows()
    best: WindowInfo | None = None
    for child in enum_child_windows(hwnd):
        if child.w < 32 or child.h < 32:
            continue
        if any(h.lower() in child.class_name.lower() for h in RENDER_CLASS_HINTS):
            if best is None or child.w * child.h > best.w * best.h:
                best = child
    return best


# --------------------------------------------------------------------------
# 矩形
# --------------------------------------------------------------------------
def window_rect(hwnd: int) -> tuple[int, int, int, int]:
    _require_windows()
    r = ctypes.c_int * 4
    rect = r()
    user32.GetWindowRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(rect))
    return rect[0], rect[1], rect[2], rect[3]


def client_rect(hwnd: int) -> tuple[int, int]:
    _require_windows()
    r = ctypes.c_int * 4
    rect = r()
    user32.GetClientRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(rect))
    return rect[2], rect[3]


def client_screen_rect(hwnd: int) -> tuple[int, int, int, int]:
    """客户区在屏幕上的位置。"""
    _require_windows()
    pt = (ctypes.c_int * 2)(0, 0)
    user32.ClientToScreen(ctypes.c_void_p(int(hwnd)), ctypes.byref(pt))
    w, h = client_rect(hwnd)
    return pt[0], pt[1], pt[0] + w, pt[1] + h


# --------------------------------------------------------------------------
# 后台截图
# --------------------------------------------------------------------------
if WINDOWS:  # pragma: no cover

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32), ("biHeight", ctypes.c_int32),
            ("biPlanes", ctypes.c_uint16), ("biBitCount", ctypes.c_uint16),
            ("biCompression", ctypes.c_uint32), ("biSizeImage", ctypes.c_uint32),
            ("biXPelsPerMeter", ctypes.c_int32), ("biYPelsPerMeter", ctypes.c_int32),
            ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
                                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.BitBlt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    gdi32.BitBlt.restype = ctypes.c_bool


def capture(hwnd: int, client_only: bool = True, restore_if_minimized: bool = False,
            crop: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """后台截取窗口画面，返回 BGR 图。

    :param client_only: 只截客户区（去掉标题栏/边框）
    :param restore_if_minimized: 最小化时先还原再截（个别模拟器最小化不出图）
    :param crop: 可选的 ``(x, y, w, h)``，在窗口坐标下再裁一刀
    """
    _require_windows()
    set_dpi_awareness()
    hwnd_v = ctypes.c_void_p(int(hwnd))
    if restore_if_minimized and user32.IsIconic(hwnd_v):
        user32.ShowWindow(hwnd_v, SW_RESTORE)
        time.sleep(0.25)

    if client_only:
        left, top, right, bottom = client_screen_rect(hwnd)
    else:
        left, top, right, bottom = window_rect(hwnd)
    w, h = max(1, right - left), max(1, bottom - top)

    hwnd_dc = user32.GetWindowDC(hwnd_v) if not client_only else user32.GetDC(hwnd_v)
    screen_dc = user32.GetDC(0)
    if not hwnd_dc or not screen_dc:
        raise RuntimeError("获取窗口 DC 失败（窗口可能已关闭）")
    mem_dc, bitmap, old = None, None, None
    try:
        mem_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
        old = gdi32.SelectObject(mem_dc, bitmap)

        flags = PW_RENDERFULLCONTENT | (PW_CLIENTONLY if client_only else 0)
        ok = user32.PrintWindow(hwnd_v, mem_dc, flags)
        if not ok:  # 老系统不支持 PW_RENDERFULLCONTENT，退回 BitBlt
            ok = gdi32.BitBlt(mem_dc, 0, 0, w, h, hwnd_dc, 0, 0, SRCCOPY)
        if not ok:
            raise RuntimeError("PrintWindow / BitBlt 均失败，无法后台截图")

        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h          # 负号 = 自上而下，省一次翻转
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        bi.bmiHeader.biCompression = BI_RGB
        buf = (ctypes.c_char * (w * h * 4))()
        got = gdi32.GetDIBits(mem_dc, bitmap, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)
        if not got:
            raise RuntimeError("GetDIBits 读取位图失败")
        arr = np.frombuffer(buf, np.uint8).reshape(h, w, 4)
        img = np.ascontiguousarray(arr[:, :, :3])  # BGRA -> BGR
    finally:
        if old and mem_dc:
            gdi32.SelectObject(mem_dc, old)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if mem_dc:
            gdi32.DeleteDC(mem_dc)
        user32.ReleaseDC(hwnd_v, hwnd_dc)
        user32.ReleaseDC(0, screen_dc)

    if crop:
        x, y, cw, ch = (int(v) for v in crop)
        x, y = max(0, min(x, img.shape[1] - 1)), max(0, min(y, img.shape[0] - 1))
        img = img[y:min(img.shape[0], y + ch), x:min(img.shape[1], x + cw)]
    return img


# --------------------------------------------------------------------------
# 后台键鼠（PostMessage，不抢焦点）
# --------------------------------------------------------------------------
def _mk_lparam(x: int, y: int) -> int:
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def post_mouse(hwnd: int, msg: int, x: int, y: int, wparam: int = 0) -> None:
    _require_windows()
    user32.PostMessageW(ctypes.c_void_p(int(hwnd)), int(msg),
                        ctypes.c_void_p(int(wparam)), ctypes.c_void_p(_mk_lparam(x, y)))


def mouse_move(hwnd: int, x: int, y: int) -> None:
    post_mouse(hwnd, WM_MOUSEMOVE, x, y)


def click(hwnd: int, x: int, y: int, button: str = "left", delay: float = 0.03) -> None:
    down, up, mk = {
        "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
        "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
        "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
    }[button]
    mouse_move(hwnd, x, y)
    post_mouse(hwnd, down, x, y, mk)
    time.sleep(delay)
    post_mouse(hwnd, up, x, y, 0)


def double_click(hwnd: int, x: int, y: int, delay: float = 0.03) -> None:
    click(hwnd, x, y, "left", delay)
    time.sleep(0.02)
    click(hwnd, x, y, "left", delay)


def mouse_down(hwnd: int, x: int, y: int, button: str = "left") -> None:
    down, _, mk = {
        "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
        "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
        "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
    }[button]
    mouse_move(hwnd, x, y)
    post_mouse(hwnd, down, x, y, mk)


def mouse_up(hwnd: int, x: int, y: int, button: str = "left") -> None:
    _, up, _ = {
        "left": (WM_LBUTTONDOWN, WM_LBUTTONUP, MK_LBUTTON),
        "right": (WM_RBUTTONDOWN, WM_RBUTTONUP, MK_RBUTTON),
        "middle": (WM_MBUTTONDOWN, WM_MBUTTONUP, MK_MBUTTON),
    }[button]
    post_mouse(hwnd, up, x, y, 0)


def mouse_wheel(hwnd: int, x: int, y: int, delta: int = -120) -> None:
    _require_windows()
    wparam = (int(delta) & 0xFFFF) << 16
    user32.PostMessageW(ctypes.c_void_p(int(hwnd)), WM_MOUSEWHEEL,
                        ctypes.c_void_p(wparam), ctypes.c_void_p(_mk_lparam(x, y)))


def _vk(ch: str) -> int:
    """字符 -> 虚拟键码。"""
    _require_windows()
    if len(ch) == 1:
        res = user32.VkKeyScanW(ctypes.c_wchar(ch))
        if res != -1:
            return res & 0xFF
    return ord(ch.upper())


def _key_lparam(vk: int, up: bool = False) -> int:
    _require_windows()
    scan = user32.MapVirtualKeyW(int(vk), 0)
    flags = 0
    if up:
        flags |= 0xC0000000  # KEYUP + PREVKEYSTATE
    return 1 | (scan << 16) | flags


def key_down(hwnd: int, key) -> None:
    _require_windows()
    vk = int(key) if isinstance(key, int) else _vk(str(key))
    user32.PostMessageW(ctypes.c_void_p(int(hwnd)), WM_KEYDOWN,
                        ctypes.c_void_p(vk), ctypes.c_void_p(_key_lparam(vk)))


def key_up(hwnd: int, key) -> None:
    _require_windows()
    vk = int(key) if isinstance(key, int) else _vk(str(key))
    user32.PostMessageW(ctypes.c_void_p(int(hwnd)), WM_KEYUP,
                        ctypes.c_void_p(vk), ctypes.c_void_p(_key_lparam(vk, up=True)))


def key_press(hwnd: int, key, delay: float = 0.03) -> None:
    key_down(hwnd, key)
    time.sleep(delay)
    key_up(hwnd, key)


def send_char(hwnd: int, ch: str) -> None:
    """发一个 WM_CHAR，支持中文（UTF-16 码元）。"""
    _require_windows()
    for unit in ch.encode("utf-16-le").decode("utf-16-le"):
        user32.PostMessageW(ctypes.c_void_p(int(hwnd)), WM_CHAR,
                            ctypes.c_void_p(ord(unit)), ctypes.c_void_p(1))


def send_text(hwnd: int, text: str, delay: float = 0.01) -> None:
    for ch in str(text):
        send_char(hwnd, ch)
        time.sleep(delay)


def set_foreground(hwnd: int) -> None:
    _require_windows()
    user32.SetForegroundWindow(ctypes.c_void_p(int(hwnd)))


def get_foreground() -> int:
    _require_windows()
    return int(user32.GetForegroundWindow() or 0)
