"""打包脚本的测试 —— 重点是防止"打出来的 EXE 少模块"这种只在运行时才炸的问题。"""
from __future__ import annotations

import ast
import sys

import pytest

from imeg.tools import build_exe as B


class Args:
    """够用的 argparse.Namespace 替身。"""

    def __init__(self, **kw):
        self.console = False
        self.onefile = False
        self.with_ocr = False
        self.with_av = False
        self.no_adb = False
        self.no_vcrt = False
        self.zip = False
        self.extra = None
        self.sign_self = False
        self.sign_pfx = None
        self.sign_password = None
        self.sign_deep = False
        self.dry_run = False
        self.__dict__.update(kw)


# ---------------------------------------------------------------- 入口脚本

def test_entry_is_absolute_import_launcher():
    """入口脚本必须只用绝对导入。

    PyInstaller 把入口当顶层脚本分析，包内相对导入（from .main_window import ...）
    解析不出全名，会静默漏掉整个 imeg.ui / imeg.core.dm 等模块。
    """
    src = B.ENTRY.read_text(encoding="utf-8")
    tree = ast.parse(src)
    mods: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "." * (node.level or 1))
    assert not [m for m in mods if m.startswith(".")], f"入口脚本里有相对导入: {mods}"
    assert "imeg.ui.app" in mods


def test_entry_file_exists():
    assert B.ENTRY.is_file(), B.ENTRY


# ---------------------------------------------------------------- 命令拼装

def _cmd(**kw) -> list[str]:
    return B.build_cmd(Args(**kw), True, B.write_version_file("0.1.0"))


def test_cmd_defaults():
    cmd = _cmd()
    assert "--onedir" in cmd and "--onefile" not in cmd
    assert "--noupx" in cmd                      # UPX 是杀软误报头号特征
    assert "--windowed" in cmd                   # 默认无控制台
    assert cmd[-1] == str(B.ENTRY)
    assert "--version-file" in cmd               # Windows 版本信息资源
    assert str(B.ICON) in cmd


def test_cmd_onefile_and_console():
    cmd = _cmd(onefile=True, console=True)
    assert "--onefile" in cmd and "--onedir" not in cmd
    assert "--console" in cmd and "--windowed" not in cmd


def test_cmd_no_version_file_on_posix():
    cmd = B.build_cmd(Args(), False, B.write_version_file("0.1.0"))
    assert "--version-file" not in cmd
    assert "PySide6.QtDBus" not in cmd           # Linux 的 Qt 插件可能要用


def test_cmd_bundles_data_files():
    cmd = _cmd()
    data = cmd[cmd.index("--add-data"):]
    joined = "\n".join(data)
    assert "style.qss" in joined
    assert "imeg/resources" in joined


def test_cmd_excludes_bloat_and_keeps_core():
    cmd = _cmd()
    excluded = {cmd[i + 1] for i, t in enumerate(cmd) if t == "--exclude-module"}
    assert {"PySide6.QtWebEngineCore", "matplotlib", "scipy"} <= excluded
    hidden = {cmd[i + 1] for i, t in enumerate(cmd) if t == "--hidden-import"}
    # 这些漏了就是启动即崩
    assert {"imeg.ui.main_window", "imeg.ui.widgets", "imeg.core.dm", "imeg.core.ocr",
            "imeg.core.inputctl", "imeg.core.palette", "imeg.ui.panels.color_panel",
            "imeg.ui.panels.findpic_panel", "imeg.ui.panels.transparent_panel"} <= hidden


def test_cmd_extra_args():
    cmd = _cmd(extra="--strip --log-level WARN")
    assert cmd[-4:] == ["--strip", "--log-level", "WARN", str(B.ENTRY)]


# ---------------------------------------------------------------- 版本信息

def test_write_version_file(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "BUILD_DIR", tmp_path)
    path = B.write_version_file("1.2.3")
    text = path.read_text(encoding="utf-8")
    assert path.is_file()
    assert "VSVersionInfo(" in text
    assert "(1, 2, 3, 0)" in text
    assert "FileVersion" in text and "1.2.3" in text


# ---------------------------------------------------------------- 收尾产物

def test_write_dist_readme(tmp_path):
    B.write_dist_readme(tmp_path, signed=False)
    assert (tmp_path / "使用说明.txt").is_file()
    assert (tmp_path / "pic").is_dir()
    txt = (tmp_path / "使用说明.txt").read_text(encoding="utf-8")
    assert "免依赖" in txt or "零依赖" in txt


def test_bundle_adb_missing_is_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(B.shutil, "which", lambda _name: None)
    assert B.bundle_adb(tmp_path) is False


def test_folder_size(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 2048)
    assert B.folder_size(tmp_path) >= 2048 / 1024 / 1024


# ---------------------------------------------------------------- 签名

def test_sign_skips_without_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(B, "find_signtool", lambda: None)
    assert B.sign(tmp_path / "nope.exe", None, None) is False


def test_sign_skips_on_posix(tmp_path):
    if sys.platform == "win32":
        pytest.skip("只在非 Windows 上测这条")
    assert B.sign(tmp_path / "nope.exe", None, None) is False
