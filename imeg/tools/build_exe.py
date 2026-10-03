"""一键打包成 EXE —— **目标机器零依赖**（不需要装 Python / Qt / OpenCV / adb）。

常用::

    build_exe.bat                                       # Windows 全依赖、强制签名便携包
    python -m imeg.tools.build_exe                      # 便携目录 dist/IMEG/IMEG.exe（推荐）
    python -m imeg.tools.build_exe --onefile            # 单文件 EXE（启动慢、更容易被误报）
    python -m imeg.tools.build_exe --zip                # 顺手压一个便携 zip
    python -m imeg.tools.build_exe --sign-self          # 用自签名证书签名（Windows）
    python -m imeg.tools.build_exe --sign-pfx my.pfx --sign-password 123456
    python -m imeg.tools.build_exe --console            # 带控制台，方便排错

默认做的事（都是为了让"干净的电脑"直接能跑）::

    1. PyInstaller 打包 Python + PySide6 + OpenCV + numpy（--noupx，避免 UPX 触发杀软）
    2. 写 Windows 版本信息资源（公司/产品名/版本号）—— 没有这个的 PyInstaller
       程序是杀软的重点怀疑对象
    3. 内嵌图标、样式表、字库等资源
    4. 把 adb（AdbWinApi.dll 等）打包进 tools/platform-tools/，没 adb 也能连设备
    5. 带上 VC++ 运行库（vcruntime140.dll 等），避免"缺 msvcp140.dll"
    6. 可选：签名、打 zip、生成使用说明

关于"签名"的实话::

    自签名证书只会给 EXE 写入 Authenticode 签名，不能让 SmartScreen 或其他电脑信任它，
    也不保证杀软放行。真正建立 Windows 发布者信任，需要受信任的 OV/EV 证书，
    或符合条件的开源代码签名服务（例如 SignPath.io Free Code Signing）。
"""
from __future__ import annotations

import argparse
from datetime import date
import os
import platform
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

__all__ = ["main", "build", "sign", "bundle_adb", "bundle_scrcpy_server",
           "DEFAULT_EXCLUDES", "HIDDEN_IMPORTS"]

ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "IMEG"
ENTRY = ROOT / "imeg" / "tools" / "pyi_entry.py"   # 见文件里的说明：必须用绝对导入的启动器
ICON = ROOT / "imeg" / "resources" / "imeg.ico"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
COMPANY = "IMEG"
PRODUCT = "IMEG 图色工具"
DESCRIPTION = "大漠风格的图色/控制工具：ADB 后台截图、模拟器窗口捕获、透明图"

#: 明确用不到的重模块，剔掉能把体积砍掉一大半
DEFAULT_EXCLUDES = [
    # PySide6 里我们用不到的全家桶
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
    "PySide6.QtWebSockets", "PySide6.QtWebView", "PySide6.Qt3DCore", "PySide6.Qt3DRender",
    "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtGraphs", "PySide6.QtGraphsWidgets", "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtBluetooth",
    "PySide6.QtNfc", "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio", "PySide6.QtStateMachine", "PySide6.QtNetworkAuth",
    "PySide6.QtRemoteObjects", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtTest",
    "PySide6.QtSql", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtTextToSpeech",
    "PySide6.QtHttpServer", "PySide6.QtWebChannel", "PySide6.QtScxml", "PySide6.QtSvg",
    "PySide6.QtSvgWidgets", "PySide6.QtUiTools", "PySide6.QtOpenGLWidgets",
    # 常见的大型第三方库（本项目不用）
    "matplotlib", "scipy", "pandas", "sklearn", "skimage", "torch", "tensorflow",
    "PIL.ImageQt", "IPython", "notebook", "pytest", "setuptools", "pip",
]

#: 只在 Windows 上排除（Linux 的 Qt 平台插件可能依赖 DBus）
WINDOWS_ONLY_EXCLUDES = ["PySide6.QtDBus"]

