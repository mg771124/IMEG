"""配色（色库）导入导出测试 —— 这是给中控台交接的数据契约。"""
from __future__ import annotations

import json

import pytest

from imeg.core.palette import (
    SCHEMA, ColorEntry, Palette, export_palette, import_palette,
)


@pytest.fixture()
def palette() -> Palette:
    pal = Palette(name="测试配色", device={"source": "adb", "resolution": [1080, 2400]})
    pal.add("按钮红", "FF0000-101010", "5|5|FF0000,10|10|00FF00", (120, 70), "主按钮")
    pal.add("背景白", "FFFFFF-202020", point=(10, 10))
    return pal


def test_add_and_validate(palette):
    assert len(palette) == 2
    assert palette.colors[0].is_multi is True
    assert palette.colors[1].is_multi is False
    with pytest.raises(Exception):
        palette.add("坏色", "NOTACOLOR-101010")


def test_json_roundtrip(palette, tmp_path):
    path = tmp_path / "palette.json"
    export_palette(palette, str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == SCHEMA
    assert data["name"] == "测试配色"
    assert data["device"]["resolution"] == [1080, 2400]
    assert data["colors"][0]["color"] == "FF0000-101010"
    assert data["colors"][0]["offsets"] == "5|5|FF0000,10|10|00FF00"
    assert data["colors"][0]["point"] == [120, 70]

    back = import_palette(str(path))
    assert len(back) == 2
    assert back.colors[0].name == "按钮红"
    assert back.colors[0].point == [120, 70]
    assert back.colors[1].color == "FFFFFF-202020"


def test_csv_roundtrip(palette, tmp_path):
    path = tmp_path / "palette.csv"
    export_palette(palette, str(path))
    text = path.read_text(encoding="utf-8")
    assert "name,color,offsets,x,y,note" in text
    back = import_palette(str(path))
    assert len(back) == 2
    assert back.colors[0].color == "FF0000-101010"
    assert back.colors[0].point == [120, 70]
    assert back.colors[0].offsets == "5|5|FF0000,10|10|00FF00"


def test_text_roundtrip(palette, tmp_path):
    path = tmp_path / "palette.txt"
    export_palette(palette, str(path))
    lines = path.read_text(encoding="utf-8").splitlines()
    # 偏移串本身含 | 和 ,，所以整行用 TAB 分隔
    assert lines[0] == "按钮红\tFF0000-101010\t5|5|FF0000,10|10|00FF00\t120,70\t主按钮"
    assert lines[1].startswith("背景白\tFFFFFF-202020\t\t10,10")

    back = import_palette(str(path))
    assert len(back) == 2
    assert back.colors[0].name == "按钮红"
    assert back.colors[0].point == [120, 70]
    assert back.colors[0].offsets == "5|5|FF0000,10|10|00FF00"
    assert back.colors[0].note == "主按钮"


def test_legacy_pipe_text(palette, tmp_path):
    """兼容旧的 | 分隔写法（偏移串含 | 时按"中间段拼回去"解析）。"""
    path = tmp_path / "old.txt"
    path.write_text("按钮红|FF0000-101010|5|5|FF0000,10|10|00FF00|120,70\n", encoding="utf-8")
    back = import_palette(str(path))
    assert len(back) == 1
    assert back.colors[0].color == "FF0000-101010"
    assert back.colors[0].offsets == "5|5|FF0000,10|10|00FF00"
    assert back.colors[0].point == [120, 70]


def test_dm_text_entry_without_point():
    entry = ColorEntry(name="A", color="00FF00-101010")
    assert entry.dm_text() == "A|00FF00-101010||"
    assert entry.dm_text().rstrip("|") == "A|00FF00-101010"


def test_remove_and_clear(palette):
    palette.remove(0)
    assert len(palette) == 1
    assert palette.colors[0].name == "背景白"
    palette.colors.clear()
    assert len(palette) == 0
