"""透明图制作：把截图/图片的背景一键抠成透明，生成大漠用的 PNG 模板。

流程与算法::

    1. 取背景色：界面上点一下（可点多个），或从边缘自动猜
    2. 判定：每个像素与背景色的色差 <= 容差 → 判为"背景"
       - mode="edge"   只从四边连通扩散（cv2.floodFill + FIXED_RANGE），
                       主体内部同色区域不会被误伤 —— 做图标/角色模板时推荐
       - mode="global" 全图同色都变透明，适合纯色底的按钮/文字
    3. 边缘：edge_adjust 收缩/扩张，feather 羽化出柔和边缘
    4. 输出 BGRA，透明区在 FindPic 时自动不参与匹配

    色差度量 metric:
       "max"    三通道最大差值（默认，与大漠偏色判定一致）
       "euclid" RGB 欧氏距离
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 OpenCV: pip install opencv-python-headless") from exc

from .image import ensure_bgr, save_image, split_alpha, with_alpha

__all__ = [
    "TransparentOptions", "guess_background", "make_transparent",
    "alpha_stats", "checkerboard", "composite_preview", "color_distance",
]


@dataclass
class TransparentOptions:
    """抠图参数。"""

    targets: list[tuple[int, int, int]] = field(default_factory=list)  # 背景色（RGB）
    tolerance: int = 32                 # 容差（0~255）
    mode: str = "edge"                  # "edge" | "global"
    metric: str = "max"                 # "max" | "euclid"
    feather: float = 0.0                # 边缘羽化半径（像素），0 关闭
    edge_adjust: int = 0                # >0 保留更多主体 / <0 透明区外扩
    soft: bool = False                  # 接近背景色的像素给半透明（抗锯齿更好）
    soft_ratio: float = 0.5             # 半透明带占比（soft=True 时生效）
    min_alpha: int = 0                  # 生成结果里 alpha 的下限

    def tol_tuple(self) -> tuple[int, int, int]:
        t = max(0, min(255, int(self.tolerance)))
        return (t, t, t)


def _to_rgb_array(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(ensure_bgr(img), cv2.COLOR_BGR2RGB)


def color_distance(rgb: np.ndarray, target: Sequence[int], metric: str = "max") -> np.ndarray:
    """像素与目标色的距离图（rgb 为 ``(..., 3)`` 的 RGB 数组）。"""
    arr = np.asarray(rgb, dtype=np.int16)
    tgt = np.array(target, dtype=np.int16).reshape((1,) * (arr.ndim - 1) + (3,))
    d = np.abs(arr - tgt)
    if metric == "euclid":
        return np.sqrt((d.astype(np.float32) ** 2).sum(axis=-1))
    return d.max(axis=-1)


def guess_background(img: np.ndarray) -> tuple[int, int, int]:
    """从图像边缘猜一个背景色（取四角 8x8 区域的中位数，最稳的那个）。"""
    rgb = _to_rgb_array(img)
    h, w = rgb.shape[:2]
    k = max(1, min(8, h // 8, w // 8))
    patches = [rgb[:k, :k], rgb[:k, -k:], rgb[-k:, :k], rgb[-k:, -k:]]
    stats = [(float(p.reshape(-1, 3).std(axis=0).mean()), np.median(p.reshape(-1, 3), axis=0))
             for p in patches]
    stats.sort(key=lambda s: s[0])
    return tuple(int(round(v)) for v in stats[0][1])


def _flood_from_border(bgr: np.ndarray, target_rgb: Sequence[int],
                       tol: tuple[int, int, int]) -> np.ndarray:
    """从四边连通扩散，找出与背景色相近且相连的区域。"""
    seed = (int(target_rgb[2]), int(target_rgb[1]), int(target_rgb[0]))  # BGR
    pad = cv2.copyMakeBorder(bgr, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=seed)
    h, w = bgr.shape[:2]
    # floodFill 的 mask 必须比图像四周各大 1 像素
    mask = np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8)
    lo = tuple(float(v) for v in tol)
    flags = 4 | cv2.FLOODFILL_FIXED_RANGE | cv2.FLOODFILL_MASK_ONLY | (255 << 8)
    cv2.floodFill(pad, mask, (0, 0), 255, loDiff=lo, upDiff=lo, flags=flags)
    return mask[2:-2, 2:-2] > 0


def _hard_alpha(bgr: np.ndarray, opts: TransparentOptions) -> tuple[np.ndarray, np.ndarray]:
    """返回 ``(alpha, distance_ratio)``；alpha 为 0~255 的硬边结果。"""
    rgb = _to_rgb_array(bgr)
    h, w = rgb.shape[:2]
    if not opts.targets:
        opts.targets = [guess_background(bgr)]

    remove = np.zeros((h, w), bool)
    ratio = np.full((h, w), np.inf, np.float32)  # 距离/容差，<1 表示在容差内
    tol_i = int(opts.tolerance)
    for target in opts.targets:
        dist = color_distance(rgb, target, opts.metric)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = dist / max(tol_i, 1)
        ratio = np.minimum(ratio, r.astype(np.float32))
        if opts.mode == "edge":
            remove |= _flood_from_border(bgr, target, opts.tol_tuple())
        else:
            remove |= dist <= tol_i

    alpha = np.where(remove, 0, 255).astype(np.uint8)
    return alpha, ratio


def make_transparent(img: np.ndarray, opts: TransparentOptions | None = None, **kw) -> np.ndarray:
    """抠背景生成 BGRA 图（透明区 alpha=0）。

    ``**kw`` 可直接覆盖 :class:`TransparentOptions` 的字段，
    例如 ``make_transparent(img, targets=[(255,255,255)], tolerance=40, mode="global")``。
    """
    opts = opts or TransparentOptions()
    if kw:
        for key, value in kw.items():
            if not hasattr(opts, key):
                raise TypeError(f"未知参数 {key!r}")
            setattr(opts, key, value)

    bgr = ensure_bgr(img)
    alpha, ratio = _hard_alpha(bgr, opts)

    if opts.edge_adjust:
        n = abs(int(opts.edge_adjust))
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * n + 1, 2 * n + 1))
        alpha = cv2.dilate(alpha, k) if opts.edge_adjust > 0 else cv2.erode(alpha, k)

    if opts.soft and opts.tolerance > 0:
        band = np.clip((ratio - opts.soft_ratio) / max(1e-6, 1.0 - opts.soft_ratio), 0.0, 1.0)
        alpha = np.minimum(alpha.astype(np.float32), (band * 255.0)).astype(np.uint8)

    if opts.feather and opts.feather > 0:
        a = alpha.astype(np.float32) / 255.0
        blur = cv2.GaussianBlur(a, (0, 0), sigmaX=float(opts.feather), sigmaY=float(opts.feather))
        alpha = np.clip(np.where(a >= 1.0, 1.0, blur) * 255.0, 0, 255).astype(np.uint8)

    if opts.min_alpha > 0:
        alpha = np.maximum(alpha, int(opts.min_alpha)).astype(np.uint8)

    return with_alpha(bgr, alpha)


def alpha_stats(bgra: np.ndarray) -> dict:
    """统计透明比例等信息，UI 展示用。"""
    _, a = split_alpha(bgra)
    total = a.size
    opaque = int((a >= 128).sum())
    return {
        "width": a.shape[1],
        "height": a.shape[0],
        "total": total,
        "opaque": opaque,
        "transparent": total - opaque,
        "opaque_ratio": opaque / total if total else 0.0,
    }


def checkerboard(w: int, h: int, size: int = 16,
                 c1=(210, 210, 210), c2=(160, 160, 160)) -> np.ndarray:
    """棋盘格底（BGR），用来预览透明区。"""
    yy, xx = np.mgrid[0:h, 0:w]
    grid = ((yy // size) + (xx // size)) % 2
    out = np.zeros((h, w, 3), np.uint8)
    out[grid == 0] = c1
    out[grid == 1] = c2
    return out


def composite_preview(bgra: np.ndarray, board: np.ndarray | None = None) -> np.ndarray:
    """把 BGRA 合成到棋盘格上，得到可直接显示的 BGR 图。"""
    bgr, a = split_alpha(bgra)
    if board is None:
        board = checkerboard(bgr.shape[1], bgr.shape[0])
    else:
        board = ensure_bgr(board)
        if board.shape[:2] != bgr.shape[:2]:
            board = cv2.resize(board, (bgr.shape[1], bgr.shape[0]))
    af = (a.astype(np.float32) / 255.0)[:, :, None]
    return np.clip(bgr.astype(np.float32) * af + board.astype(np.float32) * (1 - af), 0, 255).astype(np.uint8)


def save_template(path: str, bgra: np.ndarray, crop: bool = True) -> str:
    """保存透明图模板（PNG，保留 alpha）。``crop=True`` 时先裁掉外围透明边。"""
    if crop:
        from .image import auto_crop_alpha
        bgra = auto_crop_alpha(bgra)
    return save_image(path, bgra)
