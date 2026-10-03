"""内置资源（图标等）。"""
from __future__ import annotations

from pathlib import Path

__all__ = ["icon_path", "RESOURCE_DIR"]

RESOURCE_DIR = Path(__file__).resolve().parent
_ICON_CANDIDATES = ("imeg.ico", "imeg.png")


def icon_path() -> Path | None:
    """返回图标文件路径（打包后也能找到），没有则返回 None。"""
    import sys
    bases = [RESOURCE_DIR]
    if getattr(sys, "frozen", False):
        bases.insert(0, Path(getattr(sys, "_MEIPASS", RESOURCE_DIR)) / "imeg" / "resources")
        bases.insert(0, Path(sys.executable).resolve().parent / "imeg" / "resources")
    for base in bases:
        for name in _ICON_CANDIDATES:
            p = Path(base) / name
            if p.is_file():
                return p
    return None
