"""生成程序图标 imeg/resources/imeg.ico（深色底 + 青色取景框 + 中心取色点）。

    python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "imeg" / "resources" / "imeg.ico"
BG = (35, 42, 53, 255)
CYAN = (79, 179, 232, 255)
RED = (232, 92, 92, 255)
GREY = (150, 162, 180, 255)


def draw(size: int = 256) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(size * 0.18)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG)

    # 取景框（找图/选区的四角标记）
    m = int(size * 0.22)
    t = max(2, int(size * 0.055))
    arm = int(size * 0.20)
    for (x, y, dx, dy) in ((m, m, 1, 1), (size - m, m, -1, 1),
                           (m, size - m, 1, -1), (size - m, size - m, -1, -1)):
        d.line([x, y, x + dx * arm, y], fill=CYAN, width=t)
        d.line([x, y, x, y + dy * arm], fill=CYAN, width=t)

    # 中心取色十字
    c = size // 2
    d.ellipse([c - int(size * 0.11), c - int(size * 0.11),
               c + int(size * 0.11), c + int(size * 0.11)], outline=RED,
              width=max(2, int(size * 0.035)))
    d.line([c - int(size * 0.05), c, c + int(size * 0.05), c], fill=RED,
           width=max(2, int(size * 0.03)))
    d.line([c, c - int(size * 0.05), c, c + int(size * 0.05)], fill=RED,
           width=max(2, int(size * 0.03)))

    # 底部一条状态条
    d.rounded_rectangle([int(size * 0.28), int(size * 0.80),
                         int(size * 0.72), int(size * 0.86)],
                        radius=int(size * 0.03), fill=GREY)
    return img


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    base = draw(256)
    base.save(OUT, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    base.save(OUT.with_suffix(".png"))
    print(f"已生成 {OUT} 与 {OUT.with_suffix('.png')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
