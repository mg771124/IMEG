"""Windows 批次檔測試 —— 重點是「編碼不能跑掉」。

cmd.exe 用主控台字碼頁去解讀 .bat 的位元組：存成 UTF-8 中文會變亂碼，
存成 Big5 又會踩到「第二個 byte 是 \\ 或 | 」的地雷字。
所以這批 .bat 統一為**純 ASCII + CRLF + 無 BOM**，這裡把它們釘死。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAKE_BAT = ROOT / "tools" / "make_bat.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("make_bat", MAKE_BAT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


@pytest.fixture(scope="module", params=sorted(_load_generator().BATS))
def bat_file(request) -> Path:
    path = ROOT / request.param
    if not path.exists():
        pytest.fail(f"{request.param} 不存在，請先執行 python tools/make_bat.py")
    return path


def test_ascii_only(bat_file: Path):
    data = bat_file.read_bytes()
    bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
    assert not bad, f"{bat_file.name} 含非 ASCII 位元組（前幾個）：{bad[:5]}"


def test_no_bom(bat_file: Path):
    data = bat_file.read_bytes()
    for bom, name in ((b"\xef\xbb\xbf", "UTF-8"), (b"\xff\xfe", "UTF-16LE"), (b"\xfe\xff", "UTF-16BE")):
        assert not data.startswith(bom), f"{bat_file.name} 有 {name} BOM，請存成純 ANSI/ASCII"


def test_crlf_line_endings(bat_file: Path):
    data = bat_file.read_bytes()
    assert b"\r\n" in data, f"{bat_file.name} 不是 CRLF 換行"
    assert data.count(b"\r\n") == data.count(b"\n"), f"{bat_file.name} 混用 LF / CRLF"


def test_scripts_are_pinned(bat_file: Path, gen):
    """檔案內容必須和產生器裡的文字完全一致（改產生器後要重新產生）。"""
    expected = gen.encode_bat(gen.BATS[bat_file.name])
    assert bat_file.read_bytes() == expected, (
        f"{bat_file.name} 與 tools/make_bat.py 不一致，請執行：python tools/make_bat.py"
    )


def test_every_bat_starts_in_its_own_folder(bat_file: Path):
    text = bat_file.read_text("ascii")
    assert 'cd /d "%~dp0"' in text, f"{bat_file.name} 缺少 cd /d %~dp0（雙擊時目錄會不對）"
    assert "@echo off" in text


def test_generator_emits_ascii_for_all(gen):
    for name, text in gen.BATS.items():
        data = gen.encode_bat(text)
        assert all(b < 0x80 for b in data), f"{name} 產生結果不是純 ASCII"
        assert b"\r\n" in data


def test_checker_accepts_generated_files(bat_file: Path, gen):
    assert gen.check_bat(bat_file, bat_file.read_bytes()) == []


def test_checker_rejects_utf8_and_big5(tmp_path: Path, gen):
    """編碼地雷要能被檢查器擋下來：UTF-8 BOM、UTF-8 中文、Big5 中文。"""
    p = tmp_path / "x.bat"
    p.write_bytes(b'\xef\xbb\xbf@echo off\r\ncd /d "%~dp0"\r\n')
    assert any("BOM" in m for m in gen.check_bat(p, p.read_bytes())), "UTF-8 BOM 必須被抓到"

    p.write_bytes("@echo off\r\necho 中文\r\n".encode("utf-8"))
    assert gen.check_bat(p, p.read_bytes()), "UTF-8 中文必須被判為不合格"

    p.write_bytes("@echo off\r\necho 安裝成功\r\n".encode("cp950"))
    assert gen.check_bat(p, p.read_bytes()), "Big5 中文必須被判為不合格"

    p.write_bytes(b"@echo off\necho hi\n")
    assert any("CRLF" in m for m in gen.check_bat(p, p.read_bytes()))


def test_menu_links_to_existing_files(gen):
    """主選單呼叫的每個 .bat 都要真的存在。"""
    menu = gen.BATS["menu.bat"]
    for name in ("install.bat", "start.bat", "build.bat", "test.bat"):
        assert f'"{name}"' in menu, f"menu.bat 沒有呼叫 {name}"
        assert (ROOT / name).exists()
