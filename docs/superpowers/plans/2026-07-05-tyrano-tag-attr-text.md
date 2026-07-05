# TyranoScript 標籤屬性顯示文字翻譯 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓 Tyrano 抽取器也能翻「`[標籤]` 屬性裡的顯示文字」（`text`/`hint`/`label`/`label_ok`/`label_cancel`），補上目前整行跳過標籤所漏的 UI 文字。

**Architecture:** 只改 `adapters/tyrano/ks.py`：`extract_segments` 與 `apply_translations` 各加一個「標籤行」分支，掃白名單屬性中「含日文、非 `&` 變數運算式」的雙引號值。`deploy.py` 自動受惠。

**Tech Stack:** Python 3.10、re、pytest。

## Global Constraints

- **全程繁體中文**（程式碼註解、commit 訊息、回報）。
- **禁止自動 `git commit`/`git push`**：commit 步驟須先取得使用者當次明確同意（鐵則 #2）；commit 訊息**不得含任何人名**、結尾加 `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`。
- Python 一律 `.\.venv\Scripts\python.exe`；測試 `-m pytest -q`；**pytest 全綠再交付**；小步 TDD。
- **只動 `adapters/tyrano/ks.py` 與 `tests/test_tyrano_ks.py`**；不改 `deploy.py` 等其他檔。
- **白名單固定為 `{text, hint, label, label_ok, label_cancel}`**；`name`/`exp`/`jname`/`initial` 等**不得**納入。
- **值以 `&` 開頭者一律跳過**（變數運算式，翻了會壞 JS）；只碰雙引號、值含日文者。
- 既有 Tyrano 純文字行／資料陣列行測試**不得被破壞**。

---

### Task 1: 標籤屬性顯示文字的抽取與回寫

**Files:**
- Modify: `adapters/tyrano/ks.py`（加常數；`extract_segments`、`apply_translations` 各加一分支）
- Test: `tests/test_tyrano_ks.py`（既有檔，補測試）

**Interfaces:**
- Consumes: 既有 `extract_segments(ks_text) -> list[str]`、`apply_translations(ks_text, mapping) -> str`、常數 `_JP_CJK_RE`、`_is_data_array_line`、`_is_translatable_line`。
- Produces: 上述兩函式對「標籤行白名單屬性」多出抽取/回寫能力；新增模組層級 `_TEXT_ATTRS`、`_ATTR_RE`。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_tyrano_ks.py` 末端加入：

```python
from adapters.tyrano.ks import extract_segments, apply_translations


def test_extract_tag_attr_whitelisted_display_text():
    ks = '[dialog type="confirm" text="直前にプレイしたデータをロードします" target="autoload_ok"]\n'
    segs = extract_segments(ks)
    assert "直前にプレイしたデータをロードします" in segs
    assert "autoload_ok" not in segs  # target 非白名單，不抽
    assert "confirm" not in segs      # type 非白名單，不抽


def test_extract_tag_attr_excludes_name_and_expr_and_ascii():
    # name（角色識別字）不抽；& 變數運算式不抽；無日文值不抽
    assert extract_segments('[chara_part name="夢乃" text="こんにちは"]\n') == ["こんにちは"]
    assert extract_segments('[glink text="&f.chara_name[0][1]"]\n') == []
    assert extract_segments('[button text="OK"]\n') == []


def test_extract_tag_attr_multiple_attrs_and_tags():
    assert extract_segments('[button text="回想" hint="說明する"]\n') == ["回想", "說明する"]
    assert extract_segments('[a text="甲する"][b label="乙する"]\n') == ["甲する", "乙する"]


def test_apply_tag_attr_replaces_only_whitelisted():
    ks = '[dialog text="直前にプレイしたデータをロードします" label_ok="はい" target="ok"]\n'
    mapping = {"直前にプレイしたデータをロードします": "讀取剛剛遊玩的存檔？", "はい": "是"}
    out = apply_translations(ks, mapping)
    assert 'text="讀取剛剛遊玩的存檔？"' in out
    assert 'label_ok="是"' in out
    assert 'target="ok"' in out  # 結構屬性原樣保留


