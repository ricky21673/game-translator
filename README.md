# Game Translator

一套**通用、不遠端注入、不易被防毒誤報**的日文遊戲翻譯工具。用「遊戲自己載入」或「檔案預翻」的方式把日文遊戲翻成中文，避開 MTool 那種會被掃毒的 DLL 注入。

- **翻譯引擎可插拔**：現成字典（離線）、DeepL、或**本地 Ollama LLM**（離線、無審查、能翻 H；可用 galgame 專用的 **Sakura** 模型）。
- **繁體/簡體可選**（OpenCC 台灣在地化）。
- **翻過的自動累積成可沿用 JSON**，還有**全域共用字典**跨遊戲加速。
- **翻譯監控面板**：批次翻譯時即時顯示進度條/ETA/速度 + GPU 溫度/使用率/顯存。

---

## 支援的遊戲類型（當前）

| 引擎 | 判定依據 | 翻譯方式 |
|---|---|---|
| **RPG Maker MV** | `www/js/rpg_core.js` | 塞 JS plugin（遊戲自己載入）+ 底層畫字 hook 即時查表 |
| **RPG Maker MZ** | `js/rmmz_core.js` | 同上（注入點改在 `main.js` 前） |
| **TyranoScript（Electron 打包）** | `resources/app.asar` 內含 `.ks` | 解包 asar → 批次預翻 `.ks`（含回想/畫廊/選單等資料陣列文字）→ 改名 asar 讓遊戲改用翻好的資料夾 |

> 選遊戲主程式後**自動判型**。Unity / 原生 / 加密遊戲目前未支援（見「規劃中」的 OCR 兜底）。

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

## 翻譯來源（可混用）

| 來源 | 誰在翻 | 特性 |
|---|---|---|
| **現成字典 JSON** | 別人/MTool 早翻好的（`翻译文件.json`、`AI翻译文件.json` 等） | 離線、免費、秒出；命中率看字典完整度 |
| **DeepL API** | DeepL 伺服器 | 需 API key；會拒譯/消毒露骨內容 |
| **本地 Ollama** | 你電腦上的本地 LLM | **離線、無審查、能翻 H**；建議有 NVIDIA 顯卡 |

**推薦組合**：現成字典打底（命中即免費、秒出）＋ **本地 Ollama（Sakura）** 補字典沒有的（含 H）。翻過的自動存回快取，重玩不用再翻。

---

## 本地 Ollama 設定

### 1. 裝 Ollama
<https://ollama.com/download> → Windows → 裝 `OllamaSetup.exe`（開源、正常應用程式、不注入，不會被掃毒）。

### 2. 選模型
- **Sakura（galgame 專用，最推薦）**：專為日文 galgame/輕小說翻譯微調，保留對話引號、eroge 語氣、控制碼，明顯優於通用模型。設定見下方 3。
- **通用備選**：`ollama pull qwen2.5:14b`（約 9GB，需約 10GB VRAM；顯卡小用 `qwen2.5:7b`）。

### 3. 匯入 Sakura（galgame 專用）
1. 到 HuggingFace 下載 GGUF（約 4GB）：`SakuraLLM/Sakura-GalTransl-7B-v3.7` → `Sakura-Galtransl-7B-v3.7-IQ4_XS.gguf`（連不上把 `huggingface.co` 換 `hf-mirror.com`）。
2. 在 GGUF 同資料夾建 `Modelfile`：
   ```
   FROM ./Sakura-Galtransl-7B-v3.7-IQ4_XS.gguf
   PARAMETER temperature 0.1
   PARAMETER top_p 0.3
   PARAMETER repeat_penalty 1
   PARAMETER num_predict 512
   SYSTEM 你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。
   ```
3. 匯入：`ollama create sakura -f Modelfile`
4. 之後工具的**模型欄填 `sakura`**（工具會自動用 Sakura 專用提示詞）。

> Sakura 輸出簡體 → 由工具的「繁體」選項用 OpenCC 轉繁，不用擔心。

### 4.（選用）模型放別的槽
設使用者環境變數 `OLLAMA_MODELS`（例如 `D:\Ollama\models`），然後**完全退出 Ollama（系統匣右鍵 → Quit）再重開**才生效。

### 5. 確認就緒
`ollama list` 或瀏覽器開 `http://127.0.0.1:11434/api/tags` 應看到模型。

---

## 翻譯選項（GUI 勾選框）

