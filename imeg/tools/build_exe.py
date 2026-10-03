"""一键打包成 EXE —— **目标机器零依赖**（不需要装 Python / Qt / OpenCV / adb）。

常用::

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

    自签名证书 **不能** 让 SmartScreen 放行（它不信任自签证书），但能：
      - 消掉"未签名的可执行程序"这一类启发式规则（不少杀软对无签名直接打分）
      - 让文件属性里有发布者、版本、时间戳，看起来不像随手生成的马
    真正想让 Windows 不再弹"未知发布者"，只有两条路：
      a) 买 OV/EV 代码签名证书
      b) 走免费的正经渠道：SignPath.io Free Code Signing（面向开源项目，
         仓库需是公开仓库 + OSI 许可证；本项目是 MIT，符合条件）
         签名前先跑一遍 VirusTotal 提交，能显著加快信誉积累
"""
from __future__ import annotations

import argparse
from datetime import date
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

__all__ = ["main", "build", "sign", "bundle_adb", "DEFAULT_EXCLUDES", "HIDDEN_IMPORTS"]

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
  tools/platform-tools/ 内置 adb（没装 adb 也能连设备）
  pic/                  模板目录（界面里 SetPath 默认指到这里）
  imeg_crash.log        出错时生成的日志

【连设备】
  1. 模拟器：一般会自动出现在设备列表里（雷电 5555 / 夜神 62001 ...）
  2. 真机：手机开 USB 调试；无线的话先 USB 连一次执行 adb tcpip 5555，
     然后在软件里填 手机IP:5555 点「无线连接」

【截图源】
  ADB      后台截图，设备真实解析度，窗口不用在最前台
  窗口     不连 ADB，直接抓模拟器窗口，自动裁掉边框（仅 Windows）
  scrcpy   低延迟投屏流（需要 scrcpy-server.jar + PyAV，本便携版默认不含）

【透明图】
  透明图页签 → 框选 → 在预览图上点背景色 → 调容差 → 保存为模板
  生成的 PNG 在找图时透明区自动不参与匹配

【给中控台交接配色】
  找色页签 → 勾「批量取色」→ Ctrl+左键在画面上点 → 导出 JSON/CSV/TXT

【杀软误报】
  本程序已带版本信息资源{extra}。
  如果仍被拦截：把 IMEG.exe 提交到 https://www.virustotal.com 申请复检，
  或走 SignPath.io 的开源免费签名（仓库是 MIT，符合条件）。
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
        print("[1/6] PyInstaller 已就绪")
        return
    print("[1/6] 安装 PyInstaller …")
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
                      "--specpath", str(BUILD_DIR)]
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
    if not args.with_ocr:
        cmd += ["--exclude-module", "rapidocr_onnxruntime"]
    if not args.with_av:
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

    print(f"[2/6] 打包 {APP_NAME} {version}（{platform.system()}）…")
    _run(cmd)

    exe = DIST_DIR / APP_NAME / f"{APP_NAME}.exe" if is_windows else DIST_DIR / APP_NAME / APP_NAME
    if args.onefile:
        exe = DIST_DIR / (f"{APP_NAME}.exe" if is_windows else APP_NAME)
    if not exe.exists():  # 兜底找一下
        cands = list(DIST_DIR.rglob(f"{APP_NAME}*"))
        exe = next((c for c in cands if c.is_file() and (c.suffix in (".exe", "") or True)), exe)
    print(f"      产物: {exe}")
    return exe


