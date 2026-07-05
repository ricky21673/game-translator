# TyranoScript 標籤屬性顯示文字翻譯 — 設計（spec）

> 目標：讓 Tyrano 抽取器也能翻「`[標籤]` 屬性裡的顯示文字」（如 `[dialog text="…"]`、
> `[glink text="…"]`、`[button text="…"]`、`hint="…"`），補上目前整行跳過標籤所漏掉的 UI 文字。

## 1. 背景與問題

現有 `adapters/tyrano/ks.py` 逐行處理，只翻兩類行：
1. 純文字行（不以 `[ # * ; @` 開頭、非 `//` 註解、含日文）。
2. 資料陣列行（`[數字,"…","…"]`）的引號內容。

**所有 `[標籤]` 行整行跳過**。但 Tyrano 遊戲把大量**顯示文字放在標籤屬性**裡，例如：
```
[dialog type="confirm" text="直前にプレイしたデータをロードします" label_ok="はい" ...]
[glink text="回想する" ...]
[button ... hint="ヒント文…"]
```
這些 `text=` / `hint=` / `label_*=` 的日文因為在標籤行內而未被翻。

**實測依據**（`無人島社員旅行記` 一款的 scenario）：標籤屬性中「值含日文、且非 `&` 變數運算式」的屬性名分布——
`text`×711、`hint`×85、`jname`×14、`exp`×6、`initial`×3、`name`×2、`label_ok`×1、`label_cancel`×1。

## 2. 目標與非目標

**目標**：抽取／回寫標籤行中「白名單屬性」的日文顯示文字，復用既有 Pipeline，對所有 Tyrano 遊戲受用；且**絕不翻壞遊戲**（不碰識別字、程式碼、變數運算式）。

**非目標**：
- 翻 `&` 變數運算式內的字串字面（如 `text="&'ワイン'+f.item…"`）——屬更難的另案。
- 翻烤進圖片的按鈕文字（如 `回想する` 若為 `button_memory.png`）——屬 OCR/改圖（P2）。
- 單引號屬性 `'…'`、值內含跳脫引號 `\"` 的極端情況（延續現有限制）。

## 3. 設計

只改 `adapters/tyrano/ks.py`；`extract_segments` 與 `apply_translations` 各新增一個「標籤行」分支。`adapters/tyrano/deploy.py` 的 `translate_tree` 自動受惠，不需改動。

### 3.1 新常數

```python
# 白名單：標籤屬性中屬「玩家可見顯示文字」者才翻。刻意排除：
#   name（角色/物件識別字，翻了會壞，見既有註解）、exp（JS 運算式/程式碼）、
#   jname/initial（存疑，先不納入）、storage/target/graphic/cond/role…（結構屬性）。
_TEXT_ATTRS = {"text", "hint", "label", "label_ok", "label_cancel"}
# 標籤屬性比對：屬性名（字母/底線）= 雙引號值。簡單版，不處理值內 \" 跳脫。
_ATTR_RE = re.compile(r'([a-zA-Z_]+)="([^"]*)"')
```

### 3.2 行分類（新增第三類）

去頭尾空白後的 `stripped`，判定順序：
1. **資料陣列行**（`^\s*\[\s*\d`）→ 既有引號內容處理（不變）。
2. **標籤行**（`stripped` 以 `[` 開頭，且非資料陣列行）→ **新增**：掃白名單屬性顯示文字。
3. **純文字行**（`_is_translatable_line` 為真）→ 既有核心文字處理（不變）。
4. 其餘 → 跳過（不變）。

> 註：純文字行不以 `[` 開頭，故與標籤行互斥；資料陣列行在第 1 步已攔截。行內「多屬性／多標籤」由 `_ATTR_RE` 全域掃描一次處理。

### 3.3 抽取（`extract_segments` 新分支）

對標籤行，逐一 `_ATTR_RE.findall`，收錄符合全部條件者：`attr.lower() in _TEXT_ATTRS` ∧ `value` 非空 ∧ `not value.startswith("&")` ∧ `_JP_CJK_RE.search(value)`。收進 segments（值本身為 key）。

### 3.4 回寫（`apply_translations` 新分支）

對標籤行，用 `_ATTR_RE.sub` 逐一比對：符合上述條件且 `mapping.get(value)` 有非空、≠原文的譯文時，替換為 `attr="譯文"`；否則原樣保留 `m.group(0)`。其餘結構、換行原樣保留（比照既有資料陣列行回寫）。

### 3.5 安全性總結

- 只翻白名單屬性 → `name`（識別字）、`exp`（程式碼）天然排除。
- `&` 開頭值（變數運算式）一律跳過 → 不破壞 JS 表達式。
- 只碰雙引號、值含日文者 → 不動英數 ID、座標、檔名。

## 4. 測試策略（TDD、pytest 全綠再交付）

於 `tests/test_tyrano_ks.py` 補：

- **抽取**：
  - `[dialog text="日文" target="x"]` → 只出 `["日文"]`（`target` 不出）。
  - `[chara_part name="夢乃"]` → 空（`name` 排除）。
  - `[glink text="&f.chara_name[0][1]"]` → 空（`&` 跳過）。
  - `[button text="回想" hint="說明文"]` → 出 `text` 與 `hint` 兩者。
  - 一行多標籤 `[a text="甲"][b text="乙"]` → 出 `["甲","乙"]`。
  - 值無日文 `text="OK"` → 空。
- **回寫**：
  - `text="日文"` 有 mapping → 換譯文；`name="夢乃"`、`target="x"`、`text="&f.x"` → 不動；結構/換行保留。
  - mapping 無對應／空／等於原文 → 原樣保留。
- **回歸**：既有純文字行、資料陣列行、結尾標籤、縮排保留等測試全數不變。

## 5. 套用與驗收

- 工具更新後，對已部署的 Tyrano 遊戲**重跑一次翻譯部署**，標籤屬性日文（如 `[dialog text="直前に…"]`）即被翻到。
- 實機驗收：確認讀取確認框、glink/button 的顯示文字變中文；`回想する`（烤圖）仍為已知限制。
- 報告寫 `.superpowers/sdd/`（gitignored）。

## 6. 風險與對策

| 風險 | 對策 |
|---|---|
| 翻到不該翻的屬性（ID/程式碼）弄壞遊戲 | 屬性**白名單**（只 text/hint/label*）；`name`/`exp` 天然排除；`&` 運算式跳過 |
| 值內含跳脫引號 `\"` 斷字 | 延續既有限制，記錄；實機罕見 |
| 白名單漏收某些顯示屬性（如 `jname`） | 保守起步，日後憑實測再加；漏收＝維持未翻，不會弄壞 |
| 誤把「像屬性」的純文字行當標籤處理 | 標籤分支僅作用於 `stripped` 以 `[` 開頭者；純文字行不以 `[` 開頭，互斥 |
