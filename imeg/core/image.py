"""图色引擎：找图（支持透明图）、找色、多点找色、比色、取色。

与大漠插件的语义对齐::

    FindPic      相似度 = 命中像素数 / 参与匹配的像素数
                 命中像素 = 三通道色差都在 delta_color 容差内
                 透明区（alpha < alpha_threshold）不参与匹配
    FindColor    在区域内找符合"颜色+偏色"的点，按 dir 方向返回第一个/全部
    FindMultiColor  先找基准色，再校验一组偏移点的颜色，sim = 命中点数/总点数

方向上（``dir``）本引擎的定义统一为::

    0 左上→右下   1 中心→外围   2 右下→左上
    3 右上→左下   4 左下→右上   5 外围→中心
"""
from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 OpenCV: pip install opencv-python-headless") from exc

from .color import ColorSpec, parse_colors, parse_delta_color, rgb_to_hex
from .types import Match, Point, Rect

__all__ = [
    "ensure_bgr", "to_rgb", "load_image", "save_image", "template_mask",
    "find_pic", "find_pic_multi", "find_color", "find_multi_color",
    "cmp_color", "get_color", "get_color_num", "binarize_by_color", "draw_matches",
    "split_alpha", "with_alpha", "auto_crop_alpha",
]


# --------------------------------------------------------------------------
# 基础图像工具
# --------------------------------------------------------------------------
def ensure_bgr(img: np.ndarray) -> np.ndarray:
    """把灰度 / BGRA / RGBA 统一成 3 通道 BGR（uint8）。"""
    if img is None:
        raise ValueError("图像为空")
    arr = np.asarray(img)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim != 3:
        raise ValueError(f"不支持的图像形状 {arr.shape}")
    if arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    if arr.shape[2] == 3:
        return arr
    raise ValueError(f"不支持的通道数 {arr.shape[2]}")


