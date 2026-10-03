"""配色（色库）导入导出 —— 给"中控台 / 脚本 / 其它 agent"交接用。

产色流程（界面里一键完成）::

    勾上「批量取色」→ 在画面上连续点要采样的点
    → 每行记录：名称、颜色+偏色、采样坐标、可选的多点找色偏移
    → 导出 JSON / CSV / 大漠字符串

三种交换格式::

    JSON  imeg.palette/1     -- 推荐，带解析度、设备、备注，字段可扩展
    CSV   名称,颜色,偏移串,坐标,备注
    TXT   **TAB 分隔**（偏移串本身含 | 和逗号，用 TAB 才不会歧义）:
          名称<tab>颜色<tab>偏移串<tab>坐标<tab>备注

JSON 结构::

    {
      "schema": "imeg.palette/1",
      "name": "默认配色",
      "device": {"serial": "emulator-5554", "source": "adb",
                 "resolution": [1080, 2400], "wm_size": [1080, 2400]},
      "updated_at": "2026-10-03T16:00:00",
      "colors": [
        {"name": "按钮红", "color": "FF0000-101010",
         "offsets": "5|5|FF0000,10|10|00FF00",
         "point": [120, 70], "note": ""}
      ]
    }
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .color import parse_color
from .image import parse_offset_spec

__all__ = ["SCHEMA", "ColorEntry", "Palette", "export_palette", "import_palette",
           "palette_from_frame"]

SCHEMA = "imeg.palette/1"


@dataclass
class ColorEntry:
    """一条配色记录。"""

    name: str = ""
    color: str = "FFFFFF-101010"        # RRGGBB-DELTA
    offsets: str = ""                    # 多点找色偏移串 "dx|dy|COLOR,..."
    point: list[int] | None = None       # 采样坐标 [x, y]
    note: str = ""

    def validate(self) -> None:
        parse_color(self.color)
        if self.offsets.strip():
            parse_offset_spec(self.offsets)

    @property
    def is_multi(self) -> bool:
        return bool(self.offsets.strip())

    def dm_text(self) -> str:
        """大漠风格一行：``名称|颜色|偏移串|坐标``。"""
        pt = f"{self.point[0]},{self.point[1]}" if self.point else ""
        return "|".join([self.name, self.color, self.offsets, pt])


@dataclass
class Palette:
    """一份配色表。"""

    name: str = "默认配色"
    device: dict = field(default_factory=dict)
    colors: list[ColorEntry] = field(default_factory=list)
    updated_at: str = ""
    schema: str = SCHEMA

    # ---------------------------------------------------------------- 编辑
    def add(self, name: str, color: str, offsets: str = "",
            point: tuple[int, int] | None = None, note: str = "") -> ColorEntry:
        entry = ColorEntry(name=name, color=color, offsets=offsets,
                           point=list(point) if point else None, note=note)
        entry.validate()
        self.colors.append(entry)
        self.touch()
        return entry

    def remove(self, index: int) -> None:
        if 0 <= index < len(self.colors):
            self.colors.pop(index)
            self.touch()

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat(timespec="seconds")

    def __len__(self) -> int:
        return len(self.colors)

    # ---------------------------------------------------------------- 序列化
    def to_dict(self) -> dict:
        self.touch()
        return {
            "schema": SCHEMA,
            "name": self.name,
            "device": self.device,
            "updated_at": self.updated_at,
            "colors": [asdict(c) for c in self.colors],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Palette":
        pal = cls(name=data.get("name", "导入的配色"), device=data.get("device", {}) or {})
        for item in data.get("colors", []):
            try:
                pal.add(name=item.get("name", ""), color=item.get("color", "FFFFFF-101010"),
                        offsets=item.get("offsets", ""), point=item.get("point"),
                        note=item.get("note", ""))
            except Exception:
                continue
        pal.updated_at = data.get("updated_at", "")
        return pal

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Palette":
        return cls.from_dict(json.loads(text))

    # ---------------------------------------------------------------- 文本
    def to_text(self) -> str:
        """TAB 分隔文本，一行一条：``名称<tab>颜色<tab>偏移串<tab>坐标<tab>备注``。

        偏移串里本身就有 ``|`` 和 ``,``，所以用 TAB 分隔才不会有歧义。
        """
        rows = []
        for c in self.colors:
            pt = f"{c.point[0]},{c.point[1]}" if c.point else ""
            rows.append("\t".join([c.name, c.color, c.offsets, pt, c.note]))
        return "\n".join(rows)

    def to_dm_text(self) -> str:
        """``to_text`` 的别名（历史叫法）。"""
        return self.to_text()

    def to_csv_text(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["name", "color", "offsets", "x", "y", "note"])
        for c in self.colors:
            x, y = (c.point or ["", ""])[:2] if c.point else ("", "")
            writer.writerow([c.name, c.color, c.offsets, x, y, c.note])
        return buf.getvalue()

    @classmethod
    def from_csv_text(cls, text: str) -> "Palette":
        pal = cls(name="导入的配色")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        start = 1 if rows and rows[0] and rows[0][0].lower() in ("name", "名称") else 0
        for row in rows[start:]:
            if not row or not row[0].strip():
                continue
            row = row + [""] * (6 - len(row))
            point = None
            if row[3].strip() and row[4].strip():
                try:
                    point = (int(row[3]), int(row[4]))
                except ValueError:
                    point = None
            try:
                pal.add(row[0].strip(), row[1].strip() or "FFFFFF-101010", row[2].strip(),
                        point, row[5].strip())
            except Exception:
                continue
        return pal


def export_palette(palette: Palette, path: str) -> str:
    """按后缀自动选择格式（.json / .csv / .txt）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    suffix = p.suffix.lower()
    if suffix == ".json":
        text = palette.to_json()
    elif suffix == ".csv":
        text = palette.to_csv_text()
    else:
        text = palette.to_text()
    p.write_text(text, encoding="utf-8")
    return str(p)


