"""OCR：大漠风格的 ``Ocr`` / ``FindStr``，后端可插拔。

三种后端（按优先级自动挑选，缺依赖会自动跳过）::

    rapidocr   pip install rapidocr-onnxruntime    中文效果最好，纯本地、离线
    tesseract  安装 tesseract-ocr（含 chi_sim 语言包）     老牌
    fontlib    **零依赖**：用你自己的"字库"（一个字符一张透明 PNG）做模板匹配

大漠的 ``Ocr`` 会先按颜色把图二值化再识别，这里也是一样：
``Ocr(x1,y1,x2,y2, "FFFFFF-101010", 0.9)`` 只保留与给定颜色相近的像素。
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 OpenCV") from exc

from .image import binarize_by_color, ensure_bgr, load_image, save_image, split_alpha
from .types import Rect

__all__ = ["OcrResult", "OcrBackend", "RapidOcrBackend", "TesseractBackend",
           "FontLib", "FontLibBackend", "OcrEngine", "available_backends"]


@dataclass
class OcrResult:
    text: str
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    score: float = 1.0

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.w // 2, self.y + self.h // 2

    @property
    def rect(self) -> Rect:
        return Rect.from_xywh(self.x, self.y, self.w, self.h)

    def __str__(self) -> str:
        return f"{self.x}|{self.y}|{self.text}"


class OcrBackend(ABC):
    name = "base"

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        """输入 BGR 图（已按颜色二值化过），返回识别结果。"""

    def info(self) -> str:
        return self.name


# --------------------------------------------------------------------------
class RapidOcrBackend(OcrBackend):
    """RapidOCR（onnxruntime），中文识别效果好，完全离线。"""

    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None
        self._error = ""

    def is_available(self) -> bool:
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
            self._engine = RapidOCR()
            return True
        except Exception as exc:  # pragma: no cover
            self._error = str(exc)
            return False

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        if self._engine is None and not self.is_available():
            raise RuntimeError(f"RapidOCR 不可用（pip install rapidocr-onnxruntime）: {self._error}")
        res, _ = self._engine(ensure_bgr(image))
        out: list[OcrResult] = []
        for box, text, score in (res or []):
            pts = np.asarray(box, dtype=np.float32).reshape(-1, 2)
            x, y = pts.min(axis=0)
            x2, y2 = pts.max(axis=0)
            out.append(OcrResult(str(text), int(x), int(y), int(x2 - x), int(y2 - y), float(score)))
        return out


class TesseractBackend(OcrBackend):
    """tesseract 命令行（不依赖 pytesseract）。"""

    name = "tesseract"

    def __init__(self, lang: str = "chi_sim+eng") -> None:
        self.lang = lang
        self._exe = ""

    def is_available(self) -> bool:
        import shutil
        self._exe = shutil.which("tesseract") or ""
        return bool(self._exe)

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        import subprocess
        import tempfile
        if not self._exe and not self.is_available():
            raise RuntimeError("未找到 tesseract，请安装 tesseract-ocr 并加入 PATH")
        gray = cv2.cvtColor(ensure_bgr(image), cv2.COLOR_BGR2GRAY)
        _, binimg = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "ocr.png")
            cv2.imwrite(path, binimg)
            out = subprocess.run([self._exe, path, "stdout", "-l", self.lang, "--psm", "6", "tsv"],
                                 capture_output=True, text=True, timeout=120)
        rows = out.stdout.splitlines()
        if not rows:
            return []
        head = rows[0].split("\t")
        idx = {name: head.index(name) for name in head}
        results: list[OcrResult] = []
        for line in rows[1:]:
            cells = line.split("\t")
            if len(cells) < len(head):
                continue
            text = cells[idx["text"]].strip()
            if not text:
                continue
            try:
                conf = float(cells[idx["conf"]])
                left, top = int(cells[idx["left"]]), int(cells[idx["top"]])
                w, h = int(cells[idx["width"]]), int(cells[idx["height"]])
            except (ValueError, KeyError):
                continue
            if conf < 0:
                continue
            results.append(OcrResult(text, left, top, w, h, conf / 100.0))
        return results


# --------------------------------------------------------------------------
def tight_mask(mask: np.ndarray) -> np.ndarray | None:
    """裁掉外围空白，只留笔画的外接矩形（字库匹配要先归一化，否则尺寸差太多）。"""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


class FontLib:
    """字库：一个目录，里面每个 PNG 是一个字符（透明区不算笔画）。

    文件名约定（任选一种）::

        U+4E2D.png        Unicode 码点
        4E2D.png          十六进制码点
        中.png            直接字符（Windows/中文路径 OK）
    """

    def __init__(self, dict_dir: str | None = None) -> None:
        self.dict_dir = Path(dict_dir) if dict_dir else None
        self.glyphs: dict[str, np.ndarray] = {}   # char -> 二值图 uint8 (0/255)

    # ------------------------------------------------------------ 加载
    @staticmethod
    def _char_of(stem: str) -> str | None:
        m = re.fullmatch(r"(?:U\+|u\+)?([0-9A-Fa-f]{4,6})", stem)
        if m:
            try:
                return chr(int(m.group(1), 16))
            except ValueError:
                return None
        return stem if len(stem) == 1 else None

    def reload(self) -> int:
        self.glyphs.clear()
        if not self.dict_dir or not self.dict_dir.is_dir():
            return 0
        for path in sorted(self.dict_dir.glob("*.png")):
            ch = self._char_of(path.stem)
            if not ch:
                continue
            try:
                img = load_image(str(path), with_alpha=True)
            except Exception:
                continue
            _, a = split_alpha(img)
            glyph = tight_mask((a > 0).astype(np.uint8) * 255)
            if glyph is not None:
                self.glyphs[ch] = glyph
        return len(self.glyphs)

    def add(self, char: str, img: np.ndarray, thresh: int = 0) -> str:
        """把一个裁剪好的字符加入字库（自动二值化）。"""
        if not self.dict_dir:
            raise ValueError("未设置字库目录")
        self.dict_dir.mkdir(parents=True, exist_ok=True)
        gray = cv2.cvtColor(ensure_bgr(img), cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, max(0, int(thresh)), 255, cv2.THRESH_BINARY)
        tight = tight_mask(mask)
        if tight is None:
            raise ValueError("这个字符模板是空的（没有笔画像素）")
        path = self.dict_dir / f"U+{ord(char):04X}.png"
        save_image(str(path), np.dstack([tight, tight, tight, tight]))
        self.glyphs[char] = tight
        return str(path)


class FontLibBackend(OcrBackend):
    """字库匹配：连通域切字 → 与字库模板算 IoU → 按阅读顺序输出。零依赖。"""

    name = "fontlib"

    def __init__(self, dict_dir: str | None = None, sim: float = 0.72,
                 min_area: int = 8, max_area: int = 200_000) -> None:
        self.lib = FontLib(dict_dir)
        self.sim = float(sim)
        self.min_area = int(min_area)
        self.max_area = int(max_area)

    def is_available(self) -> bool:
        return bool(self.lib.glyphs) or bool(self.lib.reload())

    def info(self) -> str:
        return f"fontlib({len(self.lib.glyphs)} 字)"

    def recognize(self, image: np.ndarray) -> list[OcrResult]:
        if not self.lib.glyphs and not self.lib.reload():
            raise RuntimeError("字库为空：先在字库目录里放字符模板（U+4E2D.png 这种）")
        gray = cv2.cvtColor(ensure_bgr(image), cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)
        # 竖向轻微膨胀，把上下结构的汉字连成一体
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (2, 3)))
        count, _labels, stats, _cent = cv2.connectedComponentsWithStats(mask, connectivity=8)
        items: list[OcrResult] = []
        for i in range(1, count):
            x, y, w, h, area = stats[i]
            if area < self.min_area or area > self.max_area or w < 2 or h < 2:
                continue
            sub = tight_mask(mask[y:y + h, x:x + w])
            if sub is None:
                continue
            ch, score = self._match_char(sub)
            if ch:
                items.append(OcrResult(ch, int(x), int(y), int(w), int(h), float(score)))
        # 按"行"聚合：y 相近的算一行，行内按 x 排序
        items.sort(key=lambda r: (r.y, r.x))
        lines: list[list[OcrResult]] = []
        for item in items:
            for line in lines:
                if abs((line[0].y + line[0].h // 2) - (item.y + item.h // 2)) <= max(4, item.h // 2):
                    line.append(item)
                    break
            else:
                lines.append([item])
        out: list[OcrResult] = []
        for line in lines:
            line.sort(key=lambda r: r.x)
            out.extend(line)
        return out

    def _match_char(self, sub: np.ndarray) -> tuple[str | None, float]:
        best, best_score = None, 0.0
        for ch, glyph in self.lib.glyphs.items():
            if glyph.size == 0:
                continue
            g = cv2.resize(glyph, (sub.shape[1], sub.shape[0]), interpolation=cv2.INTER_AREA)
            _, gb = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)
            inter = int(np.count_nonzero((sub > 0) & (gb > 0)))
            union = int(np.count_nonzero((sub > 0) | (gb > 0)))
            score = inter / union if union else 0.0
            if score > best_score:
                best, best_score = ch, score
        return (best if best_score >= self.sim else None), best_score


# --------------------------------------------------------------------------
class OcrEngine:
    """统一入口：自动挑一个可用后端，支持手动切换。"""

    PREFERENCE = ("rapidocr", "tesseract", "fontlib")

    def __init__(self, backend: str = "auto", dict_dir: str | None = None,
                 tesseract_lang: str = "chi_sim+eng") -> None:
        self.backends: dict[str, OcrBackend] = {
            "rapidocr": RapidOcrBackend(),
            "tesseract": TesseractBackend(lang=tesseract_lang),
            "fontlib": FontLibBackend(dict_dir),
        }
        self.current: OcrBackend | None = None
        self.set_backend(backend)

    # ------------------------------------------------------------ 管理
    def set_backend(self, name: str) -> OcrBackend:
        name = (name or "auto").lower()
        if name == "auto":
            for key in self.PREFERENCE:
                backend = self.backends[key]
                try:
                    if backend.is_available():
                        self.current = backend
                        return backend
                except Exception:
                    continue
            raise RuntimeError("没有任何可用的 OCR 后端（pip install rapidocr-onnxruntime）")
        if name not in self.backends:
            raise ValueError(f"未知 OCR 后端: {name}")
        backend = self.backends[name]
        if not backend.is_available():
            raise RuntimeError(f"OCR 后端 {name} 不可用")
        self.current = backend
        return backend

    def available(self) -> list[str]:
        out = []
        for key, backend in self.backends.items():
            try:
                if backend.is_available():
                    out.append(key)
            except Exception:
                pass
        return out

    # ------------------------------------------------------------ 识别
    def recognize(self, image: np.ndarray, region: Rect | None = None,
                  color: str | None = None, sim: float = 0.9) -> list[OcrResult]:
        """识别。``color`` 为空时不按颜色过滤（直接把整块区域交给引擎）。"""
        img = ensure_bgr(image)
        ox = oy = 0
        if region is not None:
            region = region.clamp(img.shape[1], img.shape[0])
            if not region.is_valid():
                return []
            img = img[region.slice()]
            ox, oy = region.x1, region.y1
        if color:
            img = binarize_by_color(img, color, sim)
        if self.current is None:
            self.set_backend("auto")
        results = self.current.recognize(img)
        for r in results:
            r.x += ox
            r.y += oy
        return results

    def find_str(self, image: np.ndarray, *strings: str, region: Rect | None = None,
                 color: str | None = None, sim: float = 0.9) -> list[tuple[int, int, int]]:
        """找字，返回 ``[(字符串序号, x, y), ...]``。"""
        results = self.recognize(image, region=region, color=color, sim=sim)
        joined = "".join(r.text for r in results)
        out: list[tuple[int, int, int]] = []
        for idx, target in enumerate(strings):
            pos = joined.find(str(target))
            if pos >= 0 and pos < len(results):
                r = results[pos]
                out.append((idx, r.x, r.y))
        return out


def available_backends() -> list[str]:
    """当前环境可用的后端名。"""
    engine = OcrEngine.__new__(OcrEngine)
    engine.backends = {
        "rapidocr": RapidOcrBackend(),
        "tesseract": TesseractBackend(),
        "fontlib": FontLibBackend(),
    }
    engine.current = None
    return engine.available()