| 選項 | 作用 | 預設 |
|---|---|---|
| **繁體中文（台灣用語）** | 輸出用 OpenCC `s2twp` 簡轉繁＋在地化（軟體/資訊/裡…） | ✅ 勾 |
| **使用全域共用字典** | 跨遊戲累積翻譯：A 遊戲翻過的常見句在 B 遊戲直接命中，越用越快（存 `~/.game_translator/global_dict.json`） | ✅ 勾 |
| **翻譯 JSON 存繁體** | 新翻條目寫進 JSON 時就存繁體（否則存簡體較通用；輸出都是繁體） | ⬜ 不勾 |

---

## 使用流程

### RPG Maker MV / MZ
1. 開工具 → **選擇遊戲主程式**（`Game.exe`）→ 顯示判型。
2. 選翻譯來源：
   - **離線字典**：按「選擇既有字典 JSON」選遊戲附的字典，key 留空。
   - **本地 Ollama**：引擎下拉選「本地 Ollama」，模型欄填 `sakura`（或 `qwen2.5:14b`）。
   - **DeepL**：填 API key。
3.（可搭配上面的翻譯選項）按 **開始** → 自動部署 + 直接啟動遊戲（不經 inject.exe）。首次遇到的文字即時翻、之後走快取。

### TyranoScript
1. 選遊戲主程式 → 顯示「偵測到：TyranoScript」。
2. 選翻譯來源（同上）。
3. 按 **開始** → **背景批次預翻所有劇本** → 翻完自動啟動中文版。
   - 過程會跳出**翻譯監控面板**：進度條、已翻/總段數、速度、ETA、GPU 溫度/使用率/顯存（長批次跑一晚時很實用）。

> **從 0 全翻**：不選字典、引擎選 Ollama，即可把整款遊戲從頭翻（沒有現成字典打底時較久，但**單句失敗會重試/跳過、每批邊翻邊存**，可放著跑一整晚、中途出錯不白費）。

---

## 產出的可沿用 JSON

每款遊戲的翻譯累積在 `<遊戲>/translator_dict.json`（從你選的字典開始、越翻越完整），格式與 MTool 字典互通，可保留/分享/下次直接載入。另有全域共用字典跨遊戲累積。

---

## 還原（移除翻譯修改）

- **RPG Maker**：GUI 按「還原遊戲」；或把 `Game.exe` 拖到 **`還原遊戲.bat`**。
- **TyranoScript**：GUI 選遊戲 → 按「還原遊戲」（刪掉解包的 `app/`、把 `app.asar` 改回來）。
- 工具部署前會**自動備份**原始檔（`.trbak`），可完整還原。

---

## 為什麼「不易被防毒誤報」

- **不做遠端注入**：不用 `CreateRemoteThread` / `inject.exe` 那種被防毒標記的手法。
- RPG Maker：adapter 是**遊戲自己載入的 JS plugin**（正常行為）。
- TyranoScript：純**檔案預翻**，連執行期都不掛任何東西。
- 本地 Ollama 也是正常開源應用、不注入。
- 直接啟動遊戲本體，不經任何注入器。

> 註：若要對外發佈打包的 exe，仍建議買 code signing 憑證簽章以徹底免除誤報。

---

## 運作原理（簡述）

- **Python 大腦**：引擎偵測、可插拔翻譯引擎（DeepL / Ollama〔含 Sakura 模式〕/ Null）、`Pipeline`（分層查詢：遊戲私有字典 → 全域字典 → 引擎；分批邊翻邊存；繁體 postprocess）、快取字典、本機伺服器（RPG Maker 執行期用）。
- **遊戲端**：
  - RPG Maker：一支 JS plugin，hook `Bitmap.drawText` 與 `convertEscapeCharacters`，對整份嵌入的字典即時查表替換（含前綴正規化）。
  - TyranoScript：解包 `app.asar`，只翻 `.ks` 的純文字行（跳過 `[標籤]`、`#名字`、`;`/`//` 註解，保留行內 `[n2]` 與結尾 `[p]`），改名 asar 讓 Electron 改用翻好的 `app/`。

詳細架構見 `docs/superpowers/specs/2026-07-04-architecture.md`。

---

## 規劃中（未完成）

- **P2 OCR 通用兜底**：截圖 + manga-ocr/PaddleOCR + 復用引擎 + 疊字，涵蓋 Unity / 原生 / **加密遊戲** / 烤進 CG 圖片裡的文字。
- **加密 JS 遊戲**的「執行期即時 hook」（比 OCR 準）。
- 本地 LLM 批次速度優化、提示詞對包裹標籤（如 `[font_blue]…[resetfont]`）的保留。

> 完整的未完成事項、已知限制與接手指南見**交接文件** `docs/superpowers/specs/2026-07-04-handoff.md`。
