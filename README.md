# Game Translator

一套**通用、不遠端注入、不易被防毒誤報**的日文遊戲翻譯工具。用「遊戲自己載入」或「檔案預翻」的方式把日文遊戲翻成中文，避開 MTool 那種會被掃毒的 DLL 注入。

翻譯引擎**可插拔**：可用現成字典（離線）、DeepL、或**本地 Ollama LLM（離線、無審查、能翻 H）**。

---

## 支援的遊戲類型（當前）

| 引擎 | 判定依據 | 翻譯方式 |
|---|---|---|
| **RPG Maker MV** | `www/js/rpg_core.js` | 塞 JS plugin（遊戲自己載入）+ 底層畫字 hook 即時查表 |
| **RPG Maker MZ** | `js/rmmz_core.js` | 同上（注入點改在 `main.js` 前） |
| **TyranoScript（Electron 打包）** | `resources/app.asar` 內含 `.ks` | 解包 asar → 批次預翻 `.ks` → 改名 asar 讓遊戲改用翻好的資料夾 |

> 選遊戲主程式後會**自動判型**。Unity / 其他引擎目前不支援（規劃中的 OCR 通用兜底可涵蓋）。

---

## 安裝與需求

### 方式 A：打包好的 exe（免裝 Python）
到 `dist/GameTranslator/`，雙擊 **`GameTranslator.exe`**（onedir、無主控台黑窗）。整個資料夾要一起搬。

### 方式 B：原始碼
需要 Python 3.10+：
```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
啟動：雙擊 **`啟動翻譯工具.bat`**，或 `.\.venv\Scripts\python.exe main.py`。

---

## 翻譯來源（三選一，可混用）

| 來源 | 誰在翻 | 特性 |
|---|---|---|
| **現成字典 JSON** | 別人/MTool 早翻好的（`翻译文件.json`、`AI翻译文件.json` 等） | 離線、免費、秒出；命中率看字典完整度 |
| **DeepL API** | DeepL 伺服器 | 需 API key；會拒譯/消毒露骨內容 |
| **本地 Ollama** | 你電腦上的本地 LLM（Qwen2.5） | **離線、無審查、能翻 H**；需顯卡較佳 |

**推薦組合**：現成字典打底（命中即免費）＋ Ollama 補字典沒有的（含 H）。翻過的自動存回快取，重玩不用再翻。

---

## 本地 Ollama 設定（要用本地無審查翻譯才需要）

1. **下載點**：<https://ollama.com/download> → Windows → 裝 `OllamaSetup.exe`（正常應用程式、開源、不注入，不會被掃毒）。
2. **下載哪個模型**（開 PowerShell）：
   ```
   ollama pull qwen2.5:14b
   ```
   - 14b 約 9GB，需約 10GB VRAM（如 RTX 3080）。顯卡小或想快 → `ollama pull qwen2.5:7b`（約 4.7GB）。
3. **（選用）模型放別的槽**：設使用者環境變數 `OLLAMA_MODELS`，例如 `D:\Ollama\models`，然後**完全退出 Ollama（系統匣右鍵 → Quit）再重開**才生效。
4. **確認就緒**：`ollama list` 或瀏覽器開 `http://127.0.0.1:11434/api/tags` 應看到模型。

---

## 使用流程

### RPG Maker MV / MZ
1. 開工具 → **選擇遊戲主程式**（`Game.exe`）→ 顯示「偵測到：RPG Maker MV/MZ」。
2. 選翻譯來源：
   - **離線字典**：按「選擇既有字典 JSON」選遊戲附的字典，**DeepL key 留空**。
   - **本地 Ollama**：引擎下拉選「本地 Ollama」，模型欄填 `qwen2.5:14b`。
   - **DeepL**：填 API key。
3. 按 **開始** → 自動部署 + 直接啟動遊戲（不經 inject.exe）。首次遇到的文字即時翻、之後走快取。

### TyranoScript
1. 選遊戲主程式 → 顯示「偵測到：TyranoScript」。
2. 選翻譯來源（同上）。
3. 按 **開始** → **背景批次預翻所有劇本**（有進度顯示，Ollama 補漏時較久）→ 翻完自動啟動中文版。

---

## 還原（移除翻譯修改）

- **RPG Maker**：GUI 按「還原遊戲」；或把 `Game.exe` 拖到 **`還原遊戲.bat`**。
- **TyranoScript**：GUI 選遊戲 → 按「還原遊戲」（會刪掉解包的 `app/`、把 `app.asar` 改回來）。
- 工具部署前會**自動備份**原始檔（`.trbak`），可完整還原。

---

## 為什麼「不易被防毒誤報」

- **不做遠端注入**：不用 `CreateRemoteThread` / `inject.exe` 那種被防毒標記的手法。
- RPG Maker：adapter 是**遊戲自己載入的 JS plugin**（正常行為）。
- TyranoScript：純**檔案預翻**，連執行期都不掛任何東西。
- 直接啟動遊戲本體，不經任何注入器。

> 註：若要對外發佈打包的 exe，仍建議買 code signing 憑證簽章以徹底免除誤報。

---

## 運作原理（簡述）

- **Python 大腦**：引擎偵測、翻譯引擎（DeepL / Ollama / Null）、快取字典（扁平 `{原文:譯文}` JSON）、本機伺服器（RPG Maker 執行期用）。
- **遊戲端**：
  - RPG Maker：一支 JS plugin，hook `Bitmap.drawText` 與 `convertEscapeCharacters`，對整份嵌入的字典即時查表替換。
  - TyranoScript：解包 `app.asar`，只翻 `.ks` 的純文字行（跳過 `[標籤]`、`#名字`、`;註解`，保留行內 `[n2]` 與結尾 `[p]`），改名 asar 讓 Electron 改用翻好的 `app/`。

---

## 規劃中（未完成）

- **P2 OCR 通用兜底**：截圖辨識，涵蓋 Unity 與任何無專屬 adapter 的引擎、以及烤進 CG 圖片裡的文字。
- 本地 LLM 批次翻譯的速度優化、提示詞對包裹標籤（如 `[font_blue]…[resetfont]`）的保留。
