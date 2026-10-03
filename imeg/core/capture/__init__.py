"""截图源：ADB / 模拟器窗口 / scrcpy / 静态图片。"""
from __future__ import annotations

from .base import CaptureSource, PollingCaptureSource, StaticCaptureSource
from .adb_source import ADBCaptureSource
from .window_source import WindowCaptureSource, list_windows, WINDOWS_OS
from .scrcpy_source import ScrcpyCaptureSource
from .factory import create_source, available_sources, SOURCE_LABELS

__all__ = [
    "CaptureSource", "PollingCaptureSource", "StaticCaptureSource",
    "ADBCaptureSource", "WindowCaptureSource", "ScrcpyCaptureSource",
    "list_windows", "create_source", "available_sources", "SOURCE_LABELS", "WINDOWS_OS",
]
