"""核心图色引擎测试（合成图，无需真机）。"""
from __future__ import annotations

import numpy as np
import pytest

from imeg.core.alpha import TransparentOptions, make_transparent, alpha_stats, guess_background
from imeg.core.color import ColorSpec, parse_color, parse_colors, rgb_to_hex
from imeg.core.image import (
    find_color, find_multi_color, find_pic, find_pic_multi, get_color,
    get_color_num, cmp_color, template_mask, with_alpha, auto_crop_alpha, split_alpha,
)
from imeg.core.types import Rect


# ---------------------------------------------------------------- 颜色解析
def test_parse_color():
    assert parse_color("FFFFFF").rgb == (255, 255, 255)
    assert parse_color("FFFFFF").tol == (0, 0, 0)
    assert parse_color("FFFFFF-10").tol == (16, 16, 16)
    assert parse_color("FFFFFF-0F1E0A").tol == (15, 30, 10)
    assert parse_color(parse_color("123456-030303").to_str()).rgb == (0x12, 0x34, 0x56)
    assert [s.rgb for s in parse_colors("FF0000|00FF00")] == [(255, 0, 0), (0, 255, 0)]
    with pytest.raises(ValueError):
        parse_color("XYZXYZ")
    with pytest.raises(ValueError):
        parse_color("FFFFFF-1-2-3")


def test_color_match():
    spec = parse_color("FFFFFF-10")
    arr = np.array([[[255, 255, 255], [240, 255, 255], [200, 200, 200]]], np.uint8)
    assert spec.match(arr).tolist() == [[True, True, False]]


# ---------------------------------------------------------------- 构造测试图
def make_scene():
    """400x300 白底，一个红色方块 + 一个蓝色方块。"""
    img = np.full((300, 400, 3), 255, np.uint8)
    # 注意 OpenCV 是 BGR：(0,0,255) 存出来 RGB 是 FF0000（红），(255,0,0) 是 0000FF（蓝）
    img[50:110, 100:160] = (0, 0, 255)     # 红块 (100,50)-(159,109)
    img[200:240, 300:340] = (255, 0, 0)    # 蓝块 (300,200)-(339,239)
    return img


def test_find_pic_exact():
    base = make_scene()
    tpl = base[50:110, 100:160].copy()
    res = find_pic(base, tpl, sim=0.9, delta=16, max_results=1)
    assert len(res) == 1
    assert (res[0].x, res[0].y) == (100, 50)
    assert res[0].score == pytest.approx(1.0)
    assert res[0].w == 60 and res[0].h == 60


def test_find_pic_not_found_and_sim():
    base = make_scene()
    tpl = np.full((40, 40, 3), 0, np.uint8)  # 纯黑，图上没有
    assert find_pic(base, tpl, sim=0.9) == []
    # 相似度阈值提高后，带噪声的模板就找不到
    noisy = np.clip(base[50:110, 100:160].astype(np.int16) + 60, 0, 255).astype(np.uint8)
    assert find_pic(base, noisy, sim=0.95, delta=16) == []


def test_find_pic_with_noise_delta():
    base = make_scene()
    rng = np.random.default_rng(0)
    tpl = base[50:110, 100:160].astype(np.int16)
    tpl = np.clip(tpl + rng.integers(-10, 11, tpl.shape), 0, 255).astype(np.uint8)
    res = find_pic(base, tpl, sim=0.9, delta=16)
    assert res and (res[0].x, res[0].y) == (100, 50)
    assert res[0].score == pytest.approx(1.0)


def test_find_pic_region():
    base = make_scene()
    tpl = base[50:110, 100:160].copy()
    # 区域不包含目标 → 找不到
    assert find_pic(base, tpl, region=Rect(0, 0, 200, 40)) == []
    # 区域包含目标 → 坐标是大图坐标
    res = find_pic(base, tpl, region=Rect(50, 20, 250, 150))
    assert res and (res[0].x, res[0].y) == (100, 50)


