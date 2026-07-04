# Game Translator — P1 設計規格（MV/MZ 骨架打通）

日期：2026-07-04
專案位置：`D:\Xampp\htdocs\game-translator`
GUI 框架：PySide6（Qt）
語言：Python（大腦）＋ 遊戲端薄 adapter

---

## 0. 專案總目標（背景，非本階段全部範圍）

做一套「通用、不遠端注入、不易中毒」的遊戲翻譯工具：

- **Python = 大腦**：翻譯引擎（可插拔）、譯文快取字典、設定、localhost 伺服器、（未來）OCR、GUI。
- **遊戲端 = 薄 adapter**：只負責「抓原文 → 丟給 Python → 收譯文 → 顯示」。
  - RPG Maker MV/MZ → JS plugin
  - Unity → BepInEx C# plugin（遊戲自己載入，不遠端注入）
  - 其他引擎 → Python OCR 疊加兜底
- **DLL 政策**：一律「遊戲自己載入」模式，**禁止遠端注入**（不用 `CreateRemoteThread`／`inject.exe` 那套）；binary 之後買 code signing 憑證簽章以消除無信譽誤報。

分四階段推進：**P1（本文件）** → P2 OCR 兜底 → P3 Unity adapter → P4 可插拔引擎補完（本地 Sugoi 無審查、LLM 潤色）＋ GUI 華麗化＋簽章。

---

## 1. P1 目標

用**最容易的 adapter（MV/MZ JS）**打通整條垂直鏈路：

> 選遊戲主程式 → 自動判型 → 部署 adapter → 啟動遊戲 → 遊戲內出現中文

以此證明：**架構成立、且完全不需要遠端注入**。

驗收白老鼠：`D:\7-Zip\tmp\禰鳥村 愛虐と淫艶の祀 ver1.01`（已確認為 RPG Maker MV / NW.js）。

---

## 2. P1 範圍

**做：**
- Python core：翻譯引擎抽象層 + DeepL 實作 + 譯文快取字典 + localhost 伺服器
- 引擎偵測器（detector）
- 最小 GUI（PySide6）：選 exe / 顯示判型 / 鎖解「開始」/ 啟動
- MV/MZ JS adapter

**不做（留待後續階段，明確排除）：**
OCR、Unity 實作、本地 Sugoi、LLM、code signing、GUI 美化、多語系 UI、金手指。

---

## 3. 元件與介面

### 3.1 引擎偵測器 detector
- **輸入**：使用者選的遊戲 exe 路徑。
- **邏輯**（看 exe 所在資料夾特徵）：
  - `www/js/rpg_core.js` 存在 → `mv`
  - `www/js/rmmz_core.js` 存在 → `mz`
  - 同層有 `*_Data/` 且有 `UnityPlayer.dll` → `unity`（P1 只標記，不實作流程）
  - TyranoScript 特徵（`data/` + tyrano 標記）→ `tyrano`（P1 只標記）
  - 都不符 → `unknown`
- **輸出**：`{ engine, game_dir, www_dir? }`
- **可覆寫**：GUI 顯示判定，允許使用者手動改（防誤判）。

### 3.2 翻譯引擎（可插拔）
- **抽象介面** `Translator`：
  - `translate(texts: list[str], src: str, dst: str) -> list[str]`
- **DeepLTranslator**：串官方 API。
  - **鐵則：一切依 DeepL 官方文檔為準，不臆測狀態碼／欄位／回應結構。** 端點、成功狀態碼、`translations[].text` 欄位、free（`api-free.deepl.com`）vs pro（`api.deepl.com`）差異、額度／金鑰錯誤碼，全部查文檔確認後才寫。
  - 需 `auth_key`（由 GUI 輸入）。
- **快取優先**：先查字典 → 命中直接回；未命中才呼叫 API，翻完寫回字典。

### 3.3 譯文快取字典
- **格式**：`{ "原文": "譯文" }` 扁平 JSON（與遊戲附的 `AI翻译文件.json` 同款，方便互通／匯入）。
- **位置**：每個遊戲一份，存在工具側 `games/<game_id>/dict.json`（`game_id` 以遊戲路徑雜湊）。不污染遊戲原檔。

### 3.4 本機伺服器（localhost）
- 只綁 `127.0.0.1`，adapter 用來要譯文。
- **端點**：`POST /translate` body `{ "texts": ["...", ...] }` → `{ "translations": ["...", ...] }`
  - 內部：先查快取 → 未命中批次送引擎 → 寫快取 → 回傳。
- 傳輸方式（HTTP vs websocket）於實作計畫定案；P1 預設簡單 HTTP。

### 3.5 MV/MZ JS adapter
- 一支 plugin JS，由工具**寫進遊戲** `www/js/plugins/` 並在 `plugins.js` 註冊（或於 `index.html` 注入 `<script>`）——皆為遊戲自己載入，**無遠端注入**。
- **翻譯策略（P1 採最穩妥者）**：開機時把 `www/data/*.json` 內可見字串抽出 → 批次送 localhost server 翻譯＋快取 → 之後遊戲取用時查表替換顯示。
  - 實際 hook 點（`Window_Base.prototype.drawText` / `convertEscapeCharacters` / `Window_Message` 等）**須先讀該遊戲實際文字管線後定案**，不預先臆測。
- server 未就緒時 → 顯示原文，不崩。

### 3.6 最小 GUI（PySide6）
- 「選擇遊戲主程式」按鈕 → 顯示偵測結果（例：`偵測到：RPG Maker MV`）。
- 引擎下拉（P1 只有 DeepL）＋ DeepL API key 輸入框。
- 「開始」鈕：
  - **未選遊戲 → disabled**，狀態列顯示「請先選擇遊戲主程式」。
  - 選到且判型成功 → enabled。
- 按「開始」：部署 JS adapter → 啟動 localhost server → 直接啟動 `Game.exe`（**不經 inject.exe**）。

---

## 4. 資料流

```
選 exe
  → detector 判定 MV
  → GUI 顯示判型並解鎖「開始」
  → 按開始
  → 寫入 JS adapter + 起 localhost server + 開 Game.exe
  → 遊戲內 adapter 開機抽字串 → POST /translate
  → server 查快取 / 未命中呼叫 DeepL → 寫快取 → 回譯文
  → adapter 查表替換 → 顯示中文
```

---

## 5. 錯誤處理

| 情況 | 行為 |
|---|---|
| 未選遊戲 | 「開始」鎖住 + 狀態列提示，翻譯鏈路不啟動 |
| 判型 `unknown` / `unity` / `tyrano` | 提示「此引擎 P1 尚未支援（之後由 OCR / 專屬 adapter 處理）」，不解鎖 MV 流程 |
| DeepL API 失敗 | **依官方文檔狀態碼**分辨（額度用盡 / 金鑰錯 / 網路），明確回報，不硬撐、不捏造；該段保留原文 |
| localhost server 未就緒 | adapter 顯示原文，遊戲不崩 |

---

## 6. 測試 / 驗收標準

1. 用 `禰鳥村`：GUI 選 `Game.exe` → 顯示「RPG Maker MV」→ 按開始 → 遊戲主選單／對話出現中文。
2. 全程**不執行** `inject.exe` / `mzHook32.dll`（可從工作管理員確認遊戲程序無被注入）。
3. 未選遊戲時「開始」確實鎖住。
4. 斷網或抽掉 API key → 有明確錯誤訊息，遊戲不崩（顯示原文）。

---

## 7. 非目標（P1 明確不碰）

OCR、Unity 實作、本地離線模型、LLM 潤色、code signing、GUI 美化、多語系 UI、金手指。
