"""打包脚本的测试 —— 重点是防止"打出来的 EXE 少模块"这种只在运行时才炸的问题。"""
from __future__ import annotations

import ast
import sys
import zipfile

import pytest

from imeg.core import adb as ADB
from imeg.tools import build_exe as B


class Args:
    """够用的 argparse.Namespace 替身。"""

    def __init__(self, **kw):
        self.console = False
        self.onefile = False
        self.with_ocr = False
        self.with_av = False
        self.with_scrcpy_server = False
        self.no_adb = False
        self.require_adb = False
        self.require_signature = False
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


def test_cmd_collects_optional_runtime_files_and_models():
    cmd = _cmd(with_ocr=True, with_av=True, with_scrcpy_server=True)
    collected = {cmd[i + 1] for i, token in enumerate(cmd) if token == "--collect-all"}
    excluded = {cmd[i + 1] for i, token in enumerate(cmd) if token == "--exclude-module"}
    assert {"rapidocr_onnxruntime", "onnxruntime", "av"} <= collected
    assert "rapidocr_onnxruntime" not in excluded
    assert "av" not in excluded


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
    for key in ("ADB", "ANDROID_ADB", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
        monkeypatch.delenv(key, raising=False)
    assert B.bundle_adb(tmp_path) is False


def test_bundle_adb_copies_exe_and_windows_dlls(tmp_path, monkeypatch):
    source = tmp_path / "sdk" / "platform-tools"
    source.mkdir(parents=True)
    for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"):
        (source / name).write_bytes(b"test")
    monkeypatch.setenv("ADB", str(source / "adb.exe"))
    monkeypatch.setattr(B.shutil, "which", lambda _name: None)
    monkeypatch.setattr(B.platform, "system", lambda: "Windows")

    out = tmp_path / "dist"
    assert B.bundle_adb(out) is True
    dest = out / "tools" / "platform-tools"
    assert all((dest / name).is_file()
               for name in ("adb.exe", "AdbWinApi.dll", "AdbWinUsbApi.dll"))


def test_frozen_app_finds_adb_next_to_exe(tmp_path, monkeypatch):
    tools = tmp_path / "tools" / "platform-tools"
    tools.mkdir(parents=True)
    adb = tools / "adb"
    adb.write_bytes(b"adb")
    adb.chmod(0o755)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "IMEG.exe"))
    monkeypatch.setattr(ADB.shutil, "which", lambda _name: None)
    for key in ("ADB", "ANDROID_ADB", "ANDROID_HOME", "ANDROID_SDK_ROOT"):
        monkeypatch.delenv(key, raising=False)

    assert ADB._find_adb() == str(adb)


def test_bundle_scrcpy_server_copies_jar_and_version(tmp_path):
    source = tmp_path / "scrcpy-server.jar"
    source.write_bytes(b"jar")
    source.with_suffix(".json").write_text('{"version":"3.3.1"}', encoding="utf-8")
    out = tmp_path / "dist"
    assert B.bundle_scrcpy_server(out, source=source, required=True) is True
    assert (out / "scrcpy-server.jar").read_bytes() == b"jar"
    assert (out / "scrcpy-server.json").is_file()


def test_batch_builds_signed_portable_full_dependency_bundle():
    bat = (B.ROOT / "build_exe.bat").read_text(encoding="utf-8")
    assert "--with-ocr" in bat and "--with-av" in bat
    assert "--with-scrcpy-server" in bat and "--require-adb" in bat
    assert "--require-signature" in bat and "--sign-self" in bat
    assert "requirements.txt" in bat and "requirements-ocr.txt" in bat


def test_sync_batch_scripts_are_branch_scoped_and_safe():
    download = (B.ROOT / "download_latest.bat").read_text(encoding="utf-8")
    upload = (B.ROOT / "upload_to_repo.bat").read_text(encoding="utf-8")
    branch = "arena/01a1029b-imeg"
    assert branch in download and "git fetch --prune origin" in download
    assert "git merge --ff-only" in download and "git status --porcelain" in download
    assert branch in upload and "git add -A" in upload and "git commit -m" in upload
    assert "git push --set-upstream origin" in upload
    assert "--force" not in upload and "--force" not in download


def test_onefile_zip_does_not_include_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "DIST_DIR", tmp_path)
    monkeypatch.setattr(B, "_version", lambda: "1.2.3")
    exe = tmp_path / "IMEG.exe"
    exe.write_bytes(b"portable exe")

    out = B.make_zip(tmp_path, onefile=True)
    with zipfile.ZipFile(out) as archive:
        assert archive.namelist() == ["IMEG.exe"]


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
