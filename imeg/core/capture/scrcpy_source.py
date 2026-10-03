"""scrcpy 截图源：设备端编码 H.264 推流，**低延迟、高帧率**，解析度就是设备真实解析度。

需要两样东西（都不是 Python 依赖里能自动装好的）:

1. ``scrcpy-server.jar`` —— 用 ``python -m imeg.tools.fetch_scrcpy_server`` 下载，
   或自己放到 ``~/.imeg/scrcpy-server.jar`` / ``vendor/scrcpy-server.jar``
2. ``pip install av``（PyAV，内置 ffmpeg，用来解码 H.264）

协议实现对应 scrcpy 2.x / 3.x::

    adb forward tcp:PORT localabstract:scrcpy
    shell CLASSPATH=/data/local/tmp/scrcpy-server.jar app_process / \\
         com.genymobile.scrcpy.Server <版本> scid=-1 tunnel_forward=true ...
    连接后: 1 字节 dummy + 64 字节设备名 + 12 字节(codecId,width,height)
    之后每帧: 8 字节 pts + 4 字节长度 + H.264 数据

注意：**客户端传的版本号必须和服务端 jar 完全一致**，否则服务端会直接拒绝启动。
本模块会自动从 jar 里读出版本号。
"""
from __future__ import annotations

import os
import re
import socket
import struct
import subprocess
import time
import zipfile
from pathlib import Path

import numpy as np

from ..adb import AdbClient
from ..types import Frame
from .base import CaptureSource

__all__ = ["ScrcpyCaptureSource", "find_server_jar", "server_version", "SERVER_JAR_CANDIDATES"]

SERVER_JAR_CANDIDATES = [
    Path(os.environ.get("IMEG_SCRCPY_SERVER", "")) if os.environ.get("IMEG_SCRCPY_SERVER") else None,
    Path.home() / ".imeg" / "scrcpy-server.jar",
    Path(__file__).resolve().parents[2] / "vendor" / "scrcpy-server.jar",
    Path.cwd() / "scrcpy-server.jar",
]
DEVICE_NAME_LEN = 64
PACKET_FLAG_CONFIG = 1 << 63      # 2.x/3.x：配置包（带负载）
PACKET_FLAG_KEY_FRAME = 1 << 62   # 2.x/3.x：关键帧
PACKET_FLAG_SESSION = 1 << 63     # 4.x：会话信息包（无负载，宽高藏在包头里）
PACKET_FLAG_CONFIG_V4 = 1 << 62
PACKET_FLAG_KEY_FRAME_V4 = 1 << 61


def major_version(version: str) -> int:
    """"3.3.1" -> 3"""
    try:
        return int(str(version).split(".")[0])
    except (ValueError, IndexError):
        return 2


def find_server_jar(explicit: str | None = None) -> str | None:
    """找 scrcpy-server.jar。"""
    if explicit:
        p = Path(explicit)
        return str(p) if p.is_file() else None
    for cand in SERVER_JAR_CANDIDATES:
        if cand and Path(cand).is_file():
            return str(Path(cand))
    return None


def server_version(jar_path: str) -> str | None:
    """读出 jar 自带的版本号（优先读同名 .json，其次从 BuildConfig.class 里抠）。"""
    if not jar_path:
        return None
    jar = Path(jar_path)
    sidecar = jar.with_suffix(".json")
    if sidecar.is_file():
        try:
            import json
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("version"):
                return str(data["version"])
        except Exception:
            pass
    try:
        with zipfile.ZipFile(jar) as zf:
            names = [n for n in zf.namelist() if n.endswith("BuildConfig.class")]
            for name in names:
                blob = zf.read(name)
                texts = re.findall(rb"[\x20-\x7e]{4,}", blob)
                for t in texts:
                    s = t.decode("ascii", "ignore")
                    m = re.fullmatch(r"(\d+\.\d+(?:\.\d+)?)", s)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return None


class _H264Decoder:
    """PyAV 解码器包装。"""

    def __init__(self, codec_name: str = "h264") -> None:
        try:
            import av  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "scrcpy 源需要 PyAV 解码 H.264：pip install av"
            ) from exc
        self.av = av
        self.codec = av.CodecContext.create(codec_name, "r")

    def decode(self, data: bytes) -> list[np.ndarray]:
        packet = self.av.Packet(data)
        out: list[np.ndarray] = []
        try:
            frames = self.codec.decode(packet)
        except Exception:
            return out
        for frame in frames:
            try:
                out.append(frame.to_ndarray(format="bgr24"))
            except Exception:
                continue
        return out