def to_rgb(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(ensure_bgr(bgr), cv2.COLOR_BGR2RGB)


def load_image(path: str, with_alpha: bool = False) -> np.ndarray:
    """读图。``with_alpha=True`` 时强制返回 4 通道 BGRA（无 alpha 的图补 255）。

    大漠的透明图就是带 alpha 通道的 PNG，所以这里默认走 ``IMREAD_UNCHANGED``。
    """
    # 用 fromfile + imdecode，兼容中文/Unicode 路径
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"读取图片失败: {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if with_alpha:
        if img.shape[2] == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
        return img
    return ensure_bgr(img) if img.shape[2] == 4 else img


def save_image(path: str, img: np.ndarray) -> str:
    """保存（支持中文路径，PNG 会保留 alpha 通道）。"""
    ext = str(path).rsplit(".", 1)[-1] if "." in str(path) else "png"
    ok, buf = cv2.imencode("." + ext, img)
    if not ok:
        raise ValueError(f"编码图片失败: {path}")
    with open(path, "wb") as f:
        f.write(buf.tobytes())
    return path


def split_alpha(bgra: np.ndarray):
    """BGRA -> (BGR, alpha)。"""
    if bgra.ndim == 3 and bgra.shape[2] == 4:
        return ensure_bgr(bgra), bgra[:, :, 3]
    return ensure_bgr(bgra), np.full(bgra.shape[:2], 255, np.uint8)


def with_alpha(bgr: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """(BGR, alpha) -> BGRA。"""
    bgr = ensure_bgr(bgr)
    a = np.asarray(alpha, dtype=np.uint8)
    if a.shape != bgr.shape[:2]:
        a = cv2.resize(a, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_NEAREST)
    return np.dstack([bgr, a])


def auto_crop_alpha(bgra: np.ndarray, pad: int = 0) -> np.ndarray:
    """按不透明区域裁掉外围透明边。"""
    _, a = split_alpha(bgra)
    ys, xs = np.nonzero(a > 0)
    if len(xs) == 0:
        return bgra
    x1, x2 = max(0, xs.min() - pad), min(bgra.shape[1] - 1, xs.max() + pad)
    y1, y2 = max(0, ys.min() - pad), min(bgra.shape[0] - 1, ys.max() + pad)
    return bgra[y1:y2 + 1, x1:x2 + 1]


def template_mask(template: np.ndarray, alpha_threshold: int = 128) -> np.ndarray:
    """模板的参与匹配区域：``255`` 参与、``0`` 透明不参与。"""
    if template.ndim == 3 and template.shape[2] == 4:
        return (template[:, :, 3] >= int(alpha_threshold)).astype(np.uint8) * 255
    return np.full(template.shape[:2], 255, np.uint8)


# --------------------------------------------------------------------------
# 找图
# --------------------------------------------------------------------------
def _masked_ssd(base: np.ndarray, tmpl: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """带 mask 的 SSD（平方差和），整图一次算完，等价于逐位置暴力比较。

    SSD(p) = Σ_k m_k·(B[p+k] - T_k)²
           = corr(B², m) - 2·corr(B, T·m) + Σ m_k·T_k²
    """
    b = base.astype(np.float32)
    t = tmpl.astype(np.float32)
    m = (mask > 0).astype(np.float32)
    b2 = b * b
    ssd = None
    for c in range(3):
        corr_b2 = cv2.matchTemplate(b2[:, :, c], m, cv2.TM_CCORR)
        corr_bt = cv2.matchTemplate(b[:, :, c], t[:, :, c] * m, cv2.TM_CCORR)
        const = float((t[:, :, c] * t[:, :, c] * m).sum())
        term = corr_b2 - 2.0 * corr_bt + const
        ssd = term if ssd is None else ssd + term
    return np.maximum(ssd, 0.0)


def _direction_keys(xs: np.ndarray, ys: np.ndarray, w: int, h: int, direction: int) -> np.ndarray:
    """按 dir 生成排序键（越小越优先）。"""
    d = int(direction)
    if d == 0:  # 左上 → 右下
        return ys.astype(np.int64) * w + xs
    if d == 1:  # 中心 → 外围
        return (xs - w // 2) ** 2 + (ys - h // 2) ** 2
    if d == 2:  # 右下 → 左上
        return -(ys.astype(np.int64) * w + xs)
    if d == 3:  # 右上 → 左下
        return ys.astype(np.int64) * w + (w - 1 - xs)
    if d == 4:  # 左下 → 右上
        return (h - 1 - ys).astype(np.int64) * w + xs
    if d == 5:  # 外围 → 中心
        return -((xs - w // 2) ** 2 + (ys - h // 2) ** 2)
    return ys.astype(np.int64) * w + xs


def _windows_view(base: np.ndarray, th: int, tw: int) -> np.ndarray:
    """所有候选窗口的视图 ``(H-th+1, W-tw+1, th, tw, 3)``，不复制数据。"""
    base = np.ascontiguousarray(base)
    H, W, C = base.shape
    shape = (H - th + 1, W - tw + 1, th, tw, C)
    strides = (base.strides[0], base.strides[1], base.strides[0], base.strides[1], base.strides[2])
    return np.lib.stride_tricks.as_strided(base, shape=shape, strides=strides, writeable=False)


def _exact_scores(base: np.ndarray, tmpl: np.ndarray, mask: np.ndarray,
                  delta: tuple[int, int, int], ys: np.ndarray, xs: np.ndarray,
                  max_bytes: int = 96 << 20) -> np.ndarray:
    """对候选位置精确计算"大漠相似度"。"""
    th, tw = tmpl.shape[:2]
    dt = np.array(delta, dtype=np.int16).reshape(1, 1, 3)
    lo = np.clip(tmpl.astype(np.int16) - dt, 0, 255).astype(np.uint8)
    hi = np.clip(tmpl.astype(np.int16) + dt, 0, 255).astype(np.uint8)
    mbool = mask > 0
    mcount = float(mbool.sum()) or 1.0

    windows = _windows_view(base, th, tw)
    per_item = th * tw * 3
    chunk = max(1, min(len(ys), int(max_bytes // max(1, per_item))))
    out = np.empty(len(ys), np.float32)
    for i in range(0, len(ys), chunk):
        yb, xb = ys[i:i + chunk], xs[i:i + chunk]
        batch = windows[yb, xb]  # (K, h, w, 3)
        good = np.all((batch >= lo) & (batch <= hi), axis=-1)
        out[i:i + chunk] = (good & mbool).sum(axis=(1, 2)) / mcount
    return out


def _nms(xs: np.ndarray, ys: np.ndarray, scores: np.ndarray, w: int, h: int,
         min_distance: float, max_results: int) -> list[int]:
    """按分数优先的非极大抑制；``min_distance<=0`` 时不做抑制。"""
    order = np.argsort(-scores, kind="stable")
    keep: list[list[int]] = []
    if min_distance and min_distance > 0:
        r2 = float(min_distance) ** 2
        for idx in order:
            x, y = float(xs[idx]), float(ys[idx])
            for kx, ky in keep:
                if (x - kx) ** 2 + (y - ky) ** 2 < r2:
                    break
            else:
                keep.append([x, y])
                if 0 < max_results <= len(keep):
                    break
        picked = []
        for kx, ky in keep:
            cand = np.where((xs == int(kx)) & (ys == int(ky)))[0]
            picked.append(int(cand[np.argmax(scores[cand])]))
        return picked
    if max_results > 0:
        order = order[:max_results]
    return [int(i) for i in order]


def find_pic(base: np.ndarray, template: np.ndarray, sim: float = 0.9,
             delta=16, direction: int = 0, max_results: int = 1,
             region: Rect | None = None, alpha_threshold: int = 128,
             mask: np.ndarray | None = None, min_distance: float | None = None,
             max_candidates: int = 20000, name: str = "") -> list[Match]:
    """找图（透明图会用 alpha 生成 mask，透明区不参与匹配）。

    :param base:      大图 BGR
    :param template:  模板 BGR 或 BGRA（BGRA 时按 alpha_threshold 生成 mask）
    :param sim:       相似度阈值 0~1
    :param delta:     颜色容差，``16`` 或 ``"101010"``（逐通道十六进制）
    :param direction: 0~5 查找方向
    :param max_results: 最多返回几个结果（<=0 表示全部）
    :param region:    查找区域（大图坐标，闭区间）
    :param alpha_threshold: alpha 小于该值视为透明
    :param min_distance: 结果间最小间距；默认 ``min(w,h)//2``；传 0 关闭抑制
    """
    base = ensure_bgr(base)
    if template is None:
        raise ValueError("模板为空")
    tmpl = np.asarray(template)
    if tmpl.ndim == 3 and tmpl.shape[2] == 4:
        tmpl = cv2.cvtColor(tmpl, cv2.COLOR_BGRA2BGR)
    tmpl = ensure_bgr(tmpl)

    offset_x = offset_y = 0
    if region is not None:
        region = region.clamp(base.shape[1], base.shape[0])
        if not region.is_valid():
            return []
        base = base[region.slice()]
        offset_x, offset_y = region.x1, region.y1

    bh, bw = base.shape[:2]
    th, tw = tmpl.shape[:2]
    if th > bh or tw > bw:
        return []

    m = template_mask(template, alpha_threshold) if mask is None else (mask > 0).astype(np.uint8) * 255
    if m.shape[:2] != (th, tw):
        m = cv2.resize(m, (tw, th), interpolation=cv2.INTER_NEAREST)
    mcount = float((m > 0).sum())
    if mcount <= 0:
        raise ValueError("模板无可匹配像素（整张图都是透明的）")

    dvec = parse_delta_color(delta)
    ssd = _masked_ssd(base, tmpl, m)

    # 有效剪枝：坏像素至少贡献 (min(delta)+1)^2，好像素最多贡献 Σd²
    dsum = sum(int(d) ** 2 for d in dvec)
    bad_lower = (ssd - mcount * dsum) / (3.0 * 255.0 * 255.0)
    keep_mask = bad_lower <= (1.0 - float(sim)) * mcount + 1e-6
    idxs = np.nonzero(keep_mask.ravel())[0]
    if idxs.size == 0:
        return []
    if idxs.size > max_candidates:  # 兜底：只保留 SSD 最优的一批
        idxs = idxs[np.argsort(ssd.ravel()[idxs], kind="stable")[:max_candidates]]
    ys, xs = np.unravel_index(idxs, ssd.shape)

    scores = _exact_scores(base, tmpl, m, dvec, ys, xs)
    hit = scores >= float(sim) - 1e-6
    if not hit.any():
        return []
    ys, xs, scores = ys[hit], xs[hit], scores[hit]

    keys = _direction_keys(xs, ys, bw, bh, direction)
    order = np.argsort(keys, kind="stable")
    ys, xs, scores = ys[order], xs[order], scores[order]

    if min_distance is None:
        min_distance = max(1, min(th, tw) // 2)
    picked = _nms(xs, ys, scores, tw, th, float(min_distance), max_results)

    return [
        Match(x=int(xs[i]) + offset_x, y=int(ys[i]) + offset_y, w=tw, h=th,
              score=float(scores[i]), name=name)
        for i in picked
    ]


def find_pic_multi(base: np.ndarray, templates: Sequence[np.ndarray] | Sequence[tuple[str, np.ndarray]],
                   sim: float = 0.9, delta=16, direction: int = 0, max_results: int = 0,
                   region: Rect | None = None, alpha_threshold: int = 128,
                   min_distance: float | None = None) -> list[Match]:
    """多图查找（对应大漠 ``"a.png|b.png"``），结果带 ``index`` 与 ``name``。"""
    results: list[Match] = []
    for i, item in enumerate(templates):
        name, tpl = item if isinstance(item, tuple) else (str(i), item)
        for m in find_pic(base, tpl, sim=sim, delta=delta, direction=direction,
                          max_results=0, region=region, alpha_threshold=alpha_threshold,
                          min_distance=min_distance, name=name):
            m.index = i
            results.append(m)
    if not results:
        return []
    keys = _direction_keys(
        np.array([m.x for m in results]), np.array([m.y for m in results]),
        base.shape[1], base.shape[0], direction)
    results = [m for _, m in sorted(zip(keys, results), key=lambda p: p[0])]
    if max_results > 0:
        results = results[:max_results]
    return results


# --------------------------------------------------------------------------
# 找色 / 多点找色 / 比色
# --------------------------------------------------------------------------
def find_color(base: np.ndarray, color, region: Rect | None = None,
               direction: int = 0, max_results: int = 0) -> list[Point]:
    """找色。``color`` 支持 ``"FFFFFF-101010|000000"`` 多色，任一命中即可。"""
    specs = parse_colors(color)
    rgb = to_rgb(base)
    ox = oy = 0
    if region is not None:
        region = region.clamp(rgb.shape[1], rgb.shape[0])
        if not region.is_valid():
            return []
        rgb = rgb[region.slice()]
        ox, oy = region.x1, region.y1
    hit = np.zeros(rgb.shape[:2], bool)
    for spec in specs:
        hit |= spec.match(rgb)
    ys, xs = np.nonzero(hit)
    if len(xs) == 0:
        return []
    keys = _direction_keys(xs.astype(np.int64), ys.astype(np.int64), rgb.shape[1], rgb.shape[0], direction)
    order = np.argsort(keys, kind="stable")
    ys, xs = ys[order], xs[order]
    if max_results > 0:
        ys, xs = ys[:max_results], xs[:max_results]
    return [Point(int(x) + ox, int(y) + oy) for x, y in zip(xs, ys)]


def parse_offset_spec(text: str) -> list[tuple[int, int, list[ColorSpec]]]:
    """解析多点找色的偏移串 ``"dx|dy|COLOR,dx|dy|COLOR"``。"""
    out: list[tuple[int, int, list[ColorSpec]]] = []
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        seg = part.split("|")
        if len(seg) < 3:
            raise ValueError(f"非法偏移点 {part!r}，格式应为 dx|dy|COLOR")
        dx, dy = int(seg[0]), int(seg[1])
        out.append((dx, dy, parse_colors("|".join(seg[2:]))))
    return out


def find_multi_color(base: np.ndarray, first_color, offset_color,
                     sim: float = 1.0, direction: int = 0, max_results: int = 1,
                     region: Rect | None = None, max_candidates: int = 50000) -> list[Match]:
    """多点找色：先定位基准色，再校验偏移点，``sim = 命中点数 / 总点数``。"""
    first = parse_colors(first_color)
    offsets = parse_offset_spec(offset_color)
    rgb = to_rgb(base)
    ox = oy = 0
    if region is not None:
        region = region.clamp(rgb.shape[1], rgb.shape[0])
        if not region.is_valid():
            return []
        rgb = rgb[region.slice()]
        ox, oy = region.x1, region.y1

    hit = np.zeros(rgb.shape[:2], bool)
    for spec in first:
        hit |= spec.match(rgb)
    ys, xs = np.nonzero(hit)
    if len(xs) == 0:
        return []
    h, w = rgb.shape[:2]

    pts = [(0, 0, first)] + list(offsets)  # 基准点也计入相似度
    hits = np.zeros(len(xs), np.int32)
    for dx, dy, specs in pts:
        px = xs + dx
        py = ys + dy
        inside = (px >= 0) & (px < w) & (py >= 0) & (py < h)
        sub = np.zeros(len(xs), bool)
        ii = np.nonzero(inside)[0]
        if len(ii):
            vals = rgb[py[ii], px[ii]]
            for spec in specs:
                sub[ii] |= spec.match(vals)
        hits += sub
    scores = hits / float(len(pts))
    ok = scores >= float(sim) - 1e-6
    if not ok.any():
        return []
    ys, xs, scores = ys[ok], xs[ok], scores[ok]
    if len(xs) > max_candidates:
        keys = _direction_keys(xs.astype(np.int64), ys.astype(np.int64), w, h, direction)
        order = np.argsort(keys, kind="stable")[:max_candidates]
        ys, xs = ys[order], xs[order]

    keys = _direction_keys(xs.astype(np.int64), ys.astype(np.int64), w, h, direction)
    order = np.argsort(keys, kind="stable")
    out: list[Match] = []
    for i in order:
        out.append(Match(x=int(xs[i]) + ox, y=int(ys[i]) + oy,
                         score=float(scores[i]), name="multicolor"))
        if 0 < max_results <= len(out):
            break
    return out


def get_color(base: np.ndarray, x: int, y: int) -> str:
    """取色，返回大漠风格 ``"RRGGBB"``（RGB 顺序）。"""
    b, g, r = (int(v) for v in ensure_bgr(base)[int(y), int(x)])
    return rgb_to_hex((r, g, b))


def cmp_color(base: np.ndarray, x: int, y: int, color) -> bool:
    """比色：该点是否落在"颜色+偏色"范围内。"""
    rgb = to_rgb(base)
    h, w = rgb.shape[:2]
    if not (0 <= int(x) < w and 0 <= int(y) < h):
        return False
    px = rgb[int(y), int(x)]
    return any(spec.match(px.reshape(1, 3))[0] for spec in parse_colors(color))


def get_color_num(base: np.ndarray, color, region: Rect | None = None) -> int:
    """统计区域内符合颜色的像素数。"""
    rgb = to_rgb(base)
    if region is not None:
        region = region.clamp(rgb.shape[1], rgb.shape[0])
        if not region.is_valid():
            return 0
        rgb = rgb[region.slice()]
    hit = np.zeros(rgb.shape[:2], bool)
    for spec in parse_colors(color):
        hit |= spec.match(rgb)
    return int(hit.sum())


def binarize_by_color(base: np.ndarray, color, sim: float = 0.9) -> np.ndarray:
    """OCR 前处理：把"不像目标颜色"的像素压成黑色，只保留目标色（大漠 Ocr 的做法）。

    这里 sim 用来放宽偏色：``tol' = tol + (1 - sim) * 255``。
    """
    rgb = to_rgb(base)
    out = np.zeros_like(rgb)
    for spec in parse_colors(color):
        grow = int(round((1.0 - float(sim)) * 255))
        grow = max(0, min(255, grow))
        wide = ColorSpec(spec.rgb, tuple(min(255, d + grow) for d in spec.tol))
        mask = wide.match(rgb)
        out[mask] = rgb[mask]
    return out


def draw_matches(base: np.ndarray, matches: Iterable[Match], color=(0, 255, 0),
                 thickness: int = 2, label: bool = True) -> np.ndarray:
    """把匹配结果画到图上（调试与 UI 展示用）。"""
    img = ensure_bgr(base).copy()
    for m in matches:
        cv2.rectangle(img, (m.x, m.y), (m.x + m.w - 1, m.y + m.h - 1), color, thickness)
        if label:
            text = f"{m.score:.2f}"
            cv2.putText(img, text, (m.x, max(12, m.y - 4)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, color, 1, cv2.LINE_AA)
    return img
