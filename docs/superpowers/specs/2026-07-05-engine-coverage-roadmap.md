# 引擎覆蓋率擴充 Roadmap（待做，按順序）

> 目標：用**非注入**路線（逐引擎的檔案格式處理器，如同加密 MZ 解密器、Tyrano asar 解包）
> 逐步擴大支援引擎，追近 MTool 的覆蓋率——但**不複製 MTool 的注入/記憶體 hook 機制**
> （那正是我們要避開、會被防毒誤報的東西）。
>
> 每個引擎＝一個獨立子專案，挑到時各走一次 brainstorm → spec → plan → subagent 實作。

## 對照基準（MTool 支援引擎，查證來源見下）

RPG Maker 2k/2k3/XP/VX/VXAce/**MV/MZ**、Wolf RPG、**TyranoBuilder(=TyranoScript)**、SRPG Studio、KiriKiri、SMILE GAME BUILDER、Bakin、Ren'Py、Pixel Game Maker MV。
來源：mtool.app、cirno.biz 官方帖（2026-07 查證）。MTool 機制為執行期 process/記憶體 hook + 資料檔解析。

## 現況（已支援）

- ✅ RPG Maker **MV / MZ**（含**加密 MZ** `bid 1.8.1`）
- ✅ **TyranoScript**（含標籤屬性顯示文字）

## 待做（依性價比排序）

### 1. Ren'Py（最優先）
- 格式：Python，`.rpy` 腳本 / `.rpa` 封包。
- 非注入做法：Ren'Py **內建官方翻譯系統**（`renpy.translation`／`tl/` 目錄），或直接抽 `.rpy` 的 dialogue/字串。純檔案、零注入、最貼合我們路線。
- 可行性：**高**。工程小、遊戲量大（VN 大宗）。
- 風險：`.rpa` 需解包（格式公開、有現成法）；要避免翻到 Python 程式碼字面。

### 2. KiriKiri / KAG（次優先）
- 格式：`.xp3` 封包 + KAG（`.ks`）腳本（與 Tyrano 的 `.ks` 類似但不同引擎）。
- 非注入做法：解 `.xp3` → 翻 KAG 腳本純文字（可大量復用 Tyrano `ks.py` 的「純文字行 + 標籤屬性」抽取思路）→ 回包/覆蓋。
- 可行性：**中高**。VN/成人遊戲常見；`.xp3` 解包有成熟資料。
- 風險：`.xp3` 加密變體多、KAG 方言差異；需處理 tjs 腳本內字串（謹慎）。

### 3. RPG Maker XP / VX / VXAce
- 格式：RGSSAD/RGSS3A 加密封包 + Ruby **Marshal** 二進位資料（`Data/*.rvdata2` 等）。
- 非注入做法：解 RGSSAD（演算法公開）→ 解 Marshal 讀事件/資料庫文字 → 翻 → 回寫 Marshal。
- 可行性：**中**。工程較硬（要在 Python 解析/重建 Ruby Marshal 格式）。
- 風險：Marshal 版本細節、腳本(Scripts.rvdata2)內字串處理。

### 4. Wolf RPG（WOLF RPGエディター）
- 格式：自訂封包（`.wolf`）+ `Game.dat` + 事件/資料二進位。
- 非注入做法：解封包 + 解析 Wolf 的二進位事件格式抽文字。
- 可行性：**中低**。格式較封閉、工程大；但同人常見，價值高。
- 風險：格式逆向成本高；版本差異。

### 5. 其餘（個別評估、較低優先）
- **Pixel Game Maker MV**（アクションゲームツクールMV）：資源加密、格式較封閉。
- **SRPG Studio**：JS 系、可能較好切入（待查）。
- **SMILE GAME BUILDER / Bakin**：較新、資料格式待查。
- **RPG Maker 2k/2k3**：老引擎（LMU/LDB 二進位），EasyRPG 生態有格式資料可參考。

## 與既有待做的關係（見 handoff 2.x）

- 這份 roadmap 專注「**多引擎覆蓋**」；與以下既有項並行、互不取代：
  - **P2 OCR 通用兜底**（handoff 2.1）：處理「拿不到原文」（Unity/原生/圖內字/無法解的加密）——是所有引擎路線都打不到時的**最後兜底**。
  - **exe code signing**（handoff 2.4）：對外發佈免防毒誤報。
- 一般原則：**能用檔案處理器（本 roadmap）就別用 OCR**（乾淨原文 > OCR）；OCR 留給真的沒有可解檔案的情況。

## 執行方式

挑一個引擎 → `brainstorming`（釐清格式/範圍/測試策略，務必先拿到一款真實遊戲當 fixture）→ 寫 spec → `writing-plans` → subagent 實作。每個引擎的解析/抽取器獨立成模組（比照 `core/mz_decrypt.py`、`adapters/tyrano/ks.py`），可 TDD、不入庫遊戲內容。