#: 这些是运行时按需 import 的，静态分析扫不到。
#: 另外整份 imeg.ui.* / imeg.core.* 也列一份当保险：入口脚本一旦被改回
#: 相对导入（见 imeg/tools/pyi_entry.py 的说明），PyInstaller 会静默漏掉它们，
#: 打出来的 EXE 一启动就 ModuleNotFoundError，所以这里兜底。
HIDDEN_IMPORTS = [
    "numpy",
    "PIL",
    "PIL.Image",
    "imeg.resources",
    "imeg.core.alpha",
    "imeg.core.color",
    "imeg.core.image",
    "imeg.core.palette",
    "imeg.core.types",
    "imeg.core.adb",
    "imeg.core.dm",
    "imeg.core.inputctl",
    "imeg.core.ocr",
    "imeg.core.capture",
    "imeg.core.capture.win32",
    "imeg.core.capture.adb_source",
    "imeg.core.capture.window_source",
    "imeg.core.capture.scrcpy_source",
    "imeg.ui.app",
    "imeg.ui.context",
    "imeg.ui.main_window",
    "imeg.ui.widgets",
    "imeg.ui.panels",
    "imeg.ui.panels.color_panel",
    "imeg.ui.panels.device_panel",
    "imeg.ui.panels.findpic_panel",
    "imeg.ui.panels.input_panel",
    "imeg.ui.panels.ocr_panel",
    "imeg.ui.panels.script_panel",
    "imeg.ui.panels.transparent_panel",
]

VERSION_TMPL = """\
# UTF-8
#
# Windows 版本信息资源 —— 没有它的 PyInstaller 程序很容易被杀软当马
#
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={prodvers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [StringStruct('CompanyName', '{company}'),
         StringStruct('FileDescription', '{description}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', '{app}'),
         StringStruct('LegalCopyright', 'Copyright (c) {year} {company}'),
         StringStruct('OriginalFilename', '{app}.exe'),
         StringStruct('ProductName', '{product}'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""

README_TXT = """\
IMEG {version} —— 便携版（免安装、免依赖）

【怎么跑】
  双击 IMEG.exe 即可。第一次运行杀软可能要几秒扫描，放行就好。

【目录说明】
  IMEG.exe              主程序
  _internal/            运行库（Python/Qt/OpenCV 都在这里，别删）
  tools/platform-tools/ 完整发行包内置 adb；若此目录缺失，需自行配置 adb / ANDROID_HOME
  pic/                  模板目录（界面里 SetPath 默认指到这里）
  imeg_crash.log        出错时生成的日志

【连设备】
  1. 模拟器：一般会自动出现在设备列表里（雷电 5555 / 夜神 62001 ...）
  2. 真机：手机开 USB 调试；无线的话先 USB 连一次执行 adb tcpip 5555，
     然后在软件里填 手机IP:5555 点「无线连接」

【截图源】
  ADB      后台截图，设备真实解析度，窗口不用在最前台
  窗口     不连 ADB，直接抓模拟器窗口，自动裁掉边框（仅 Windows）
  scrcpy   低延迟投屏流（打包时如已启用，会内置 scrcpy-server.jar + PyAV）

【离线依赖】
  Python、Qt、OpenCV、numpy、Pillow、psutil 等运行库均已打入本目录。
  若本包启用了 OCR，RapidOCR 模型也会一并打包；无需在目标电脑安装 Python。

【透明图】
  透明图页签 → 框选 → 在预览图上点背景色 → 调容差 → 保存为模板
  生成的 PNG 在找图时透明区自动不参与匹配

【给中控台交接配色】
  找色页签 → 勾「批量取色」→ Ctrl+左键在画面上点 → 导出 JSON/CSV/TXT

【签名 / 安全提示】
  本程序已带版本信息资源{extra}。
  若用的是自签名证书，其他电脑默认不会信任它，仍可能显示未知发布者或触发 SmartScreen；
  需要受信任的 OV/EV / SignPath 证书才能建立公信力。签名不等于杀软保证放行。
  如误报，请把 IMEG.exe 提交到 https://www.virustotal.com 申请复检。
