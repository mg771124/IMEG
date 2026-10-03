"""无界面用法示例：连 ADB → 后台截图 → 找图 → 点击。

    python examples/dm_script.py [serial]

不需要启动图形界面，适合直接写成挂机脚本。
"""
from __future__ import annotations

import sys
import time

from imeg.core.dm import Dm

SERIAL = sys.argv[1] if len(sys.argv) > 1 else None


def main() -> int:
    dm = Dm(path="./pic")                       # 模板目录
    if not dm.BindDevice(serial=SERIAL, kind="adb", fps=5, raw=True):
        print("绑定设备失败:", dm.last_error)
        print("提示：adb devices 看看有没有设备；无线设备用 adb connect IP:5555")
        return 1

    print("绑定成功:", dm.GetBindInfo())
    w, h = dm.GetClientSize()
    print(f"画面 {w}x{h}   设备解析度 {dm.GetDeviceSize()}")

    # 后台截图（不需要窗口在前台）
    dm.Capture(0, 0, w - 1, h - 1, "screen.png")

    # 找图：透明图模板会自动忽略透明区
    ret = dm.FindPic(0, 0, w - 1, h - 1, "button.png", "101010", 0.9, 0)
    print("FindPic:", ret)
    if ret != "-1|-1|-1":
        _, x, y = ret.split("|")
        dm.LeftClick(int(x) + 10, int(y) + 10)          # 后台点击（adb input tap）

    # 找色 / 多点找色
    print("FindColor:", dm.FindColor(0, 0, w - 1, h - 1, "FFFFFF-101010"))
    print("FindMultiColor:",
          dm.FindMultiColor(0, 0, w - 1, h - 1, "FF0000", "5|5|FF0000,10|10|00FF00", 1.0, 0))

    # 键鼠
    dm.KeyPressStr("BACK")
    dm.SendString("hello")
    dm.Swipe(w // 2, h * 3 // 4, w // 2, h // 4, 400)    # 上滑

    # 循环等待某个图出现
    for i in range(30):
        if dm.FindPic(0, 0, w - 1, h - 1, "popup.png", "101010", 0.85, 0) != "-1|-1|-1":
            print("弹窗出现了")
            break
        time.sleep(0.5)

    dm.UnBindWindow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