def import_palette(path: str) -> Palette:
    """按后缀判断格式；没有后缀就按内容猜（含逗号当 CSV，否则当大漠文本）。"""
    text = Path(path).read_text(encoding="utf-8")
    suffix = Path(path).suffix.lower()
    if suffix == ".json":
        return Palette.from_json(text)
    if suffix == ".csv":
        return Palette.from_csv_text(text)
    if suffix == ".txt":
        return _from_text(text)
    if text.lstrip().startswith("{"):
        return Palette.from_json(text)
    return Palette.from_csv_text(text) if "," in text.splitlines()[0] else _from_text(text)


def _from_text(text: str) -> Palette:
    """解析 TAB 分隔文本；兼容旧的 ``|`` 分隔写法。"""
    pal = Palette(name="导入的配色")
    for line in text.splitlines():
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t")]
            parts += [""] * (5 - len(parts))
            name, color, offsets, coord, note = parts[:5]
        else:  # 旧格式 名称|颜色|偏移串|坐标 —— 偏移串含 |，取中间段拼回去
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                continue
            name, color = parts[0], parts[1]
            rest = parts[2:]
            coord = rest[-1] if rest else ""
            offsets = "|".join(rest[:-1])
            note = ""
        point = None
        if "," in coord:
            try:
                x, y = coord.split(",")[:2]
                point = (int(x), int(y))
            except ValueError:
                point = None
        try:
            pal.add(name or f"色{len(pal) + 1}", color or "FFFFFF-101010", offsets, point, note)
        except Exception:
            continue
    return pal


def palette_from_frame(frame) -> dict:
    """把当前画面/源的信息填进配色的 device 字段，方便中控台核对解析度。"""
    info: dict = {}
    try:
        info["source"] = frame.source.name
    except Exception:
        pass
    try:
        info["resolution"] = [frame.width, frame.height]
    except Exception:
        pass
    try:
        info["device_size"] = list(frame.source.device_size() or [])
    except Exception:
        pass
    try:
        info["serial"] = getattr(frame.source, "serial", None)
    except Exception:
        pass
    return {k: v for k, v in info.items() if v not in (None, [], "")}