def bundle_adb(dist_root: Path) -> bool:
    """把 adb 拷进产物目录，目标机器不用自己装 adb。"""
    dest = dist_root / "tools" / "platform-tools"
    if dest.exists() and any(dest.glob("adb*")):
        return True
    found = shutil.which("adb")
    src = Path(found).parent if found else None
    if src is None:
        for env in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            base = os.environ.get(env)
            if base:
                p = Path(base) / "platform-tools"
                if (p / "adb").is_file() or (p / "adb.exe").is_file():
                    src = p
                    break
    if src is None:
        print("      [跳过] 本机没找到 adb，打包后需要用户自己装（或设 ANDROID_HOME）")
        return False
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in Path(src).iterdir():
        if f.is_file() and (f.name.startswith("adb") or f.name.lower().startswith("adbwin")
                            or f.suffix.lower() in (".dll", ".exe")):
            shutil.copy2(f, dest / f.name)
            n += 1
    print(f"      已内置 adb（{n} 个文件）-> {dest}")
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
                    if f.is_file():
                        zf.write(f, f.relative_to(src_root))
            elif path.is_file():
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
    script = f"""
$ErrorActionPreference = 'Stop'
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject '{subject}' `
    -CertStoreLocation 'Cert:\\CurrentUser\\My' -HashAlgorithm SHA256 `
    -KeyLength 2048 -KeyExportPolicy Exportable -NotAfter (Get-Date).AddYears(3)
$pw = ConvertTo-SecureString -String '{password}' -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath '{pfx}' -Password $pw | Out-Null
Write-Output $cert.Thumbprint
"""
    proc = subprocess.run([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                          capture_output=True, text=True)
    if proc.returncode != 0 or not pfx.is_file():
        print(f"      自签名证书生成失败: {proc.stderr.strip()[:300]}")
        return False
    print(f"      已生成自签名证书 {pfx}（指纹 {proc.stdout.strip().splitlines()[-1]}）")
    return True


def sign(target: Path, pfx: Path | None, password: str, deep: bool = False,
         self_sign: bool = False) -> bool:
    """给产物签名。返回是否真的签上了。"""
    if platform.system() != "Windows":
        print("[5/6] 非 Windows：跳过签名（只影响 Windows SmartScreen）")
        return False
    if self_sign and (pfx is None or not pfx.is_file()):
        pfx = BUILD_DIR / "imeg-selfsign.pfx"
        password = password or "imeg"
        if not pfx.is_file():
            print("[5/6] 生成自签名证书 …")
            if not make_self_signed_pfx(pfx, password):
                return False
    if pfx is None or not pfx.is_file():
        print("[5/6] 未指定证书，跳过签名（加 --sign-self 或 --sign-pfx 证书.pfx）")
        return False

    tool = find_signtool()
    if tool is None:
        print("[5/6] 没找到 signtool.exe，跳过签名。")
        print("      装 Windows SDK（或只勾 Signing Tools）后重跑，")
        print("      或手动执行: signtool sign /f 证书.pfx /p 密码 /tr "
              "http://timestamp.digicert.com /td sha256 /fd sha256 IMEG.exe")
        return False

    targets: list[Path] = []
    if target.is_file():
        targets = [target]
    else:
        targets = [p for p in target.glob("*.exe")]
        if deep:
            targets += list((target / "_internal").rglob("*.dll")) if (target / "_internal").is_dir() \
                else list(target.rglob("*.dll"))
    if not targets:
        return False

    ok = True
    for file in targets:
        for server in ("http://timestamp.digicert.com", "http://timestamp.sectigo.com"):
            cmd = [str(tool), "sign", "/f", str(pfx), "/p", password,
                   "/fd", "SHA256", "/td", "SHA256", "/tr", server,
                   "/v", str(file)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                print(f"      已签名 {file.name}")
                break
        else:
            ok = False
            print(f"      签名失败 {file.name}")
    if ok:
        print("      提示：自签名证书不会让 SmartScreen 放行，但能消掉"
              "「未签名程序」这类启发式告警；要彻底解决请买 OV/EV 证书或走 SignPath 免费开源签名。")
    return ok


# --------------------------------------------------------------------------
def folder_size(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1024 / 1024
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024 / 1024


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="一键打包 IMEG（目标机器零依赖）")
    ap.add_argument("--onefile", action="store_true", help="打成单个 EXE（启动慢、误报率高）")
    ap.add_argument("--console", action="store_true", help="带控制台窗口（排错用）")
    ap.add_argument("--zip", action="store_true", help="再压一个便携 zip")
    ap.add_argument("--with-ocr", action="store_true", help="把 rapidocr 也打进去（大，+上百 MB）")
    ap.add_argument("--with-av", action="store_true", help="把 PyAV 打进去（scrcpy 源要用）")
    ap.add_argument("--no-adb", action="store_true", help="不内置 adb")
    ap.add_argument("--no-vcrt", action="store_true", help="不补 VC++ 运行库")
    ap.add_argument("--sign-self", action="store_true", help="生成自签名证书并签名（Windows）")
    ap.add_argument("--sign-pfx", default=None, help="用指定的 PFX 证书签名")
    ap.add_argument("--sign-password", default="", help="PFX 密码")
    ap.add_argument("--sign-deep", action="store_true", help="连内部 DLL 一起签（慢）")
    ap.add_argument("--extra", default="", help="追加给 PyInstaller 的参数")
    ap.add_argument("--dry-run", action="store_true", help="只打印命令不执行")
    args = ap.parse_args(argv)

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
        print("[3/6] 补依赖 …")
        if not args.no_adb:
            bundle_adb(dist_root if not args.onefile else DIST_DIR)
        if not args.no_vcrt:
            bundle_vcrt(dist_root if not args.onefile else DIST_DIR)
    print("[4/6] 签名 …")
    signed = False
    if not args.dry_run:
        signed = sign(exe, Path(args.sign_pfx) if args.sign_pfx else None,
                      args.sign_password, deep=args.sign_deep, self_sign=args.sign_self)

    print("[5/6] 写使用说明 …")
    if not args.dry_run:
        write_dist_readme(dist_root if not args.onefile else DIST_DIR, signed=signed)

    print("[6/6] 收尾 …")
    if args.zip and not args.dry_run:
        make_zip(dist_root, args.onefile)

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
