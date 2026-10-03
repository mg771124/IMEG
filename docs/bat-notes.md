# 批次檔（.bat）編碼規範

> 一句話：**本專案的 .bat 一律是純 ASCII（英文訊息），存成 ANSI，不要存成 UTF-8。**

## 為什麼不用 UTF-8

`cmd.exe` 不是用「檔案內容」去判斷編碼的，它是用**目前主控台的字碼頁**去解讀 .bat
裡的位元組：

| 系統 | 主控台字碼頁 | 檔案該存的編碼 |
|---|---|---|
| 繁體中文 Windows | 950（Big5） | ANSI / Big5 |
| 簡體中文 Windows | 936（GBK） | ANSI / GBK |
| 英文 Windows | 437 / 850 | ASCII |

把 .bat 存成 UTF-8，在繁中 Windows 上每一個中文字都會被拆成兩個 Big5 字，
畫面就是一片亂碼 —— 這就是「bat 裡的中文顯示不出來」最常見的原因。
（加 `chcp 65001` 可以救，但要在檔頭先切字碼頁，且每個用這支 bat 的人都要對，
很容易一個人存檔就全毀。）

## 那為什麼連 Big5 中文也不用

因為 Big5 有惡名昭彰的**「許功蓋」問題**：部分常用字的第二個 byte 剛好是
`0x5C`（反斜線 `\`）或 `0x7C`（管線 `|`），cmd.exe 會把它當成指令的一部分，
整行指令被切斷。最常踩到的就是：

| 字 | Big5 編碼 | 第二個 byte |
|---|---|---|
| 功 | A5 5C | `\` |
| 會 | B7 7C | `\|` |
| 許 | B3 5C | `\` |
| 蓋 | B8 5C | `\` |

`echo 安裝成功` 這種話，在 Big5 底下就是不定時炸彈。所以：

* `.bat` 本體 → **純 ASCII**，訊息寫英文
* 程式自己印出來的中文（Python 端）→ 照常，那是 stdout，跟 .bat 檔案編碼無關

## 怎麼改這些 .bat

**不要直接用記事本開 .bat 來改**，一按存檔很容易變成 UTF-8。
流程是：

1. 改 `tools/make_bat.py` 裡的文字（它是 UTF-8，可以放心寫）
2. 重新產生：

```bash
python tools/make_bat.py           # 重新寫出所有 .bat
python tools/make_bat.py --check   # 只檢查現有檔案的編碼
```

3. 跑測試確認沒跑掉：

```bash
python -m pytest tests/test_bats.py -q
```

產生器會強制擋下任何非 ASCII 位元組，測試也會比對「檔案內容 == 產生器輸出」，
直接被偷改成 UTF-8 會測試失敗。

## 檔案清單

| 檔案 | 用途 |
|---|---|
| `menu.bat` | 主選單（安裝 / 啟動 / 打包 / 測試 / 開資料夾） |
| `install.bat` | 建立 `.venv`、裝 requirements，可選 OCR 與 av |
| `start.bat` | 啟動圖形介面（`python -m imeg`） |
| `build.bat` | 打包 EXE（`python -m imeg.tools.build_exe`，可帶參數） |
| `test.bat` | 跑 pytest |

## 真的一定要中文訊息怎麼辦

如果哪天 .bat 裡非得顯示繁體中文，照這個順序做，缺一不可：

1. 檔頭第一行放 `chcp 950>nul 2>nul`（第二行放 `@echo off` 也可以，但 `chcp`
   那行必須是純 ASCII，否則第一行的中文就已經亂了）
2. 檔案存成 **ANSI / Big5（cp950）**，不是 UTF-8
3. 避開第二個 byte 是 `0x5C` / `0x7C` 的字（功、會、許、蓋、育、院……），
   或改成用 `chcp 65001` + UTF-8 存檔
4. 用 `tools/make_bat.py` 的 `_find_bad_trail_bytes()` 這種檢查先掃一遍