"""


# --------------------------------------------------------------------------
def _version() -> str:
    sys.path.insert(0, str(ROOT))
    from imeg import __version__
    return __version__


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    printable = " ".join(str(c) for c in cmd)
    print(f"  $ {printable}")
    proc = subprocess.run([str(c) for c in cmd], cwd=str(cwd or ROOT))
    if proc.returncode != 0:
        raise SystemExit(f"命令失败（退出码 {proc.returncode}）: {printable}")


def ensure_pyinstaller() -> None:
    import importlib.util

    if importlib.util.find_spec("PyInstaller") is not None:
        print("[1/7] PyInstaller 已就绪")
        return
    print("[1/7] 安装 PyInstaller …")
    _run([sys.executable, "-m", "pip", "install", "-U", "pyinstaller>=6.3"])


def write_version_file(version: str) -> Path:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    parts = [int(p) if p.isdigit() else 0 for p in version.split(".")]
    vers = tuple((parts + [0, 0, 0, 0])[:4])
    text = VERSION_TMPL.format(filevers=vers, prodvers=vers, company=COMPANY,
                               description=DESCRIPTION, version=version, app=APP_NAME,
                               product=PRODUCT, year=date.today().year)
    path = BUILD_DIR / "version_info.txt"
    path.write_text(text, encoding="utf-8")
    return path


def build_cmd(args, is_windows: bool, version_file: Path) -> list[str]:
    """拼出 PyInstaller 命令（--dry-run 时也会用到）。"""
    cmd: list[str] = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                      "--name", APP_NAME, "--noupx",
                      "--distpath", str(DIST_DIR),
                      "--workpath", str(BUILD_DIR / "pyi"),
                      "--specpath", str(BUILD_DIR),
                      "--paths", str(ROOT)]
    cmd += ["--windowed"] if not args.console else ["--console"]
    if args.onefile:
        cmd += ["--onefile"]
    else:
        cmd += ["--onedir"]
    if ICON.is_file():
        cmd += ["--icon", str(ICON)]
    if is_windows and version_file.is_file():
        cmd += ["--version-file", str(version_file)]

    sep = os.pathsep
    data = [
        (ROOT / "imeg" / "ui" / "style.qss", "imeg/ui"),
        (ROOT / "imeg" / "resources", "imeg/resources"),
    ]
    for src, dst in data:
        if src.exists():
            cmd += ["--add-data", f"{src}{sep}{dst}"]

    for mod in DEFAULT_EXCLUDES + (WINDOWS_ONLY_EXCLUDES if is_windows else []):
        cmd += ["--exclude-module", mod]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]

    # RapidOCR loads ONNX models and ONNX Runtime's native providers dynamically.
    # Collect data/binaries explicitly so the offline OCR works on a clean PC.
    if getattr(args, "with_ocr", False):
        for package in ("rapidocr_onnxruntime", "onnxruntime"):
            cmd += ["--collect-all", package]
    else:
        cmd += ["--exclude-module", "rapidocr_onnxruntime"]

    # scrcpy needs PyAV; include it automatically when its server jar is requested.
    include_av = bool(getattr(args, "with_av", False)
                       or getattr(args, "with_scrcpy_server", False))
    if include_av:
        cmd += ["--collect-all", "av"]
    else:
        cmd += ["--exclude-module", "av"]
    if args.extra:
        cmd += args.extra.split()
    cmd += [str(ENTRY)]
    return cmd


def build(args) -> Path:
    ensure_pyinstaller()
    version = _version()
    is_windows = platform.system() == "Windows"
    version_file = write_version_file(version)
    cmd = build_cmd(args, is_windows, version_file)

    print(f"[2/7] 打包 {APP_NAME} {version}（{platform.system()}）…")
    _run(cmd)

    exe = DIST_DIR / APP_NAME / f"{APP_NAME}.exe" if is_windows else DIST_DIR / APP_NAME / APP_NAME
    if args.onefile:
        exe = DIST_DIR / (f"{APP_NAME}.exe" if is_windows else APP_NAME)
    if not exe.exists():  # 兜底找一下
        expected_name = f"{APP_NAME}.exe" if is_windows else APP_NAME
        candidates = [path for path in DIST_DIR.rglob(expected_name) if path.is_file()]
        if candidates:
            exe = candidates[0]
    print(f"      产物: {exe}")
    return exe


def _copy_platform_tools(src: Path, dest: Path) -> int:
    """复制 adb 及其同目录的可执行文件、DLL 和许可证说明。"""
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for file in src.iterdir():
        name = file.name.lower()
        target = dest / file.name
        if (file.is_file() and (file.suffix.lower() in (".dll", ".exe")
                                or name.startswith("adb")
                                or name in {"license", "license.txt", "notice", "notice.txt"})
                and file.resolve() != target.resolve()):
            shutil.copy2(file, target)
            copied += 1
    return copied


def _download_platform_tools(dest: Path) -> bool:
    """从 Google 官方分发地址获取 Windows Platform-Tools（ADB）。"""
    if platform.system() != "Windows":
        return False
    url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
    archive = BUILD_DIR / "deps" / "platform-tools-windows.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    print("      本机没找到 adb，正在从 Google 下载官方 Platform-Tools …")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "IMEG-build"})
        with urllib.request.urlopen(request, timeout=180) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
        with zipfile.ZipFile(archive) as zf:
            # 只复制平台工具压缩包根目录的文件名，避免解压路径穿越。
            for info in zf.infolist():
                parts = Path(info.filename).parts
                if info.is_dir() or len(parts) != 2 or parts[0].lower() != "platform-tools":
                    continue
                name = parts[1]
                if name in ("", ".", "..") or Path(name).name != name:
                    continue
                lower = name.lower()
                if not (lower.endswith((".dll", ".exe")) or lower.startswith("adb")
                        or lower in {"license", "license.txt", "notice", "notice.txt"}):
                    continue
                with zf.open(info) as src, (dest / name).open("wb") as out:
                    shutil.copyfileobj(src, out)
    except (OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"      下载/解压 adb 失败: {exc}")
        return False
    return ((dest / "adb.exe").is_file()
            and (dest / "AdbWinApi.dll").is_file()
            and (dest / "AdbWinUsbApi.dll").is_file())


def bundle_adb(dist_root: Path, download_missing: bool = False) -> bool:
    """把 adb 及 Windows 所需 DLL 拷进产物目录，目标机不用另装 adb。"""
    dest = dist_root / "tools" / "platform-tools"
    adb_names = ("adb.exe", "adb")
    if any((dest / name).is_file() for name in adb_names):
        if platform.system() != "Windows" or all((dest / name).is_file()
                                                   for name in ("AdbWinApi.dll", "AdbWinUsbApi.dll")):
            return True

    src: Path | None = None
    # ADB / ANDROID_ADB 可以直接指向 adb.exe，不必先把它加入 PATH。
    for raw in (os.environ.get("ADB"), os.environ.get("ANDROID_ADB")):
        if raw and Path(raw).is_file():
            src = Path(raw).parent
            break
    found = shutil.which("adb")
    if src is None and found:
        src = Path(found).parent
    if src is None:
        for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            base = os.environ.get(env)
            if base:
                candidate = Path(base) / "platform-tools"
                if any((candidate / name).is_file() for name in adb_names):
                    src = candidate
                    break
    local = ROOT / "tools" / "platform-tools"
    if src is None and any((local / name).is_file() for name in adb_names):
        src = local

    dest.mkdir(parents=True, exist_ok=True)
    if src is not None:
        count = _copy_platform_tools(src, dest)
        has_adb = any((dest / name).is_file() for name in adb_names)
        has_windows_dlls = (platform.system() != "Windows" or
                            all((dest / name).is_file()
                                for name in ("AdbWinApi.dll", "AdbWinUsbApi.dll")))
        if has_adb and has_windows_dlls:
            print(f"      已内置 adb（{count} 个文件）-> {dest}")
            return True

    if download_missing and _download_platform_tools(dest):
        print(f"      已内置 Google Platform-Tools -> {dest}")
        return True

    print("      [跳过] 没有可用的完整 adb。请安装 Android Platform-Tools，或把 adb.exe / DLL 放入 tools/platform-tools/。")
    return False


def bundle_scrcpy_server(dist_root: Path, source: Path | None = None,
                         required: bool = False, version: str | None = None) -> bool:
    """将 scrcpy-server.jar 和版本 sidecar 放到 exe 旁边；可选自动下载。"""
    candidates = [
        source,
        Path(os.environ["IMEG_SCRCPY_SERVER"]) if os.environ.get("IMEG_SCRCPY_SERVER") else None,
        ROOT / "tools" / "scrcpy-server.jar",
        ROOT / "vendor" / "scrcpy-server.jar",
        BUILD_DIR / "deps" / "scrcpy-server.jar",
        Path.home() / ".imeg" / "scrcpy-server.jar",
    ]
    jar = next((Path(path) for path in candidates if path and Path(path).is_file()), None)
    if jar is None:
        try:
            from .fetch_scrcpy_server import DEFAULT_VERSION, download
            target = BUILD_DIR / "deps" / "scrcpy-server.jar"
            jar = Path(download(version or DEFAULT_VERSION, str(target)))
        except (OSError, urllib.error.URLError, SystemExit) as exc:
            if required:
                raise SystemExit(f"下载 scrcpy-server.jar 失败: {exc}") from exc
            print(f"      [跳过] scrcpy-server.jar 未就绪: {exc}")
            return False
    if not jar.is_file():
        if required:
            raise SystemExit(f"找不到 scrcpy-server.jar: {jar}")
        print(f"      [跳过] 找不到 scrcpy-server.jar: {jar}")
        return False

    dist_root.mkdir(parents=True, exist_ok=True)
    target = dist_root / "scrcpy-server.jar"
    if jar.resolve() != target.resolve():
        shutil.copy2(jar, target)
    sidecar = jar.with_suffix(".json")
    sidecar_target = target.with_suffix(".json")
    if sidecar.is_file() and sidecar.resolve() != sidecar_target.resolve():
        shutil.copy2(sidecar, sidecar_target)
    print(f"      已内置 scrcpy-server.jar -> {target}")
    return True


def bundle_vcrt(dist_root: Path) -> int:
    """带上 VC++ 运行库，避免目标机器缺 msvcp140.dll / vcruntime140.dll。"""
    if platform.system() != "Windows":
        return 0
    names = ["vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
             "msvcp140_1.dll", "msvcp140_2.dll", "concrt140.dll"]
    have = {p.name.lower() for p in dist_root.rglob("*.dll")}
    copied = 0
    for name in names:
        if name.lower() in have:
            continue
        src = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / name
        if src.is_file():
            shutil.copy2(src, dist_root / name)
            copied += 1
    if copied:
        print(f"      已补 VC++ 运行库 {copied} 个 -> {dist_root}")
    return copied


def write_dist_readme(dist_root: Path, signed: bool) -> None:
    text = README_TXT.format(version=_version(),
                             extra="、内嵌图标" + ("，并已做数字签名" if signed else "（未签名）"))
    (dist_root / "使用说明.txt").write_text(text, encoding="utf-8")
    (dist_root / "pic").mkdir(exist_ok=True)
    print(f"      已写 {dist_root / '使用说明.txt'}")


def make_zip(dist_root: Path, onefile: bool) -> Path:
    if onefile:
        src_root = DIST_DIR
        members = [dist_root]
    else:
        src_root = dist_root
        members = list(dist_root.iterdir())
    out = DIST_DIR / f"{APP_NAME}-{_version()}-{platform.system().lower()}-portable.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in members:
            if path.is_dir():
                for f in path.rglob("*"):
                    # onefile 模式下压缩包本身也在 DIST_DIR，别把正在写入的 zip 包进去。
                    if f.is_file() and f.resolve() != out.resolve():
                        zf.write(f, f.relative_to(src_root))
            elif path.is_file() and path.resolve() != out.resolve():
                zf.write(path, path.relative_to(src_root))
    print(f"      便携包: {out}  ({out.stat().st_size / 1024 / 1024:.0f} MB)")
    return out


# --------------------------------------------------------------------------
def find_signtool() -> Path | None:
    which = shutil.which("signtool") or shutil.which("signtool.exe")
    if which:
        return Path(which)
    kits = Path(r"C:\Program Files (x86)\Windows Kits\10\bin")
    if kits.is_dir():
        cands = sorted(kits.glob("*/x64/signtool.exe"))
        if cands:
            return cands[-1]
    return None


def make_self_signed_pfx(pfx: Path, password: str, subject: str = "CN=IMEG Open Source") -> bool:
    """用 PowerShell 生成一张自签名代码签名证书（仅 Windows）。"""
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if not ps:
        return False
    pfx = pfx.resolve()
    pfx.parent.mkdir(parents=True, exist_ok=True)
    # 透过环境变量传入路径、主题与密码，避免把输入内容拼进 PowerShell 源码。
    env = os.environ.copy()
    env["IMEG_PFX_OUTPUT"] = str(pfx)
    env["IMEG_PFX_PASSWORD"] = password
    env["IMEG_CERT_SUBJECT"] = subject
    script = r"""
