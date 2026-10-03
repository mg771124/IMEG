"""大漠（dm.dll）风格的 API 门面 —— 脚本里写 ``dm.FindPic(...)`` 就能用。

返回值一律沿用大漠的字符串约定，方便把旧脚本搬过来::

    FindPic       -> "index|x|y"          找不到 "-1|-1|-1"
    FindPicEx     -> "index|x|y|index|x|y|..."（全部结果）
    FindColor     -> "x|y"                找不到 "-1|-1"
    FindColorEx   -> "x|y|x|y|..."
    FindMultiColor-> "x|y"                找不到 "-1|-1"
    CmpColor      -> 0 符合 / -1 不符合
    GetColor      -> "RRGGBB"
    Ocr           -> "x|y|文字|x|y|文字2|..."
    FindStr       -> "index|x|y"          找不到 "-1|-1|-1"
    Capture       -> 0/1（1 为成功）

与真正的大漠有两点不同（写在前面，免得踩坑）:

1. 坐标是 **0 基**（大漠也是 0 基，但区域是闭区间，这里保持一致）
2. ``GetScreenData`` 返回 base64 **PNG**（大漠是 BMP），另有 ``GetScreenDataBmp`` 返回 BMP
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 OpenCV") from exc

from .capture import create_source
from .image import (
    find_color, find_multi_color, find_pic, find_pic_multi,
    get_color, get_color_num, load_image, save_image,
)
from .inputctl import NullInputController, create_input
from .ocr import OcrEngine
from .types import Match, Rect

__all__ = ["Dm", "DEFAULT_PIC_DIR"]

DEFAULT_PIC_DIR = Path.home() / ".imeg" / "pic"


class Dm:
    """大漠风格的对象。UI 的脚本控制台里直接就是 ``dm``。"""

    VERSION = "IMEG 0.1.0 (dm-compatible)"

    def __init__(self, source=None, input_ctrl=None, ocr: OcrEngine | None = None,
                 path: str | None = None) -> None:
        self.source = source
        self.input = input_ctrl or NullInputController()
        self.ocr = ocr
        self._path = Path(path) if path else DEFAULT_PIC_DIR
        self._pic_cache: dict[str, tuple[float, np.ndarray]] = {}
        self.last_error = ""
        self._last_file = ""

    # ==================================================================== 路径
    def SetPath(self, path: str) -> int:
        p = Path(path)
        if not p.is_dir():
            try:
                p.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self.last_error = str(exc)
                return 0
        self._path = p
        return 1

    def GetPath(self) -> str:
        return str(self._path)

    def SetDict(self, index: int, file: str) -> int:
        """加载字库文件（这里字库就是一个目录，存放字符模板 PNG）。"""
        if self.ocr is None:
            self.ocr = OcrEngine(backend="fontlib")
        backend = self.ocr.backends["fontlib"]
        backend.lib.dict_dir = Path(file)
        backend.lib.reload()
        self.ocr.set_backend("fontlib")
        return 1

    def UseDict(self, index: int) -> int:
        if self.ocr is None:
            return 0
        try:
            self.ocr.set_backend("fontlib")
            return 1
        except Exception:
            return 0

    # ==================================================================== 绑定
    def BindDevice(self, serial: str | None = None, kind: str = "adb", **kw) -> int:
        """绑定设备/窗口：``kind`` 可为 adb / window / scrcpy / static。"""
        try:
            kw.pop("adb", None)
            self.source = create_source(kind, serial=serial, **kw)
            self.source.start()
            self.source.wait_frame(timeout=8)
            self.input = create_input("adb" if kind in ("adb", "scrcpy") else
                                      ("window" if kind == "window" else "null"),
                                      serial=serial, hwnd=kw.get("hwnd", 0))
            return 1
        except Exception as exc:
            self.last_error = str(exc)
            return 0

    def BindWindow(self, hwnd: int, display: str = "normal", **kw) -> int:  # noqa: ARG002
        try:
            self.source = create_source("window", hwnd=hwnd, **kw)
            self.source.start()
            self.source.wait_frame(timeout=8)
            self.input = create_input("window", hwnd=hwnd)
            return 1
        except Exception as exc:
            self.last_error = str(exc)
            return 0

    def UnBindWindow(self) -> int:
        try:
            if self.source:
                self.source.stop()
            self.source = None
            self.input = NullInputController()
            return 1
        except Exception as exc:
            self.last_error = str(exc)
            return 0

    def IsBind(self) -> int:
        return 1 if (self.source is not None and self.source.running) else 0

    def GetBindInfo(self) -> dict:
        if not self.source:
            return {"bound": False}
        w, h = self.source.size()
        return {"bound": True, "source": self.source.name, "size": (w, h),
                "device_size": self.source.device_size(), "fps": round(self.source.stats.fps, 1),
                "frames": self.source.stats.frames, "errors": self.source.stats.errors,
                "last_error": self.source.stats.last_error}

    # ==================================================================== 截图
    def _frame(self) -> np.ndarray:
        if self.source is None:
            raise RuntimeError("还没有绑定设备：先 BindDevice() / BindWindow()")
        img = self.source.image()
        if img is None:
            img = self.source.wait_frame(timeout=8)
        if img is None:
            raise RuntimeError(f"取不到画面: {self.source.stats.last_error}")
        return img

    def GetClientSize(self) -> tuple[int, int]:
        img = self._frame()
        return img.shape[1], img.shape[0]

    def GetDeviceSize(self) -> tuple[int, int]:
        return self.source.device_size() or self.GetClientSize()

    def GetScreenData(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0) -> str:
        """返回 base64 PNG（大漠同名的返回值是 BMP 的 base64）。"""
        img = self._crop(x1, y1, x2, y2)
        ok, buf = cv2.imencode(".png", img)
        return base64.b64encode(buf.tobytes()).decode() if ok else ""

    def GetScreenDataBmp(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0) -> str:
        img = self._crop(x1, y1, x2, y2)
        ok, buf = cv2.imencode(".bmp", img)
        return base64.b64encode(buf.tobytes()).decode() if ok else ""

    def _crop(self, x1: int, y1: int, x2: int, y2: int) -> np.ndarray:
        img = self._frame()
        w, h = img.shape[1], img.shape[0]
        if x2 <= 0:
            x2 = w - 1
        if y2 <= 0:
            y2 = h - 1
        rect = Rect(int(x1), int(y1), int(x2), int(y2)).clamp(w, h)
        return img[rect.slice()]

    def Capture(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0, file: str = "") -> int:
        """截图保存（后台，不需要窗口在前台）。"""
        try:
            img = self._crop(x1, y1, x2, y2)
            if not file:
                file = str(Path(self._path) / f"capture_{int(time.time() * 1000)}.png")
            target = Path(file)
            if not target.is_absolute():
                target = Path(self._path) / target
            target.parent.mkdir(parents=True, exist_ok=True)
            save_image(str(target), img)
            self._last_file = str(target)
            return 1
        except Exception as exc:
            self.last_error = str(exc)
            return 0

    def SavePic(self, file: str, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0) -> int:
        """把区域存成模板（``Capture`` 的别名，语义更清楚）。"""
        return self.Capture(x1, y1, x2, y2, file)

    # ==================================================================== 模板
    def _resolve(self, name: str) -> Path:
        p = Path(str(name))
        candidates = [p, Path(self._path) / p, Path(self._path) / "pic" / p]
        for base in (Path(self._path), Path(self._path) / "pic"):
            for ext in ("", ".png", ".bmp", ".jpg"):
                c = base / (str(name) + ext)
                if c not in candidates:
                    candidates.append(c)
        for c in candidates:
            if c.is_file():
                return c
        raise FileNotFoundError(f"找不到图片: {name}（搜索目录 {self._path}）")

    def _load_pics(self, pic_name: str) -> list[tuple[str, np.ndarray]]:
        out = []
        for name in str(pic_name).split("|"):
            name = name.strip()
            if not name:
                continue
            path = self._resolve(name)
            mtime = path.stat().st_mtime
            cached = self._pic_cache.get(str(path))
            if cached and cached[0] == mtime:
                img = cached[1]
            else:
                img = load_image(str(path), with_alpha=True)
                self._pic_cache[str(path)] = (mtime, img)
            out.append((name, img))
        return out

    # ==================================================================== 图色
    def _rect(self, x1: int, y1: int, x2: int, y2: int) -> Rect | None:
        if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
            return None
        return Rect(int(x1), int(y1), int(x2), int(y2))

    def FindPic(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0, pic_name: str = "",
                delta_color="101010", sim: float = 0.9, direction: int = 0,
                alpha_threshold: int = 128) -> str:
        """找图，返回 ``"index|x|y"``，找不到 ``"-1|-1|-1"``。"""
        try:
            base = self._frame()
            pics = self._load_pics(pic_name)
            if not pics:
                return "-1|-1|-1"
            if len(pics) == 1:
                res = find_pic(base, pics[0][1], sim=sim, delta=delta_color,
                               direction=direction, max_results=1,
                               region=self._rect(x1, y1, x2, y2),
                               alpha_threshold=alpha_threshold, name=pics[0][0])
                if not res:
                    return "-1|-1|-1"
                return f"0|{res[0].x}|{res[0].y}"
            res = find_pic_multi(base, pics, sim=sim, delta=delta_color, direction=direction,
                                 max_results=1, region=self._rect(x1, y1, x2, y2),
                                 alpha_threshold=alpha_threshold)
            if not res:
                return "-1|-1|-1"
            return f"{res[0].index}|{res[0].x}|{res[0].y}"
        except Exception as exc:
            self.last_error = str(exc)
            return "-1|-1|-1"

    def FindPicEx(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0, pic_name: str = "",
                  delta_color="101010", sim: float = 0.9, direction: int = 0,
                  max_results: int = 100, alpha_threshold: int = 128) -> str:
        """找图（全部结果），返回 ``"index|x|y|index|x|y|..."``。"""
        try:
            base = self._frame()
            pics = self._load_pics(pic_name)
            if not pics:
                return ""
            region = self._rect(x1, y1, x2, y2)
            if len(pics) == 1:
                res = find_pic(base, pics[0][1], sim=sim, delta=delta_color,
                               direction=direction, max_results=max_results,
                               region=region, alpha_threshold=alpha_threshold, name=pics[0][0])
                for i, m in enumerate(res):
                    m.index = i
            else:
                res = find_pic_multi(base, pics, sim=sim, delta=delta_color, direction=direction,
                                     max_results=max_results, region=region,
                                     alpha_threshold=alpha_threshold)
            return "|".join(f"{m.index}|{m.x}|{m.y}" for m in res)
        except Exception as exc:
            self.last_error = str(exc)
            return ""

    def FindColor(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
                  color: str = "FFFFFF-000000", direction: int = 0) -> str:
        """找色，返回 ``"x|y"``，找不到 ``"-1|-1"``。"""
        try:
            base = self._frame()
            pts = find_color(base, color, region=self._rect(x1, y1, x2, y2),
                             direction=direction, max_results=1)
            return f"{pts[0].x}|{pts[0].y}" if pts else "-1|-1"
        except Exception as exc:
            self.last_error = str(exc)
            return "-1|-1"

    def FindColorEx(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
                    color: str = "FFFFFF-000000", direction: int = 0,
                    max_results: int = 100) -> str:
        try:
            base = self._frame()
            pts = find_color(base, color, region=self._rect(x1, y1, x2, y2),
                             direction=direction, max_results=max_results)
            return "|".join(f"{p.x}|{p.y}" for p in pts)
        except Exception as exc:
            self.last_error = str(exc)
            return ""

    def FindMultiColor(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
                       first_color: str = "FFFFFF-000000", offset_color: str = "",
                       sim: float = 1.0, direction: int = 0) -> str:
        """多点找色，返回 ``"x|y"``，找不到 ``"-1|-1"``。"""
        try:
            base = self._frame()
            res = find_multi_color(base, first_color, offset_color, sim=sim,
                                   direction=direction, max_results=1,
                                   region=self._rect(x1, y1, x2, y2))
            return f"{res[0].x}|{res[0].y}" if res else "-1|-1"
        except Exception as exc:
            self.last_error = str(exc)
            return "-1|-1"

    def CmpColor(self, x: int, y: int, color: str = "FFFFFF-000000", sim: float = 1.0) -> int:  # noqa: ARG002
        try:
            base = self._frame()
            from .image import cmp_color
            return 0 if cmp_color(base, x, y, color) else -1
        except Exception as exc:
            self.last_error = str(exc)
            return -1

    def GetColor(self, x: int, y: int) -> str:
        try:
            return get_color(self._frame(), x, y)
        except Exception as exc:
            self.last_error = str(exc)
            return ""

    def GetColorNum(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
                    color: str = "FFFFFF-000000") -> int:
        try:
            return get_color_num(self._frame(), color, region=self._rect(x1, y1, x2, y2))
        except Exception as exc:
            self.last_error = str(exc)
            return 0

    # ==================================================================== 键鼠
    def MoveTo(self, x: int, y: int) -> int:
        return self._safe(lambda: self.input.move_to(int(x), int(y)))

    def MoveR(self, dx: int, dy: int) -> int:
        return self._safe(lambda: self.input.move_to(*self._pos_offset(dx, dy)))

    def _pos_offset(self, dx: int, dy: int) -> tuple[int, int]:
        cx, cy = getattr(self, "_cursor", (0, 0))
        cx, cy = cx + int(dx), cy + int(dy)
        self._cursor = (cx, cy)
        return cx, cy

    def LeftClick(self, x: int | None = None, y: int | None = None) -> int:
        return self._click(x, y, "left")

    def RightClick(self, x: int | None = None, y: int | None = None) -> int:
        return self._click(x, y, "right")

    def MiddleClick(self, x: int | None = None, y: int | None = None) -> int:
        return self._click(x, y, "middle")

    def DoubleClick(self, x: int | None = None, y: int | None = None) -> int:
        return self._safe(lambda: self.input.double_click(*self._xy(x, y)))

    def _xy(self, x, y) -> tuple[int, int]:
        if x is None or y is None:
            return getattr(self, "_cursor", (0, 0))
        self._cursor = (int(x), int(y))
        return self._cursor

    def _click(self, x, y, button: str) -> int:
        return self._safe(lambda: self.input.click(*self._xy(x, y), button=button))

    def LeftDown(self, x: int | None = None, y: int | None = None) -> int:
        return self._safe(lambda: self.input.mouse_down(*self._xy(x, y), button="left"))

    def LeftUp(self, x: int | None = None, y: int | None = None) -> int:
        return self._safe(lambda: self.input.mouse_up(*self._xy(x, y), button="left"))

    def Swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> int:
        return self._safe(lambda: self.input.swipe(x1, y1, x2, y2, duration_ms))

    def WheelDown(self, x: int | None = None, y: int | None = None) -> int:
        return self._safe(lambda: self.input.wheel(*self._xy(x, y), delta=-3))

    def WheelUp(self, x: int | None = None, y: int | None = None) -> int:
        return self._safe(lambda: self.input.wheel(*self._xy(x, y), delta=3))

    def KeyDown(self, key) -> int:
        return self._safe(lambda: self.input.key(key))

    def KeyUp(self, key) -> int:
        return self._safe(lambda: getattr(self.input, "key_up", lambda k: None)(key))

    def KeyPress(self, key) -> int:
        """按键码（数字）。"""
        return self._safe(lambda: self.input.key(key))

    def KeyPressChar(self, ch: str) -> int:
        """按一个字符键，如 ``"a"``。"""
        return self._safe(lambda: self.input.key(str(ch)))

    def KeyPressStr(self, key_string: str, delay: float = 0.05) -> int:
        """按功能键名，如 ``"HOME"`` / ``"BACK"``（可空格分隔多个）。"""
        def run():
            for name in str(key_string).replace("+", " ").split():
                self.input.key(name.upper())
                if delay:
                    time.sleep(delay)
        return self._safe(run)

    def SendString(self, text: str) -> int:
        return self._safe(lambda: self.input.text(str(text)))

    def SendString2(self, hwnd: int, text: str) -> int:  # noqa: ARG002
        return self.SendString(text)

    def _safe(self, fn) -> int:
        try:
            fn()
            return 1
        except Exception as exc:
            self.last_error = str(exc)
            return 0

    # ==================================================================== OCR
    def _ocr_engine(self) -> OcrEngine:
        if self.ocr is None:
            self.ocr = OcrEngine(backend="auto")
        return self.ocr

    def Ocr(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
            color: str = "FFFFFF-000000", sim: float = 0.9) -> str:
        """识别文字，返回 ``"x|y|文字|x|y|文字2|..."``。"""
        try:
            res = self._ocr_engine().recognize(self._frame(), region=self._rect(x1, y1, x2, y2),
                                               color=color, sim=sim)
            return "|".join(f"{r.x}|{r.y}|{r.text}" for r in res)
        except Exception as exc:
            self.last_error = str(exc)
            return ""

    def FindStr(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
                string: str = "", color: str = "FFFFFF-000000", sim: float = 0.9) -> str:
        """找字，返回 ``"index|x|y"``（index 是第几个待查字符串），找不到 ``"-1|-1|-1"``。"""
        try:
            strings = [s for s in str(string).split("|") if s]
            found = self._ocr_engine().find_str(self._frame(), *strings,
                                                region=self._rect(x1, y1, x2, y2),
                                                color=color, sim=sim)
            return f"{found[0][0]}|{found[0][1]}|{found[0][2]}" if found else "-1|-1|-1"
        except Exception as exc:
            self.last_error = str(exc)
            return "-1|-1|-1"

    def FindStrEx(self, x1: int = 0, y1: int = 0, x2: int = 0, y2: int = 0,
                  string: str = "", color: str = "FFFFFF-000000", sim: float = 0.9) -> str:
        try:
            strings = [s for s in str(string).split("|") if s]
            found = self._ocr_engine().find_str(self._frame(), *strings,
                                                region=self._rect(x1, y1, x2, y2),
                                                color=color, sim=sim)
            return "|".join(f"{i}|{x}|{y}" for i, x, y in found)
        except Exception as exc:
            self.last_error = str(exc)
            return ""

    # ==================================================================== 其他
    def Delay(self, ms: int) -> int:
        time.sleep(max(0, int(ms)) / 1000.0)
        return 1

    def Ver(self) -> str:
        return self.VERSION

    # -------------------------------------------------- Python 风格的便利接口
    def find_pic_list(self, pic_name: str, sim: float = 0.9, delta="101010",
                      region: Rect | None = None, max_results: int = 10) -> list[Match]:
        """返回 :class:`Match` 列表（带 score/尺寸），UI 与脚本用起来更方便。"""
        base = self._frame()
        pics = self._load_pics(pic_name)
        if not pics:
            return []
        if len(pics) == 1:
            return find_pic(base, pics[0][1], sim=sim, delta=delta, max_results=max_results,
                            region=region, name=pics[0][0])
        return find_pic_multi(base, pics, sim=sim, delta=delta, max_results=max_results, region=region)
