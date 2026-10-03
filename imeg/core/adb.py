"""ADB 客户端：设备枚举、无线连接、**后台截图**、真实解析度、输入注入。

ADB 截图天然就是"后台截图"：不需要窗口在最前台、不需要窗口可见，
只要 SurfaceFlinger 能出图（非 DRM/安全页面）就能拿到画面。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise ImportError("需要 OpenCV: pip install opencv-python-headless") from exc

__all__ = ["AdbError", "Device", "AdbClient", "KEY"]


class AdbError(RuntimeError):
    """ADB 命令执行失败。"""


#: 常用 Android keyevent（大漠 KeyPress 的按键名）
KEY: dict[str, int] = {
    "HOME": 3, "BACK": 4, "MENU": 82, "APP_SWITCH": 187, "POWER": 26,
    "VOLUME_UP": 24, "VOLUME_DOWN": 25, "MUTE": 164,
    "ENTER": 66, "DEL": 67, "BACKSPACE": 67, "ESCAPE": 111, "TAB": 61,
    "SPACE": 62, "DPAD_UP": 19, "DPAD_DOWN": 20, "DPAD_LEFT": 21, "DPAD_RIGHT": 22,
    "CAMERA": 27, "SEARCH": 84, "BRIGHTNESS_DOWN": 220, "BRIGHTNESS_UP": 221,
}
for _i in range(10):
    KEY[str(_i)] = 7 + _i
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    KEY[_c.upper()] = 29 + _i


@dataclass
class Device:
    serial: str
    state: str = "unknown"
    model: str = ""
    product: str = ""
    device: str = ""
    transport_id: str = ""

    def __str__(self) -> str:
        label = self.model or self.product or self.serial
        return f"{label} ({self.serial})" if label != self.serial else self.serial

    @property
    def is_online(self) -> bool:
        return self.state in ("device", "recovery", "sideload")


def _find_adb(adb_path: str | None = None) -> str:
    candidates = []
    if adb_path:
        candidates.append(adb_path)
    env = os.environ.get("ADB") or os.environ.get("ANDROID_ADB")
    if env:
        candidates.append(env)
    if os.environ.get("ANDROID_HOME"):
        candidates.append(str(Path(os.environ["ANDROID_HOME"]) / "platform-tools" / "adb"))
    if os.environ.get("ANDROID_SDK_ROOT"):
        candidates.append(str(Path(os.environ["ANDROID_SDK_ROOT"]) / "platform-tools" / "adb"))
    # Packaged builds keep platform-tools beside IMEG.exe. In onedir mode __file__
    # points into PyInstaller's _internal directory, so don't rely on it for this path.
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        candidates.append(str(app_dir / "tools" / "platform-tools" / "adb"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(str(Path(meipass) / "tools" / "platform-tools" / "adb"))
    candidates.append(str(Path(__file__).resolve().parents[2] / "tools" / "platform-tools" / "adb"))
    candidates.append("adb")
    for c in candidates:
        if not c:
            continue
        p = Path(c)
        if p.is_file() and os.access(str(p), os.X_OK):
            return str(p)
        if os.name == "nt" and p.with_suffix(".exe").is_file():
            return str(p.with_suffix(".exe"))
        found = shutil.which(c)
        if found:
            return found
    return candidates[-1]


@dataclass
class AdbClient:
    """轻量 ADB 封装（只用 subprocess 调 adb，不依赖第三方库）。"""

    adb_path: str | None = None
    host: str = "127.0.0.1"
    port: int = 5037
    timeout: float = 15.0
    _exe: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self._exe = _find_adb(self.adb_path)

    @property
    def exe(self) -> str:
        return self._exe

    # ---------------------------------------------------------------- 基础执行
    def _base_cmd(self) -> list[str]:
        return [self._exe]

    def run(self, args: list[str], timeout: float | None = None, check: bool = True) -> str:
        cmd = self._base_cmd() + [str(a) for a in args]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout or self.timeout)
        except FileNotFoundError as exc:
            raise AdbError(f"找不到 adb: {self._exe}（把 adb 放进 PATH，或设置环境变量 ADB）") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb 超时: {' '.join(cmd)}") from exc
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        if check and proc.returncode != 0:
            raise AdbError(f"adb 失败: {' '.join(cmd)}\n{err.strip() or out.strip()}")
        return out

    def run_bytes(self, args: list[str], timeout: float | None = None) -> bytes:
        cmd = self._base_cmd() + [str(a) for a in args]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout or self.timeout)
        except FileNotFoundError as exc:
            raise AdbError(f"找不到 adb: {self._exe}") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdbError(f"adb 超时: {' '.join(cmd)}") from exc
        if proc.returncode != 0:
            raise AdbError(f"adb 失败: {' '.join(cmd)}\n{proc.stderr.decode('utf-8', 'replace').strip()}")
        return proc.stdout

    def version(self) -> str:
        return self.run(["version"]).strip().splitlines()[0]

    # ---------------------------------------------------------------- 设备
    def devices(self) -> list[Device]:
        out = self.run(["devices", "-l"], timeout=10, check=False)
        result: list[Device] = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial, state = parts[0], parts[1]
            info = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            result.append(Device(
                serial=serial, state=state,
                model=info.get("model", ""), product=info.get("product", ""),
                device=info.get("device", ""), transport_id=info.get("transport_id", ""),
            ))
        return result

    def connect(self, addr: str) -> str:
        """无线连接 ``192.168.1.8:5555``（Android 11+ 需先走配对）。"""
        out = self.run(["connect", addr], timeout=20, check=False).strip()
        if "connected" not in out and "already" not in out:
            raise AdbError(f"连接 {addr} 失败: {out}")
        return out

    def disconnect(self, addr: str) -> str:
        return self.run(["disconnect", addr], timeout=10, check=False).strip()

    def _serial_args(self, serial: str | None) -> list[str]:
        return ["-s", serial] if serial else []

    def shell(self, cmd: str, serial: str | None = None, timeout: float | None = None,
              check: bool = True) -> str:
        return self.run(self._serial_args(serial) + ["shell", cmd], timeout=timeout, check=check)

    def shell_bytes(self, cmd: str, serial: str | None = None, timeout: float | None = None) -> bytes:
        args = self._serial_args(serial) + ["shell"] + cmd.split()
        return self.run_bytes(args, timeout=timeout)

    def push(self, local: str, remote: str, serial: str | None = None, timeout: float | None = None) -> None:
        self.run(self._serial_args(serial) + ["push", local, remote], timeout=timeout or 60)

    def forward(self, local: str, remote: str, serial: str | None = None) -> None:
        self.run(self._serial_args(serial) + ["forward", local, remote], timeout=10)

    def forward_remove(self, local: str, serial: str | None = None) -> None:
        self.run(self._serial_args(serial) + ["forward", "--remove", local], timeout=10, check=False)

    def tcpip(self, port: int = 5555, serial: str | None = None) -> str:
        return self.shell(f"tcpip {int(port)}", serial=serial, timeout=20, check=False).strip()

    # ---------------------------------------------------------------- 截图
    @staticmethod
    def _decode_png(data: bytes) -> np.ndarray:
        if not data:
            raise AdbError("截图数据为空")
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
        if img is None:
            raise AdbError("PNG 解码失败（数据被破坏）")
        if img.ndim == 2:
            return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    def screencap(self, serial: str | None = None, display: int | None = None,
                  timeout: float | None = None) -> np.ndarray:
        """后台截图 → BGR 图（设备真实解析度）。

        优先 ``exec-out screencap -p``（原样输出，不会把 \\n 变成 \\r\\n），
        失败时退化到 ``shell screencap -p`` 并修正 CRLF。
        """
        cmd = ["screencap", "-p"]
        if display is not None:
            cmd += ["-d", str(int(display))]
        args = self._serial_args(serial) + ["exec-out"] + cmd
        try:
            data = self.run_bytes(args, timeout=timeout or self.timeout)
            return self._decode_png(data)
        except AdbError:
            data = self.shell_bytes(" ".join(cmd), serial=serial, timeout=timeout)
            return self._decode_png(data.replace(b"\r\n", b"\n"))

    def screencap_raw(self, serial: str | None = None, display: int | None = None) -> np.ndarray:
        """用原始 RGBA 快速截图（``screencap`` 不带 -p），比 PNG 快不少。"""
        cmd = ["screencap"]
        if display is not None:
            cmd += ["-d", str(int(display))]
        data = self.shell_bytes(" ".join(cmd), serial=serial, timeout=self.timeout)
        if len(data) < 12:
            raise AdbError("raw 截图数据不足")
        w, h = int.from_bytes(data[0:4], "little"), int.from_bytes(data[4:8], "little")
        fmt = int.from_bytes(data[8:12], "little")
        payload = data[12:]
        need = w * h * 4
        if len(payload) < need:
            raise AdbError(f"raw 截图数据不足: {len(payload)} < {need}")
        rgba = np.frombuffer(payload[:need], np.uint8).reshape(h, w, 4)
        if fmt == 1:  # RGBA
            return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        if fmt == 2:  # RGBX / RGB565?
            return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(rgba, cv2.COLOR_BGRA2BGR)

    # ---------------------------------------------------------------- 分辨率
    def wm_size(self, serial: str | None = None) -> tuple[int, int] | None:
        """当前逻辑分辨率（``wm size``）。"""
        out = self.shell("wm size", serial=serial, check=False)
        m = re.search(r"(?:Physical size|Override size):\s*(\d+)x(\d+)", out)
        if m:
            return int(m.group(1)), int(m.group(2))
        m = re.search(r"(\d+)x(\d+)", out)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def wm_density(self, serial: str | None = None) -> int | None:
        out = self.shell("wm density", serial=serial, check=False)
        m = re.search(r"(\d+)", out)
        return int(m.group(1)) if m else None

    def physical_size(self, serial: str | None = None) -> tuple[int, int] | None:
        """屏幕物理分辨率。"""
        for cmd in ("dumpsys display | grep -m1 'mBaseDisplayInfo'",
                    "dumpsys display | grep -m1 'real'",
                    "getprop ro.boot.hardware.display",
                    "cat /sys/class/graphics/fb0/virtual_size"):
            out = self.shell(cmd, serial=serial, check=False)
            m = re.search(r"(\d{3,5})x(\d{3,5})", out)
            if m:
                return int(m.group(1)), int(m.group(2))
        return None

    def rotation(self, serial: str | None = None) -> int:
        """屏幕旋转 0/1/2/3（分别对应 0°/90°/180°/270°）。"""
        out = self.shell("settings get system user_rotation", serial=serial, check=False).strip()
        if out.isdigit():
            return int(out)
        out = self.shell("dumpsys input | grep -m1 SurfaceOrientation", serial=serial, check=False)
        m = re.search(r"SurfaceOrientation:\s*(\d)", out)
        return int(m.group(1)) if m else 0

    def resolution_info(self, serial: str | None = None) -> dict:
        """一次拿全：截图分辨率 / 逻辑分辨率 / 物理分辨率 / DPI / 旋转。"""
        info: dict = {"serial": serial}
        try:
            img = self.screencap(serial=serial)
            info["capture_size"] = (img.shape[1], img.shape[0])
        except Exception as exc:  # pragma: no cover
            info["capture_error"] = str(exc)
        info["wm_size"] = self.wm_size(serial)
        info["physical_size"] = self.physical_size(serial)
        info["density"] = self.wm_density(serial)
        info["rotation"] = self.rotation(serial)
        return info

    # ---------------------------------------------------------------- 输入
    def tap(self, x: int, y: int, serial: str | None = None) -> None:
        self.shell(f"input tap {int(x)} {int(y)}", serial=serial, timeout=10)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300,
              serial: str | None = None) -> None:
        self.shell(f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
                   serial=serial, timeout=max(10, duration_ms / 1000 + 10))

    def long_press(self, x: int, y: int, duration_ms: int = 1000, serial: str | None = None) -> None:
        self.swipe(x, y, x, y, duration_ms, serial=serial)

    def keyevent(self, key: int | str, serial: str | None = None) -> None:
        code = KEY.get(str(key).upper(), key if isinstance(key, int) else None)
        if code is None:
            raise AdbError(f"未知按键: {key}")
        self.shell(f"input keyevent {int(code)}", serial=serial, timeout=10)

    def text(self, text: str, serial: str | None = None) -> None:
        """输入文本（ADB 的 input text，空格与特殊字符需转义）。"""
        esc = (str(text).replace("\\", "\\\\").replace(" ", "%s")
               .replace("'", "\\'").replace('"', '\\"')
               .replace("&", "\\&").replace("|", "\\|").replace(";", "\\;")
               .replace("<", "\\<").replace(">", "\\>").replace("(", "\\(")
               .replace(")", "\\)").replace("$", "\\$").replace("`", "\\`"))
        self.shell(f"input text '{esc}'", serial=serial, timeout=10)

    def is_screen_on(self, serial: str | None = None) -> bool:
        out = self.shell("dumpsys power | grep -m1 'mWakefulness'", serial=serial, check=False)
        return "Awake" in out
