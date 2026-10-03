"""截图源工厂：按名字/配置创建 ADB / 窗口 / scrcpy / 静态图 源。"""
from __future__ import annotations

from ..adb import AdbClient

SOURCE_LABELS = {
    "adb": "ADB 截图（后台 / 真实解析度）",
    "window": "模拟器窗口捕获（不连 ADB）",
    "scrcpy": "scrcpy 投屏流（低延迟）",
    "static": "本地图片（离线做模板）",
}


def available_sources() -> dict[str, bool]:
    """各源在当前平台的可用性。"""
    from . import window_source
    return {
        "adb": True,
        "window": window_source.WINDOWS_OS,
        "scrcpy": True,
        "static": True,
    }


def create_source(kind: str, **kw):
    """创建截图源。

    :param kind: ``adb`` / ``window`` / ``scrcpy`` / ``static``
    :param kw:   透传给对应源的参数（serial / hwnd / fps / server_jar / path ...）
    """
    kind = (kind or "adb").lower()
    adb = kw.pop("adb", None) or AdbClient()

    if kind == "adb":
        from .adb_source import ADBCaptureSource
        return ADBCaptureSource(adb=adb, **kw)
    if kind == "window":
        from .window_source import WindowCaptureSource
        return WindowCaptureSource(adb=adb, **kw)
    if kind == "scrcpy":
        from .scrcpy_source import ScrcpyCaptureSource
        return ScrcpyCaptureSource(adb=adb, **kw)
    if kind == "static":
        from .base import StaticCaptureSource
        return StaticCaptureSource(**kw)
    raise ValueError(f"未知截图源: {kind}（可选 {', '.join(SOURCE_LABELS)}）")
