"""命令行做透明图：把纯色/边缘背景抠成 alpha，用于 FindPic。

    python examples/make_transparent.py input.png output.png --color FFFFFF --tol 40
    python examples/make_transparent.py input.png output.png --auto      # 自动猜背景色
"""
from __future__ import annotations

import argparse

from imeg.core.alpha import TransparentOptions, alpha_stats, guess_background, make_transparent, save_template
from imeg.core.color import hex_to_rgb
from imeg.core.image import load_image


def main() -> int:
    ap = argparse.ArgumentParser(description="抠背景生成透明图模板")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--color", default="", help="背景色 RRGGBB，可逗号分隔多个")
    ap.add_argument("--tol", type=int, default=32, help="色差容差 0-255")
    ap.add_argument("--mode", choices=["edge", "global"], default="edge",
                    help="edge=只抠边缘连通区(默认) / global=全局同色都抠")
    ap.add_argument("--metric", choices=["max", "euclid"], default="max")
    ap.add_argument("--feather", type=float, default=0.0, help="羽化半径（像素）")
    ap.add_argument("--edge-adjust", type=int, default=0, help=">0 保留更多主体 / <0 外扩透明区")
    ap.add_argument("--soft", action="store_true", help="接近背景色的像素给半透明")
    ap.add_argument("--auto", action="store_true", help="自动猜背景色")
    args = ap.parse_args()

    img = load_image(args.input)
    targets = [hex_to_rgb(c) for c in args.color.split(",") if c.strip()] or []
    if not targets or args.auto:
        targets = [guess_background(img)]
    print("背景色:", targets)

    bgra = make_transparent(img, TransparentOptions(
        targets=targets, tolerance=args.tol, mode=args.mode, metric=args.metric,
        feather=args.feather, edge_adjust=args.edge_adjust, soft=args.soft))
    save_template(args.output, bgra, crop=True)
    print("已保存", args.output, alpha_stats(bgra))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
