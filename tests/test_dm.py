"""大漠风格 API（dm 门面）+ 截图源 + 字库 OCR 的端到端测试。"""
from __future__ import annotations

import numpy as np
import pytest

from imeg.core.capture import StaticCaptureSource
from imeg.core.dm import Dm
from imeg.core.image import save_image, with_alpha
from imeg.core.inputctl import NullInputController
from imeg.core.ocr import FontLib, OcrEngine
from imeg.core.types import Rect


@pytest.fixture()
def scene(tmp_path):
    """造一张 400x300 的"手机截图"：白底 + 红方块 + 蓝方块。"""
    img = np.full((300, 400, 3), 255, np.uint8)
    img[50:110, 100:160] = (0, 0, 255)     # RGB FF0000 红块
    img[200:240, 300:340] = (255, 0, 0)    # RGB 0000FF 蓝块
    path = tmp_path / "screen.png"
    save_image(str(path), img)

    src = StaticCaptureSource(str(path))
    src.start()
    src.wait_frame(timeout=3)
    dm = Dm(source=src, input_ctrl=NullInputController(), path=str(tmp_path))
    return dm, img, tmp_path


def test_source_and_size(scene):
    dm, img, _ = scene
    assert dm.IsBind() == 1
    assert dm.GetClientSize() == (400, 300)
    assert dm.GetDeviceSize() == (400, 300)


def test_dm_colors(scene):
    dm, _, _ = scene
    assert dm.GetColor(10, 10) == "FFFFFF"
    assert dm.GetColor(120, 70) == "FF0000"
    assert dm.FindColor(0, 0, 399, 299, "FF0000-000000") == "100|50"
    assert dm.FindColor(0, 0, 399, 299, "123456-000000") == "-1|-1"
    assert dm.CmpColor(120, 70, "FF0000-101010") == 0
    assert dm.CmpColor(10, 10, "FF0000-101010") == -1
    assert dm.GetColorNum(0, 0, 399, 299, "FF0000") == 3600


def test_dm_find_pic_and_transparent(scene, tmp_path):
    dm, img, tmp_path = scene
    # 普通模板
    save_image(str(tmp_path / "red.png"), img[50:110, 100:160])
    assert dm.FindPic(0, 0, 399, 299, "red.png", "101010", 0.9, 0) == "0|100|50"
    assert dm.FindPic(0, 0, 399, 299, "notexist.png", "101010", 0.9, 0) == "-1|-1|-1"

    # 透明图模板：只保留红块中间一小块，其余透明
    tpl = img[40:120, 90:170].copy()
    alpha = np.zeros((80, 80), np.uint8)
    alpha[20:60, 20:60] = 255
    save_image(str(tmp_path / "red_alpha.png"), with_alpha(tpl, alpha))
    # 模板里只有 [20:60]x[20:60] 参与匹配（对应画面 110..149, 60..99），
    # 红块是 100..159,50..109，所以按左上→右下第一个命中位置是 (80,30)
    assert dm.FindPic(0, 0, 399, 299, "red_alpha.png", "101010", 0.9, 0) == "0|80|30"

    # 多图
    save_image(str(tmp_path / "blue.png"), img[200:240, 300:340])
    # 方向 0 = 左上→右下，红块(100,50) 比蓝块(300,200) 先命中，index 1 表示第二张模板
    assert dm.FindPic(0, 0, 399, 299, "blue.png|red.png", "101010", 0.9, 0) == "1|100|50"
    assert dm.FindPic(0, 0, 399, 299, "blue.png", "101010", 0.9, 0) == "0|300|200"
    assert dm.FindPicEx(0, 0, 399, 299, "red.png|blue.png", "101010", 0.9, 0) == "0|100|50|1|300|200"

    # 区域限制
    assert dm.FindPic(0, 0, 200, 150, "blue.png", "101010", 0.9, 0) == "-1|-1|-1"


def test_dm_multicolor(scene):
    dm, _, _ = scene
    assert dm.FindMultiColor(0, 0, 399, 299, "FF0000", "5|5|FF0000,30|30|FF0000", 1.0, 0) == "100|50"
    assert dm.FindMultiColor(0, 0, 399, 299, "FF0000", "5|5|00FF00", 1.0, 0) == "-1|-1"


def test_dm_capture_and_screendata(scene, tmp_path):
    dm, _, _ = scene
    assert dm.Capture(100, 50, 159, 109, str(tmp_path / "out.png")) == 1
    from imeg.core.image import load_image
    assert load_image(str(tmp_path / "out.png")).shape == (60, 60, 3)

    data = dm.GetScreenData(0, 0, 20, 20)
    assert data.startswith("iVBOR")  # PNG base64 头
    import base64
    raw = base64.b64decode(data)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert dm.GetScreenDataBmp()[:2] == "Qk"  # "BM" 的 base64 前缀


def test_dm_input_null(scene):
    dm, _, _ = scene
    assert dm.LeftClick(10, 20) == 1
    assert dm.KeyPressStr("HOME") == 1
    assert dm.SendString("abc") == 1
    assert dm.Swipe(0, 0, 100, 100, 200) == 1
    log = dm.input.log
    assert any("click 10,20" in line for line in log)
    assert any("key HOME" in line for line in log)


def test_fontlib_ocr(tmp_path):
    """字库 OCR：用 cv2 渲染的字符当字库，再识别同字体写出来的文字。"""
    import cv2

    def render(text: str, size: int = 40) -> np.ndarray:
        img = np.zeros((size * 2, size * 2, 3), np.uint8)
        cv2.putText(img, text, (int(size * 0.4), int(size * 1.3)),
                    cv2.FONT_HERSHEY_SIMPLEX, size / 30.0, (255, 255, 255), 3, cv2.LINE_AA)
        return img

    dict_dir = tmp_path / "fontlib"
    lib = FontLib(str(dict_dir))
    for ch in "AB":
        glyph = render(ch)
        lib.add(ch, glyph, thresh=1)
    assert lib.reload() == 2

    engine = OcrEngine(backend="fontlib", dict_dir=str(dict_dir))
    assert engine.current.name == "fontlib"

    target = render("AB")
    results = engine.recognize(target, color="FFFFFF-000000")
    text = "".join(r.text for r in results)
    assert text == "AB", f"识别结果 {text} / 结果数 {len(results)}"

    # 大漠风格输出
    dm = Dm(source=StaticCaptureSource(str(_save(target, tmp_path))), path=str(tmp_path))
    dm.ocr = engine
    out = dm.Ocr(0, 0, 79, 79, "FFFFFF-000000", 0.9)
    fields = out.split("|")
    assert [fields[i + 2] for i in range(0, len(fields), 3)] == ["A", "B"]
    assert dm.FindStr(0, 0, 79, 79, "AB", "FFFFFF-000000", 0.9) != "-1|-1|-1"


def _save(img: np.ndarray, tmp_path) -> str:
    p = tmp_path / "ocr_target.png"
    save_image(str(p), img)
    return str(p)
