"""右侧功能面板。"""
from __future__ import annotations

__all__ = [
    "DevicePanel", "FindPicPanel", "ColorPanel", "TransparentPanel",
    "InputPanel", "OcrPanel", "ScriptPanel",
]

from .color_panel import ColorPanel
from .device_panel import DevicePanel
from .findpic_panel import FindPicPanel
from .input_panel import InputPanel
from .ocr_panel import OcrPanel
from .script_panel import ScriptPanel
from .transparent_panel import TransparentPanel
