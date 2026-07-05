# Game Translator — 架構與設計（現況總覽）

> 本文件反映**目前實際實作**的完整架構，取代早期只涵蓋 P1（MV 骨架）的
> `2026-07-04-game-translator-p1-design.md`（該份與其 plan 保留作歷史紀錄）。
> 測試現況：約 207 passed（含加密 MZ 支援；`test_server.py` 偶發 Windows socket flaky，重跑即綠）。

---

## 1. 目標與原則

一套**通用、不遠端注入、不易被防毒誤報**的日文遊戲翻譯工具，把日文遊戲翻成中文。

- **不遠端注入**：不使用 `CreateRemoteThread`／`inject.exe` 類手法（MTool 被掃毒的元兇）。
  - RPG Maker：adapter 是**遊戲自己載入的 JS plugin**。
  - TyranoScript：純**檔案預翻**，執行期不掛任何東西。
- **翻譯引擎可插拔**：現成字典（離線）／DeepL／本地 Ollama（含 Sakura），統一走 `Pipeline`。
- **產出可沿用 JSON**：翻過的累積進 `translator_dict.json`（＋全域共用字典），可重用、可分享，格式與 MTool 字典互通。

---

## 2. 支援矩陣（現況）

| 引擎 | 偵測依據 | 翻譯方式 | 狀態 |
|---|---|---|---|
| RPG Maker MV | `www/js/rpg_core.js` | JS plugin：整字典嵌入 + 底層畫字 hook 即時查表 | ✅ |
| RPG Maker MZ | `js/rmmz_core.js` | 同上（index.html 注入點改在 `main.js` 前） | ✅ |
| 加密 RPG Maker MZ | `data/*.json` 為 `{uid,bid,data}` 密文 | 部署時 Python 解密（自動爆破金鑰，`bid 1.8.1` 家族）→ 抽字 → Sakura 批次預翻建離線字典 → 離線 hook 查表；`data` 零改動 | ✅ 程式碼完成／端到端實機驗收待做 |
| TyranoScript（Electron） | `resources/app.asar` 內含 `.ks` | 解包 asar → 批次翻 `.ks` → 改名 asar 讓 Electron 用 `app/` | ✅ |
| Unity / 原生 Win32 | — | （未支援）規劃由 P2 OCR 兜底 | ⏳ |

---

## 3. 核心元件（Python 大腦）