class ScrcpyCaptureSource(CaptureSource):
    """用 scrcpy 投屏流抓帧。"""

    name = "scrcpy"

    def __init__(self, serial: str | None = None, adb: AdbClient | None = None,
                 server_jar: str | None = None, fps: float = 30.0,
                 max_size: int = 0, bit_rate: int = 8_000_000, display_id: int = 0,
                 codec: str = "h264", server_version_override: str | None = None,
                 extra_args: str = "", device_port: int = 0) -> None:
        super().__init__(fps=fps)
        self.adb = adb or AdbClient()
        self.serial = serial or self._auto_serial()
        self.server_jar = server_jar
        self.max_size = int(max_size)
        self.bit_rate = int(bit_rate)
        self.display_id = int(display_id)
        self.codec = codec
        self.version_override = server_version_override
        self.extra_args = extra_args.strip()
        self.device_port = int(device_port)

        self._sock: socket.socket | None = None
        self._proc: subprocess.Popen | None = None
        self._decoder: _H264Decoder | None = None
        self.device_name = ""
        self._local_port = 0
        self.major = 2
        self._width = 0
        self._height = 0
        self.codec_id = 0

    def _auto_serial(self) -> str | None:
        try:
            devs = [d for d in self.adb.devices() if d.is_online]
        except Exception:
            return None
        return devs[0].serial if devs else None

    # ---------------------------------------------------------------- 启动
    def _server_args(self, version: str) -> list[str]:
        self.major = major_version(version)
        args = [
            version,
            "scid=-1",                       # 用默认的 "scrcpy" 抽象套接字名
            "log_level=warn",
            "video=true",
            "audio=false",
            f"video_codec={self.codec}",
            f"max_size={self.max_size}",
            f"video_bit_rate={self.bit_rate}",
            f"max_fps={int(self.fps_target)}",
            "tunnel_forward=true",           # 服务端监听，客户端连
            "control=false",                 # 控制走 adb input，不占 socket
            f"display_id={self.display_id}",
            "show_touches=false",
            "stay_awake=false",
            "downsize_on_error=true",
            "cleanup=true",
            "power_on=true",
            "send_device_meta=true",
            "send_frame_meta=true",
            "send_dummy_byte=true",
        ]
        # 4.x 用 send_stream_meta，且视频头只有 4 字节（宽高走会话信息包）
        args.append("send_stream_meta=true" if self.major >= 4 else "send_codec_meta=true")
        if self.extra_args:
            args += self.extra_args.split()
        return args

    def open(self) -> None:
        jar = find_server_jar(self.server_jar)
        if not jar:
            raise RuntimeError(
                "没找到 scrcpy-server.jar。执行 `python -m imeg.tools.fetch_scrcpy_server` 下载，"
                "或把它放到 ~/.imeg/scrcpy-server.jar，或用 server_jar= 指定路径"
            )
        version = self.version_override or server_version(jar)
        if not version:
            raise RuntimeError(f"无法从 {jar} 读出版本号，请用 server_version_override= 手工指定")
        if not self.serial:
            raise RuntimeError("没有可用设备")

        remote = "/data/local/tmp/scrcpy-server.jar"
        self.adb.push(jar, remote, serial=self.serial, timeout=60)

        self._local_port = self.device_port or _free_port()
        self.adb.forward(f"tcp:{self._local_port}", "localabstract:scrcpy", serial=self.serial)

        cmd = [
            self.adb.exe, "-s", self.serial, "shell",
            f"CLASSPATH={remote} app_process / com.genymobile.scrcpy.Server "
            + " ".join(self._server_args(version)),
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        # 连 socket（服务端启动要几百毫秒，重试若干次）
        sock = None
        deadline = time.time() + 12.0
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", self._local_port), timeout=3.0)
                s.settimeout(5.0)
                sock = s
                break
            except OSError as exc:
                last_err = exc
                time.sleep(0.3)
        if sock is None:
            self._cleanup()
            raise RuntimeError(f"连接 scrcpy 服务端失败: {last_err}")
        self._sock = sock

        sock.recv(1)  # dummy byte
        self.device_name = sock.recv(DEVICE_NAME_LEN).rstrip(b"\x00").decode("utf-8", "replace")
        if self.major >= 4:
            # v4：只有 4 字节 codecId，宽高要等第一个"会话信息包"
            self.codec_id = struct.unpack(">i", self._recv_exact(4))[0]
            self._width = self._height = 0
        else:
            self.codec_id, self._width, self._height = struct.unpack(">iii", self._recv_exact(12))
        self._decoder = _H264Decoder(self.codec)

    def _recv_exact(self, n: int) -> bytes:
        assert self._sock is not None
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("scrcpy 连接已断开")
            buf += chunk
        return bytes(buf)

    # ---------------------------------------------------------------- 抓帧
    def grab(self) -> Frame:
        if self._sock is None or self._decoder is None:
            raise RuntimeError("scrcpy 未启动")
        while True:
            header = self._recv_exact(12)
            pts_flags, size = struct.unpack(">qI", header)
            if self.major >= 4 and (pts_flags & PACKET_FLAG_SESSION):
                # v4 的会话信息包：宽高就在包头里，没有负载
                self._width = pts_flags & 0xFFFFFFFF
                self._height = size
                continue
            if size <= 0 or size > 32 * 1024 * 1024:
                raise ConnectionError(f"异常的包大小: {size}")
            data = self._recv_exact(size)
            frames = self._decoder.decode(data)
            if frames:
                img = frames[-1]
                return Frame.from_image(
                    img, source=self.name,
                    meta={"serial": self.serial, "device_name": self.device_name,
                          "config": bool(pts_flags & PACKET_FLAG_CONFIG),
                          "key_frame": bool(pts_flags & PACKET_FLAG_KEY_FRAME)},
                )
            # 还没解出图像就继续读下一个包（SPS/PPS 之类的配置包）

    def device_size(self) -> tuple[int, int] | None:
        if self._width and self._height:
            return self._width, self._height
        return None

    # ---------------------------------------------------------------- 关闭
    def _cleanup(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        if self._local_port:
            try:
                self.adb.forward_remove(f"tcp:{self._local_port}", serial=self.serial)
            except Exception:
                pass
        try:
            self.adb.shell("pkill -f com.genymobile.scrcpy.Server", serial=self.serial, check=False)
        except Exception:
            pass

    def close(self) -> None:
        self._cleanup()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScrcpyCaptureSource serial={self.serial} {self._width}x{self._height}>"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port
