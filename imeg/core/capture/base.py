"""截图源抽象：ADB / 窗口捕获 / scrcpy / 静态图片 统一接口。"""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..types import Frame

__all__ = ["CaptureSource", "PollingCaptureSource", "StaticCaptureSource", "SourceStats"]


@dataclass
class SourceStats:
    frames: int = 0
    errors: int = 0
    fps: float = 0.0
    last_cost_ms: float = 0.0
    last_error: str = ""
    started_at: float = 0.0


class CaptureSource(ABC):
    """所有截图源的基类：线程安全，后台线程持续抓帧。"""

    name = "base"

    def __init__(self, fps: float = 10.0) -> None:
        self.fps_target = max(0.5, float(fps))
        self.stats = SourceStats()
        self._frame: Frame | None = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paused = threading.Event()

    # ------------------------------------------------------------ 需要实现
    @abstractmethod
    def grab(self) -> Frame:
        """同步抓一帧。失败时抛异常。"""

    def device_size(self) -> tuple[int, int] | None:
        """设备的"实际解析度"（与抓到的帧尺寸可能不同，比如窗口源缩放过）。"""
        return None

    def open(self) -> None:  # 可选：打开前的准备工作
        pass

    def close(self) -> None:  # 可选：释放资源
        pass

    # ------------------------------------------------------------ 生命周期
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._paused.clear()
        try:
            self.open()
        except Exception as exc:
            raise RuntimeError(f"{self.name} 打开失败: {exc}") from exc
        self.stats.started_at = time.time()
        self._thread = threading.Thread(target=self._loop, name=f"capture-{self.name}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        try:
            self.close()
        except Exception:
            pass

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    # ------------------------------------------------------------ 取帧
    def frame(self) -> Frame | None:
        with self._lock:
            return self._frame

    def image(self) -> np.ndarray | None:
        f = self.frame()
        return None if f is None else f.image

    def size(self) -> tuple[int, int]:
        f = self.frame()
        if f is not None:
            return f.width, f.height
        return self.device_size() or (0, 0)

    def wait_frame(self, timeout: float = 5.0) -> Frame | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            f = self.frame()
            if f is not None:
                return f
            time.sleep(0.02)
        return None

    # ------------------------------------------------------------ 线程体
    def _loop(self) -> None:
        interval = 1.0 / self.fps_target
        seq = 0
        last = 0.0
        while not self._stop.is_set():
            if self._paused.is_set():
                time.sleep(0.05)
                continue
            t0 = time.time()
            try:
                frame = self.grab()
                seq += 1
                frame.seq = seq
                frame.source = self.name
                frame.timestamp = time.time()
                with self._lock:
                    self._frame = frame
                self.stats.frames += 1
                self.stats.last_error = ""
                if last:
                    dt = t0 - last
                    if dt > 0:
                        self.stats.fps = self.stats.fps * 0.8 + (1.0 / dt) * 0.2
            except Exception as exc:
                self.stats.errors += 1
                self.stats.last_error = str(exc)
            self.stats.last_cost_ms = (time.time() - t0) * 1000.0
            last = t0
            sleep = interval - (time.time() - t0)
            if sleep > 0:
                self._stop.wait(sleep)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


#: 轮询抓帧的别名（保持语义清晰：所有源都是后台线程轮询）
PollingCaptureSource = CaptureSource


class StaticCaptureSource(CaptureSource):
    """读一张本地图片当"画面"，用来离线做模板/透明图（无设备也能用）。"""

    name = "static"

    def __init__(self, path: str, fps: float = 5.0) -> None:
        super().__init__(fps=fps)
        from ..image import load_image
        self.path = path
        self._img = load_image(path)
        self._frame = Frame.from_image(self._img, source=self.name)

    def grab(self) -> Frame:
        return Frame.from_image(self._img, source=self.name)

    def device_size(self):
        return self._frame.width, self._frame.height