def test_find_pic_transparent_mask():
    """透明图：模板里的透明区不参与匹配 —— 大漠透明图的核心语义。"""
    base = np.full((100, 100, 3), 200, np.uint8)   # 灰底
    base[20:60, 20:60] = (0, 0, 255)               # 蓝块（RGB=FF0000）
    # 模板取 60x60，其中只有覆盖蓝块的 40x40 区域保留（其余透明）
    tpl_bgr = base[10:70, 10:70].copy()
    alpha = np.zeros((60, 60), np.uint8)
    alpha[10:50, 10:50] = 255
    tpl = with_alpha(tpl_bgr, alpha)
    assert int(template_mask(tpl).sum() // 255) == 40 * 40

    res = find_pic(base, tpl, sim=0.9, delta=8)
    assert len(res) == 1
    assert (res[0].x, res[0].y) == (10, 10)
    assert res[0].score == pytest.approx(1.0)

    # 模板透明区对应的画面被涂掉 → 不影响匹配
    base2 = base.copy()
    base2[0:20, :] = 0
    base2[60:, :] = 0
    base2[:, 0:20] = 0
    base2[:, 60:] = 0
    res2 = find_pic(base2, tpl, sim=0.9, delta=8)
    assert res2 and (res2[0].x, res2[0].y) == (10, 10)

    # 参与匹配的区域被改掉 → 匹配不上
    base3 = base.copy()
    base3[30:40, 30:40] = (0, 255, 0)
    assert find_pic(base3, tpl, sim=0.99, delta=8) == []


def test_find_pic_multi():
    base = make_scene()
    tpls = [(name, base[y0:y1, x0:x1].copy())
            for name, (x0, y0, x1, y1) in
            [("blue", (100, 50, 160, 110)), ("red", (300, 200, 340, 240))]]
    res = find_pic_multi(base, tpls, sim=0.9, max_results=0)
    assert [(m.name, m.x, m.y) for m in res] == [("blue", 100, 50), ("red", 300, 200)]
    assert [m.index for m in res] == [0, 1]


def test_direction():
    base = np.zeros((60, 60, 3), np.uint8)
    base[5, 5] = base[5, 55] = base[55, 5] = base[55, 55] = 255
    p0 = find_color(base, "FFFFFF", direction=0, max_results=1)[0]
    p2 = find_color(base, "FFFFFF", direction=2, max_results=1)[0]
    p3 = find_color(base, "FFFFFF", direction=3, max_results=1)[0]
    assert (p0.x, p0.y) == (5, 5)
    assert (p2.x, p2.y) == (55, 55)
    assert (p3.x, p3.y) == (55, 5)


def test_find_color_and_get_color():
    base = make_scene()
    assert get_color(base, 120, 70) == "FF0000"    # 红块
    assert get_color(base, 320, 220) == "0000FF"   # 蓝块
    assert get_color(base, 10, 10) == "FFFFFF"
    assert len(find_color(base, "FF0000", max_results=0)) == 60 * 60
    assert find_color(base, "FF0000", max_results=1)[0].x == 100
    assert get_color_num(base, "FF0000") == 3600
    assert cmp_color(base, 120, 70, "FF0000-101010") is True
    assert cmp_color(base, 10, 10, "FF0000-101010") is False
    # 多色 + 区域限制：只在右下角区域里找蓝块
    assert find_color(base, "0000FF-000000|123456", region=Rect(260, 180, 399, 299),
                      max_results=1)[0].x == 300
    assert find_color(base, "0000FF", region=Rect(0, 0, 260, 180)) == []


def test_find_multi_color():
    base = make_scene()
    # 蓝块基准点 (100,50) 为白色外背景基准：用 (100,50) 蓝色 + 偏移点
    res = find_multi_color(base, "FF0000", "5|5|FF0000,30|30|FF0000", sim=1.0, max_results=1)
    assert res and (res[0].x, res[0].y) == (100, 50)
    # 偏移点颜色不对 → 找不到
    assert find_multi_color(base, "FF0000", "5|5|00FF00", sim=1.0, max_results=1) == []
    # 部分命中：sim 降低后可以命中
    res2 = find_multi_color(base, "FF0000", "5|5|FF0000,30|30|00FF00", sim=0.6, max_results=1)
    assert res2 and (res2[0].x, res2[0].y) == (100, 50)


# ---------------------------------------------------------------- 透明图
def test_make_transparent_global():
    img = np.full((80, 80, 3), 255, np.uint8)          # 白底
    img[20:60, 20:60] = (0, 0, 255)                    # 中间蓝块
    bgra = make_transparent(img, targets=[(255, 255, 255)], tolerance=10, mode="global")
    _, a = split_alpha(bgra)
    assert a[10, 10] == 0        # 白底变透明
    assert a[40, 40] == 255      # 主体保留
    st = alpha_stats(bgra)
    assert st["opaque"] == 40 * 40


def test_make_transparent_edge_keeps_interior():
    """边缘连通模式：主体内部与背景同色的区域不会被抠掉。"""
    img = np.full((80, 80, 3), 255, np.uint8)
    img[20:60, 20:60] = (0, 0, 255)
    img[30:50, 30:50] = 255                            # 蓝色块中间的白色洞
    bgra = make_transparent(img, targets=[(255, 255, 255)], tolerance=10, mode="edge")
    _, a = split_alpha(bgra)
    assert a[10, 10] == 0        # 外围白底 → 透明
    assert a[40, 40] == 255      # 内部白洞 → 保留
    bgra2 = make_transparent(img, targets=[(255, 255, 255)], tolerance=10, mode="global")
    assert split_alpha(bgra2)[1][40, 40] == 0


def test_make_transparent_tolerance_and_feather():
    img = np.full((60, 60, 3), 255, np.uint8)
    img[:, :] = (250, 250, 250)
    img[20:40, 20:40] = (0, 0, 255)
    strict = make_transparent(img, targets=[(255, 255, 255)], tolerance=2, mode="global")
    loose = make_transparent(img, targets=[(255, 255, 255)], tolerance=16, mode="global")
    assert int((split_alpha(strict)[1] == 0).sum()) < int((split_alpha(loose)[1] == 0).sum())

    feathered = make_transparent(loose, feather=2.0)
    a = split_alpha(feathered)[1]
    assert 0 < a[19, 30] < 255   # 边缘出现半透明


def test_make_transparent_edge_adjust():
    img = np.full((60, 60, 3), 255, np.uint8)
    img[20:40, 20:40] = (0, 0, 255)
    base = make_transparent(img, targets=[(255, 255, 255)], tolerance=10, mode="global")
    grow = make_transparent(img, targets=[(255, 255, 255)], tolerance=10, mode="global", edge_adjust=3)
    shrink = make_transparent(img, targets=[(255, 255, 255)], tolerance=10, mode="global", edge_adjust=-3)
    n = lambda x: int((split_alpha(x)[1] > 0).sum())
    assert n(shrink) < n(base) < n(grow)


def test_guess_background_and_crop():
    img = np.zeros((60, 60, 3), np.uint8)
    img[:, :] = (10, 20, 30)      # BGR
    img[20:40, 20:40] = (0, 0, 255)
    assert guess_background(img) == (30, 20, 10)  # RGB
    bgra = make_transparent(img, targets=[(30, 20, 10)], tolerance=5, mode="global")
    assert auto_crop_alpha(bgra).shape == (20, 20, 4)