$ErrorActionPreference = 'Stop'
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $env:IMEG_CERT_SUBJECT `
    -CertStoreLocation 'Cert:\CurrentUser\My' -HashAlgorithm SHA256 `
    -KeyLength 2048 -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(3)
$pw = ConvertTo-SecureString -String $env:IMEG_PFX_PASSWORD -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath $env:IMEG_PFX_OUTPUT -Password $pw | Out-Null
Write-Output $cert.Thumbprint
"""
    proc = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True, env=env)
    if proc.returncode != 0 or not pfx.is_file():
        print(f"      自签名证书生成失败: {proc.stderr.strip()[:300]}")
        return False
    print(f"      已生成自签名证书 {pfx}（指纹 {proc.stdout.strip().splitlines()[-1]}）")
    return True


def sign(target: Path, pfx: Path | None, password: str, deep: bool = False,
         self_sign: bool = False) -> bool:
    """给产物签名。返回是否真的签上了。"""
    if platform.system() != "Windows":
        print("[4/7] 非 Windows：跳过签名（只影响 Windows SmartScreen）")
        return False
    if self_sign and (pfx is None or not pfx.is_file()):
        pfx = BUILD_DIR / "imeg-selfsign.pfx"
        password = password or "imeg"
        if not pfx.is_file():
            print("[4/7] 生成自签名证书 …")
            if not make_self_signed_pfx(pfx, password):
                return False
    if pfx is None or not pfx.is_file():
        print("[4/7] 未指定证书，跳过签名（加 --sign-self 或 --sign-pfx 证书.pfx）")
        return False

    tool = find_signtool()
    if tool is None:
        print("[4/7] 没找到 signtool.exe，跳过签名。")
        print("      装 Windows SDK（或只勾 Signing Tools）后重跑，")
        print("      或手动执行: signtool sign /f 证书.pfx /p 密码 /tr "
              "http://timestamp.digicert.com /td sha256 /fd sha256 IMEG.exe")
        return False

    if target.is_file():
        targets = [target]
    else:
        targets = sorted(target.rglob("*.exe"))
        if deep:
            targets += sorted(target.rglob("*.dll"))
    if not targets:
        return False

    ok = True
    for file in targets:
        signed_file = False
        # 优先打可信时间戳；网络不可用时再做无时间戳签名，至少保证 PE 中有签名。
        for server in ("http://timestamp.digicert.com", "http://timestamp.sectigo.com", None):
            cmd = [str(tool), "sign", "/f", str(pfx)]
            if password:
                cmd += ["/p", password]
            cmd += ["/fd", "SHA256"]
            if server:
                cmd += ["/td", "SHA256", "/tr", server]
            cmd += ["/v", str(file)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                print(f"      已签名 {file.name}")
                signed_file = True
                break
        if not signed_file:
            ok = False
            details = (proc.stderr or proc.stdout).strip().splitlines()
            print(f"      签名失败 {file.name}" + (f": {details[-1][:240]}" if details else ""))
    if ok and self_sign:
        print("      提示：自签名证书不会让 SmartScreen 放行；目标电脑仍需信任该证书，"
              "或使用受信任的 OV/EV / SignPath 代码签名证书。")
    return ok


# --------------------------------------------------------------------------
def folder_size(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1024 / 1024
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024


def run_selftest(exe: Path, with_ocr: bool = False, with_av: bool = False) -> None:
    """在构建机上启动打包产物，尽早发现漏模块、Qt 插件或 OCR 模型。"""
    cmd = [str(exe), "--selftest"]
    if with_ocr:
        cmd.append("--selftest-ocr")
    if with_av:
        cmd.append("--selftest-av")
    print("      运行打包后自检 …")
    try:
        proc = subprocess.run(cmd, cwd=str(exe.parent), capture_output=True, text=True, timeout=240)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"打包后自检无法启动: {exc}") from exc
    if proc.returncode != 0:
        detail = "\n".join(part.strip() for part in (proc.stdout, proc.stderr) if part.strip())
        log = exe.parent / "imeg_selftest.log"
        if log.is_file():
            detail = (detail + "\n" + log.read_text(encoding="utf-8", errors="replace")).strip()
        raise SystemExit("打包后自检失败" + (f":\n{detail}" if detail else f"（退出码 {proc.returncode}）"))
    log = exe.parent / "imeg_selftest.log"
    if log.is_file():
        log.unlink()
    print("      打包后自检通过")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="一键打包 IMEG（目标机器零依赖）")
    ap.add_argument("--onefile", action="store_true", help="打成单个 EXE（启动慢、误报率高）")
    ap.add_argument("--console", action="store_true", help="带控制台窗口（排错用）")
    ap.add_argument("--zip", action="store_true", help="再压一个便携 zip")
    ap.add_argument("--with-ocr", action="store_true", help="把 RapidOCR、ONNX Runtime 与模型一并打入（体积较大）")
    ap.add_argument("--with-av", action="store_true", help="把 PyAV 打进去（scrcpy 源要用）")
    ap.add_argument("--with-scrcpy-server", action="store_true", help="把 scrcpy-server.jar 放到 exe 旁，缺少时从官方发布页下载")
    ap.add_argument("--scrcpy-server-version", default=os.environ.get("IMEG_SCRCPY_SERVER_VERSION"),
                    help="scrcpy-server 版本，默认使用下载器内的稳定版本")
    ap.add_argument("--no-adb", action="store_true", help="不内置 adb")
    ap.add_argument("--require-adb", action="store_true", help="必须内置 adb；Windows 上本机未安装时自动下载官方 Platform-Tools")
    ap.add_argument("--no-vcrt", action="store_true", help="不补 VC++ 运行库")
    ap.add_argument("--sign-self", action="store_true", help="生成自签名证书并签名（Windows）")
    ap.add_argument("--sign-pfx", default=os.environ.get("IMEG_SIGN_PFX"), help="用指定的 PFX 证书签名（或设置 IMEG_SIGN_PFX）")
    ap.add_argument("--sign-password", default=os.environ.get("IMEG_SIGN_PASSWORD", ""),
                    help="PFX 密码（或设置 IMEG_SIGN_PASSWORD，避免写入命令行）")
    ap.add_argument("--require-signature", action="store_true", help="若签名未成功则让打包失败")
    ap.add_argument("--sign-deep", action="store_true", help="连内部 DLL 一起签（慢）")
    ap.add_argument("--extra", default="", help="追加给 PyInstaller 的参数")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    args = ap.parse_args(argv)
    if args.no_adb and args.require_adb:
        ap.error("--no-adb 和 --require-adb 不能同时使用")
    if args.no_adb and args.with_scrcpy_server:
        ap.error("scrcpy 依赖 adb，不能同时使用 --no-adb 和 --with-scrcpy-server")
    if args.sign_pfx and not args.dry_run and not Path(args.sign_pfx).is_file():
        ap.error(f"PFX 文件不存在：{args.sign_pfx}")

    print(f"IMEG 打包工具 —— 版本 {_version()}，平台 {platform.system()} {platform.machine()}")
    if args.dry_run:
        print("（--dry-run：只打印，不真正执行）")
        is_win = platform.system() == "Windows"
        print("  PyInstaller 命令:")
        for token in build_cmd(args, is_win, write_version_file(_version())):
            print("   ", token)

    if not args.dry_run:
        exe = build(args)
    else:
        exe = DIST_DIR / APP_NAME / f"{APP_NAME}.exe"

    dist_root = DIST_DIR if args.onefile else DIST_DIR / APP_NAME
    if not args.dry_run:
        if not exe.is_file():
            raise SystemExit(f"PyInstaller 未生成预期的程序文件：{exe}")
        print("[3/7] 补齐运行依赖 …")
        if not args.no_adb:
            adb_ok = bundle_adb(dist_root, download_missing=args.require_adb)
            if args.require_adb and not adb_ok:
                raise SystemExit("本次打包要求内置 adb，但未能取得完整 Platform-Tools；未生成可分发包。")
        if args.with_scrcpy_server:
            bundle_scrcpy_server(dist_root, required=True, version=args.scrcpy_server_version)
        if not args.no_vcrt:
            bundle_vcrt(dist_root)
        # 在签名前启动 EXE，验证 Python、Qt 和实际请求打包的可选依赖/模型。
        if platform.system() == "Windows":
            run_selftest(exe, with_ocr=args.with_ocr,
                         with_av=(args.with_av or args.with_scrcpy_server))

    print("[4/7] 签名 …")
    signed = False
    if not args.dry_run:
        signing_target = dist_root if args.sign_deep else exe
        signed = sign(signing_target, Path(args.sign_pfx).expanduser() if args.sign_pfx else None,
                      args.sign_password, deep=args.sign_deep,
                      self_sign=(args.sign_self and not bool(args.sign_pfx)))
        if args.require_signature and not signed:
            raise SystemExit("签名是必需的，但没有成功签署所有目标文件。请安装 Windows SDK Signing Tools，或提供有效的 PFX 证书。")

    print("[5/7] 写使用说明 …")
    if not args.dry_run:
        write_dist_readme(dist_root, signed=signed)

    print("[6/7] 收尾 / 压缩便携包 …")
    if args.zip and not args.dry_run:
        make_zip(dist_root, args.onefile)

    print("[7/7] 完成")
    if not args.dry_run and dist_root.exists():
        print(f"\n完成！产物目录: {dist_root}   大小 {folder_size(dist_root):.0f} MB")
        print(f"主程序: {exe}")
    print("""
后续建议（关于杀软误报，这些都是真管用的）:
  1. 优先用便携目录（默认），别用 --onefile：单文件自解压壳是杀软头号特征
  2. 已内嵌版本信息资源 + 图标，别用 UPX 压缩
  3. 把 IMEG.exe 提交 https://www.virustotal.com 复检，几天后各引擎会更新
  4. 想要 Windows 不再提示"未知发布者"：买 OV/EV 证书，或走
     https://signpath.io/ 的免费开源签名（仓库需公开 + OSI 许可证，本项目 MIT 符合）
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
