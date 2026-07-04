# 加密 RPG Maker MZ 支援 — 設計（spec）

> 對應 handoff 2.2「加密 JS 遊戲」。實測後方向已修正：真實障礙只有**一層檔案加密**，
> 破解後即為乾淨日文，走既有「檔案預翻」路線即可，**不需要**執行期即時 hook。
> 目標遊戲（開發/驗收用，內容為 H 同人，**不入庫**）：`ゆうべは大変おたのしみでしたね。`

---

## 1. 背景與實測結論

現有工具對此款加密 MZ 覆蓋率低，原因是**部署時讀不到原文**：`data/*.json` 為密文，
工具無法在部署階段抽字建字典，離線字典只剩遊戲附的 MTool `翻译文件.json`（1739 條、殘缺）。

實測（PoC 已驗證，證據見對話紀錄）確認：

1. **檔案加密可破且可逆**。每個 data 檔為 `{"uid":…, "bid":"1.8.1", "data":"<base64 密文>"}`。
   解密邏輯被改寫進遊戲的 `js/rmmz_managers.js`（`DataManager.onXhrLoad`，混淆過）：
   - 金鑰種子 `_K = Math.sqrt(51076)|0 = 226`（此款寫死）。
   - 依**檔名**（去副檔名、轉小寫）算 hash `t`：`t = ((t<<5) - t + charCode) | 0`。
   - 派生金鑰 `fk = _K XOR (t & 255)`。
   - 反向逐位元組解密，用前一個（已解出的）位元組回饋：
     ```
     ls = fk
     for i = len-1 .. 0:
         _c = fk XOR 23
         _p = (ls<<2) XOR (ls>>>3)
         _k = (((_c + (i % 128) + _p) XOR 186) + 33) & 255
         v  = b[i] XOR _k
         b[i] = v; ls = v
     ```
   - 解出的位元組為 **UTF-8**，`JSON.parse` 後即標準 MZ 資料結構。
   - 另含綁 `libGLESv2.dll`（大小 8192528 + 特定位移 hash）的反竄改 `process.exit`——只保護遊戲本體，**與解密無關**，我方 Python 端不受影響。

2. **沒有第二層字元替換**。解密後日文完全乾淨（角色名「エイト/ゼシカ」、訊息「暗闇の中その小さな穴をみる。」、控制碼 `\FS[28]`/`\SE[0]`/`♥` 皆完整）。全庫掃描後**真亂碼 0 條**。
   先前疑似的「特製訊息系統／字型替換」是 Windows cp950 主控台輸出 UTF-8 時的**顯示亂碼假警報**，非資料問題。

3. **MTool 看到的也是真日文**（其字典 key 為 `移動（宿屋　受付）` 等真日文），代表此款無需還原字碼即可比對替換。

**結論**：補上「部署時解密」即可讓既有離線預翻全流程生效。

---

## 2. 設計原則與核心洞察

- **執行期不使用我方解密器**：遊戲自己會把 data 解密進記憶體（`window.$dataXXX`）。
  我方離線 hook（`Bitmap.drawText` / `Window_Base.convertEscapeCharacters`）只需用
  「原文 → 譯文」完整字典查表替換即可。
- **我方 Python 解密器只在「部署時」用**：讀出原文、建字典。
- **`data/*.json` 零改動**：維持原加密檔，最安全、可完整還原（僅動 index.html/plugins.js，
  沿用既有 `.trbak` 備份機制）。
- **最大化復用**：Pipeline（分層查詢／分批邊翻邊存／繁體 postprocess／全域字典）、
  監控面板、Sakura 模式、離線 hook、備份還原——全部沿用，不重造。

---

## 3. 元件設計

### 3.1 `core/mz_decrypt.py`（新）— 加密 MZ 解密器

單一職責：把加密 MZ 的 data 內容還原成 Python 物件。純函式、無 I/O 副作用（讀檔由呼叫端負責）。

介面：

- `is_encrypted_mz(obj: dict) -> bool`
  判斷是否為加密結構：`obj` 同時含 `uid`、`bid`、`data`（`data` 為非空字串）。

- `detect_key(sample_data_b64: str, filename: str) -> int | None`
  **自動爆破 `_K`**：`K` 由 0 試到 255，對 `sample` 解密，取「解出為合法 UTF-8 且
  `json.loads` 成功」的 `K`。找不到回 `None`。`_K` 為全庫不變量，偵測一次即可全庫共用
  （建議用最小的一個 data 檔偵測，找到後可用第二個檔驗證一致性）。

- `decrypt(data_b64: str, filename: str, key: int, scheme: str = "bid_1.8.1") -> dict`
  依上述演算法解密並回傳 `json.loads` 結果。`filename` 需為**去路徑、去 `.json`、轉小寫**後的名稱
  （與遊戲 `src.split(...).pop().replace('.json','').toLowerCase()` 一致）。

實作細節與可擴充性：

- 演算法常數（`23`、`186`、`33`、回饋式 `(ls<<2)^(ls>>3)`、`i%128`、種子公式）以
  `scheme` 對應一組參數的方式收斂在一處（例如 `_SCHEMES = {"bid_1.8.1": {...}}`），
  日後遇到別的 `bid`/加密器可加新 scheme，不動主流程。
- 位元運算一律以 `& 0xFF` / `& 0xFFFFFFFF` 明確遮罩，對齊 JS 的 `|0` 與位元語意。

### 3.2 `core/mz_extract.py`（新）— MZ 文字抽取器

單一職責：把「解密後的 MZ 資料結構」轉成「待翻字串清單」，keying 對齊 MTool 慣例
（確保與執行期 hook 收到的字串吻合）。純資料轉換、無 I/O。