- **core/detector.py**：`detect(exe)` → `Detection(engine, game_dir, www_dir, js_dir, web_dir)`。判 mv/mz/unity/tyrano/unknown。`web_dir` = 含 index.html/js 的目錄（mv=www、mz=遊戲根）。
- **core/cache.py**：`DictCache`（扁平 `{原文:譯文}` JSON，UTF-8；對損毀/空檔容錯退回空字典）。
- **core/translators/**：
  - `base.Translator`（抽象）
  - `deepl.DeepLTranslator`（依官方 API：`/v2/translate`、`DeepL-Auth-Key`、狀態碼 456/403/429）
  - `null.NullTranslator`（離線字典模式：原樣回傳，不呼叫網路）
  - `local.LocalTranslator`（打 Ollama `/api/chat`；**單句容錯 + 重試**；**Sakura 模式**：偵測模型名含 sakura → 用 Sakura 專用系統提示與「将下面的日文文本翻译成中文：」格式）
- **core/pipeline.py**：`Pipeline(cache, translator, target_lang, source_lang, postprocess, global_cache, store_converted)`
  - **分層查詢**：遊戲私有 cache → 全域 cache → 引擎。
  - **分批 + 邊翻邊存**（BATCH=50）：中途崩潰最多丟一批，可續跑。
  - **雙寫**：新翻結果同時寫遊戲 cache 與全域 cache。
  - **postprocess**：繁體（OpenCC s2twp）於輸出時套用。
  - **store_converted**：新翻條目寫入 cache 前先轉繁（讓 JSON 存繁體）；預設 False（存簡體較通用）。
- **core/postprocess.py**：`make_traditional_converter()`（OpenCC `s2twp`，lazy import）。
- **core/paths.py**：`global_dict_path()` → `~/.game_translator/global_dict.json`。
- **core/server.py**：localhost `POST /translate`（RPG Maker 執行期用；只綁 127.0.0.1；輸入防呆回 400）。
- **core/asar.py**：Electron asar 讀取／攤平／解包（`read_asar_header`／`iter_files`／`extract_asar`）。

---

## 4. 遊戲端 adapter

### 4.1 RPG Maker（MV/MZ）— `adapters/mv/ZZ_Translator_Bridge.js` + `launcher.py`
- **bridge**：偵測 `window.$translatorDict` → 離線整字典模式；`lookup()` 統一查表（整串 → 前綴正規化剝 `\n<名>`/`en()`/`if()` 後查 inner，保留前綴），hook `Bitmap.prototype.drawText`（全面覆蓋）與 `Window_Base.prototype.convertEscapeCharacters`（訊息）。線上模式保留 collectStrings + server 路徑。全程 try/catch + console.warn，不崩遊戲。
- **launcher.deploy_mv_adapter**：複製 bridge → 寫 `translator_dict_data.js`（離線嵌入整字典）＋ `translator_boot.js`（port/maps）→ 於 `plugins.js` 末端註冊 → index.html 於 `js/plugins.js` 或 `js/main.js`（取先出現者）之前注入。**改檔前自動備份 `.trbak`**；可重入；找不到載入點會 raise。
- **launcher.restore_mv_adapter**：還原 plugins.js/index.html、刪 bridge/boot/dict_data。

### 4.2 TyranoScript — `adapters/tyrano/` + `deploy.py`
- `ks.py`：`extract_segments`／`apply_translations`（翻純文字行 + 資料陣列行 `[數字,…]` 引號內容 + **標籤屬性白名單顯示文字**〔`text`/`hint`/`label`/`label_ok`/`label_cancel`；跳過 `name`/`exp`/`&` 變數運算式〕；跳 `#名`/`*label`/`;`/`//`；保留行內 `[n2]` 與結尾 `[p]`）。
- `deploy.py`：`translate_tree`（跨檔彙整去重 → 一次 pipeline.translate → 逐檔回寫；三階段 progress）、`deploy_tyrano`（解包 app.asar → 翻 → `os.replace` 把 app.asar 改名成 `.trbak`；可重入）、`restore_tyrano`（刪 app/、改名回 app.asar）。

---

## 5. GUI（`gui/app.py`，PySide6）

- 選遊戲主程式 → 自動判型 → 依 `can_start`（僅 mv/mz/tyrano）鎖解「開始」。
- 翻譯來源：引擎下拉（DeepL / 本地 Ollama＋模型欄）＋「選擇既有字典 JSON」＋ key 欄；`choose_translator_mode(engine, dict_path, key)` → offline/deepl/local/none。
- 選項：**繁體中文（s2twp）**、**使用全域共用字典**、**翻譯 JSON 存繁體**（皆為 checkbox）。
- 流程分流：
  - **mv/mz** → 部署 JS adapter + 起 server + 直接啟動遊戲（不注入）。
  - **tyrano** → **背景 QThread** 跑 `deploy_tyrano`（批次預翻、進度顯示）→ 翻完啟動；不需 server。
- 「還原遊戲」鈕：依引擎呼叫對應 restore。
- 全程 try/except 容錯，錯誤顯示於狀態列。

---

## 6. 打包與啟動

- **PyInstaller**：`GameTranslator.spec`（onedir + `--windowed` 免主控台黑窗），bridge JS 以資源打包；`resource_path()` 兼容開發/凍結（`sys._MEIPASS`）。
- 啟動：`啟動翻譯工具.bat`（CRLF）／`還原遊戲.bat`（拖 Game.exe）／`restore.py`（CLI）。

---

## 7. 本地 LLM（Ollama）

- 我們的工具只用 `requests` 打 `127.0.0.1:11434`，不引入重相依；模型跑在 Ollama、GPU 加速。
- 推薦模型：**Sakura-GalTransl-7B**（galgame 專用，處理控制碼/ruby 較佳）；`qwen2.5` 為通用備選。輸出簡體 → 由 postprocess 轉繁。

---

## 8. 已知限制與路線圖

- **加密 RPG Maker MZ**：✅ 已支援（見 §2）。部署時 Python 解密 `{uid,bid,data}`（自動爆破金鑰、`bid 1.8.1` 家族）→ 抽字 → Sakura 批次預翻建離線字典；`data` 零改動。新增模組 `core/mz_decrypt.py`、`core/mz_extract.py`、`core/translators/protect.py`（控制碼保護）、`adapters/mz/pretranslate.py`。端到端實機驗收待做。
- **P2 OCR 通用兜底**（未實作）：截圖 + manga-ocr/PaddleOCR + 復用引擎 + PySide6 疊字；用於 Unity/原生/圖內文字等 hook 不到的情況。可靠度：乾淨對話框高、文字疊 CG 低。
- **s2twp 偶爾過度在地化**（如 `选择项目→選擇專案`）；GalGame 容錯高，必要時可改 `s2t`。
- **全域字典**目前無 GUI 清空/自訂路徑/淘汰機制；離線整字典嵌入模式不含全域字典內容。

---

## 9. 測試

- `pytest`：約 207 passed（detector/cache/translators/pipeline/server/asar/tyrano/launcher/gui 狀態機/postprocess/paths + 加密 MZ 解密/抽字/控制碼保護/批次預翻…；`test_server.py` 偶發 Windows socket flaky，重跑即綠）。
- 遊戲端 JS 以 `node --check` 靜態驗；真實遊戲的視覺翻譯由使用者實機驗收。