def test_apply_tag_attr_leaves_name_and_expr_untouched():
    ks = '[chara_part name="夢乃" text="こんにちは"][glink text="&f.x"]\n'
    mapping = {"夢乃": "夢乃譯", "こんにちは": "你好", "&f.x": "壞掉"}
    out = apply_translations(ks, mapping)
    assert 'name="夢乃"' in out      # name 不碰（即使 mapping 有）
    assert 'text="你好"' in out       # text 白名單 → 翻
    assert 'text="&f.x"' in out       # & 運算式不碰


def test_apply_tag_attr_no_mapping_keeps_original():
    ks = '[dialog text="未翻的日文"]\n'
    assert apply_translations(ks, {}) == ks  # 無對應 → 原樣保留
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_tyrano_ks.py -q`
Expected: 新測試 FAIL（標籤行目前被整行跳過，`text=` 等不會被抽/翻）

- [ ] **Step 3: 寫實作**

在 `adapters/tyrano/ks.py`：

3a) 於既有常數區（`_QUOTED_STR_RE = ...` 之後）新增：

```python
# 標籤屬性白名單：只翻屬「玩家可見顯示文字」的屬性。刻意排除 name（識別字）、
# exp（JS 運算式）、jname/initial（存疑）、storage/target/graphic/cond/role… 等結構屬性。
_TEXT_ATTRS = {"text", "hint", "label", "label_ok", "label_cancel"}
# 標籤屬性比對：屬性名（字母/底線）= 雙引號值。簡單版，不處理值內 \" 跳脫。
_ATTR_RE = re.compile(r'([a-zA-Z_]+)="([^"]*)"')


def _is_translatable_attr_value(attr: str, value: str) -> bool:
    """標籤屬性值是否為「該翻的日文顯示文字」：屬性在白名單、值非空、
    不以 & 開頭（變數運算式）、且含日文假名/CJK。"""
    return (attr.lower() in _TEXT_ATTRS and bool(value)
            and not value.startswith("&") and bool(_JP_CJK_RE.search(value)))
```

3b) 於 `extract_segments` 迴圈中，在「資料陣列行分支」之後、`if not _is_translatable_line(stripped):` 之前，插入標籤行分支：

```python
        # 標籤行（以 [ 開頭、非資料陣列行）：抽白名單屬性中的日文顯示文字。
        # 純文字行不以 [ 開頭，故互斥；資料陣列行已於上方攔截。
        if stripped.startswith("["):
            for attr, value in _ATTR_RE.findall(stripped):
                if _is_translatable_attr_value(attr, value):
                    segments.append(value)
            continue
```

3c) 於 `apply_translations` 迴圈中，在「資料陣列行分支」之後、`if not _is_translatable_line(stripped):` 之前，插入標籤行分支：

```python
        # 標籤行：只替換白名單屬性的日文顯示文字，其餘屬性/結構原樣保留。
        if stripped.startswith("["):

            def _replace_attr(m: "re.Match[str]") -> str:
                attr, value = m.group(1), m.group(2)
                if _is_translatable_attr_value(attr, value):
                    translation = mapping.get(value)
                    if translation and translation != value:
                        return f'{attr}="{translation}"'
                return m.group(0)

            new_body = _ATTR_RE.sub(_replace_attr, body)
            out_lines.append(f"{new_body}{newline}")
            continue
```

- [ ] **Step 4: 執行測試確認通過 + 全套無回歸**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_tyrano_ks.py -q`
Expected: PASS（新 6 測試 + 既有 tyrano ks 測試全綠）

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: 全套 PASS（`test_server.py` 偶發 Windows socket flaky，單獨重跑即綠）

- [ ] **Step 5: Commit（先取得使用者明確同意）**

```bash
git add adapters/tyrano/ks.py tests/test_tyrano_ks.py
git commit -m "feat: Tyrano 抽取器支援標籤屬性顯示文字（text/hint/label 白名單）"
```

---

## 驗收清單

- [ ] `pytest -q` 全綠（新增 6 測試 + 既有）。
- [ ] 白名單只含 `{text, hint, label, label_ok, label_cancel}`；`name`/`exp`/`&運算式` 確認不被翻。
- [ ] 既有純文字行／資料陣列行行為未變（回歸測試綠）。
- [ ] （套用）對實體 Tyrano 遊戲重跑部署後，`[dialog text="…"]` 等標籤顯示文字變中文。