介面（暫定）：

- `extract_strings(data_name: str, data_obj) -> list[str]`
  依 `data_name` 分派：
  - **地圖 / CommonEvents / Troops 事件指令**：
    - `401`/`405`（顯示文字）：**連續者分組成一則訊息塊**（以 `\n` 串接），整塊為一個 key。
    - `102`（選項）、`402`（選項分支標題）：逐項。
    - 跳過：`355`/`655`（script）、`108`/`408`（註解）、純數值參數。
  - **System.json**：`terms`（basic/commands/params/messages）、`gameTitle` 等可見詞條。
  - **Actors/Items/Skills/Weapons/Armors/States/Classes/Enemies**：
    `name`、`nickname`、`description`、`profile`、`message1..4`（存在者）；跳過 `note`（多為 meta）。
  - 一律只收「含日文假名/漢字」的字串；去重由呼叫端或 Pipeline 處理。

- 控制碼保護：對送往翻譯引擎的字串，先把控制碼（`\` 開頭的 `\XX` 與 `\XX[...]`）
  以 placeholder 遮罩、翻完還原，避免模型改動或吃掉控制碼；`♥` 等符號保留原樣。
  （字典 key 仍為**含控制碼的原字串**，以對齊執行期 hook 所見。）

> keying 對齊策略：以遊戲現成 `翻译文件.json`(MTool) 的實際 key 形態為準繩，
> 於實作時比對「解密資料」與「MTool key」校準分組規則（MTool 字典本就與現有 bridge 相容）。

### 3.3 整合到部署流程

- **`core/detector.py`**：MZ 判定後，額外 peek 一個 `data/*.json`，若 `is_encrypted_mz` 為真，
  在 `Detection` 標記 `encrypted=True`（欄位新增，向後相容預設 False）。
- **`launcher.py`（MZ 部署路徑）**：當 `encrypted`：
  1. 讀 `data/*.json` → `detect_key` 取 `_K` → 逐檔 `decrypt`。
  2. `mz_extract.extract_strings` 彙整全部待翻字串、去重。
  3. **先併入遊戲現成字典**（`翻译文件.json` MTool + `translator_dict.json`）當底，已翻者不重翻。
  4. 缺口交 `Pipeline.translate`（Sakura）補齊；沿用分批邊翻邊存與繁體。
  5. 產出完整 `{原文:譯文}` → 沿用現有 `translator_dict_data.js` 嵌入 + 離線 hook 部署。
  6. `data/*.json` **不改**。
- **監控面板**：此批次路徑接上段級 `segment_progress`（順帶補 handoff 2.3 對 MZ 的一部分）。

---

## 4. 測試策略（TDD、pytest 全綠再交付）

- **`tests/test_mz_decrypt.py`**：
  - **Round-trip**：在測試內用同演算法**加密**一段自製已知日文 JSON → `decrypt` → 應完全相等。
    （不依賴、也不入庫任何遊戲內容。）
  - `detect_key` 對 round-trip 樣本能爆破出正確 `K`；亂資料回 `None`。
  - `is_encrypted_mz` 對 `{uid,bid,data}` / 一般 JSON 的判定。
  - **真檔 smoke test**：以環境變數/固定本機路徑指向實體遊戲，存在才跑（`skipif`），
    驗證能解出含指定日文片段；**遊戲檔不入庫**。
- **`tests/test_mz_extract.py`**：小段自製解密資料 → 預期字串集合（訊息分組、選項、名稱、System；
  控制碼遮罩/還原 round-trip）。
- **`tests/test_detector.py`**：補加密偵測案例（以自製最小加密 data 檔）。
- **launcher 整合測試**：以自製加密 fixture 走「解密→抽取→（stub 引擎）翻→建字典」路徑。

---

## 5. 驗收（實機，鐵則 #7）

單元測試全綠**不等於**功能完成。最終須：

1. `.\.venv\Scripts\python.exe -m pytest -q` 全綠。
2. 對實體遊戲部署 → 啟動 `Game.exe` → **實際訊息視窗顯示中文**、覆蓋率明顯高於原本 1739 條。
3. 記錄命中率與未命中樣本；若執行期 hook 字串與 key 不吻合，回頭校準 §3.2 keying。
4. 「還原遊戲」可完整復原（index.html/plugins.js 還原、data 本就未動）。

報告寫 `.superpowers/sdd/`（gitignored）。

---

## 6. 範圍與非目標

- **範圍**：`bid 1.8.1` 加密器（通用偵測 + 自動爆破 `_K`，故同款加密器的其他遊戲多半也能吃）；
  MZ 事件/名稱/System 文字抽取；部署時預翻建字典；data 零改動；接監控面板。
- **非目標**：其他 `bid`/加密器的完整支援（保留 scheme 擴充點，遇到再加）；
  執行期即時 hook（本設計已證明不需要）；OCR（另案 P2）；exe 簽章（另案）。

---

## 7. 風險與對策

| 風險 | 對策 |
|---|---|
| 執行期 hook 收到的字串與抽取 key 不吻合 → 命中率低 | 以 MTool 現成 key 慣例校準分組；實機驗收量測命中率、逐步修正 |
| 別款遊戲 `_K` 或常數不同 | `_K` 自動爆破已涵蓋不同 `_K`；常數不同則新增 scheme |
| 控制碼被翻譯引擎改動 | 送翻前 placeholder 遮罩、翻後還原；key 保留原控制碼 |
| 反竄改 `process.exit` 誤傷 | 僅遊戲本體行為，我方不動 data/dll，部署只加 bridge，不觸發 |
| H 內容入庫風險 | 測試一律用自製資料 round-trip；真檔僅本機 `skipif` smoke，不 commit |
