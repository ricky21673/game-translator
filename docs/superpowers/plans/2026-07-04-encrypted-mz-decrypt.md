# 加密 RPG Maker MZ 支援 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 讓工具能對「檔案加密的 RPG Maker MZ」（如 `ゆうべは大変おたのしみでしたね。`）部署時解密、抽字、以 Sakura 批次預翻建立完整離線字典，達成全款翻譯覆蓋。

**Architecture:** 新增純函式的解密器（`core/mz_decrypt.py`）與抽取器（`core/mz_extract.py`）；用一個「控制碼保護」翻譯器裝飾器（`core/translators/protect.py`）包住現有引擎以保住 `\FS[28]` 等控制碼；偵測器加 `encrypted` 旗標；新增 `adapters/mz/pretranslate.py` orchestration 把「解密→抽取→Pipeline 批次翻」串起來填滿 cache；GUI 比照 Tyrano 用背景 QThread 跑預翻並接監控面板，最後沿用既有 `deploy_mv_adapter` 離線嵌入。執行期完全靠遊戲自解密 + 既有 hook 查表，`data/*.json` 零改動。

**Tech Stack:** Python 3.10、PySide6、pytest；復用 `core/pipeline.py`、`launcher.deploy_mv_adapter`、`gui/monitor.py`。

## Global Constraints

- **全程繁體中文**（程式碼註解、commit 訊息、回報一律繁中）。
- **禁止自動 `git commit`/`git push`**：本計畫每個「Commit」步驟都**必須先取得使用者當次明確同意**才執行（使用者鐵則 #2）。Staging/diff 可，commit 不可自作主張。
- **commit 訊息與註解不得出現任何人名**（使用者鐵則）。
- Python 直譯器一律用 `.\.venv\Scripts\python.exe`；測試 `-m pytest -q`；打包 `-m PyInstaller GameTranslator.spec`。
- **pytest 全綠再交付**；小步 TDD。
- **不得把遊戲內容（H 同人）commit 進 repo**：解密/抽取測試一律用「測試內自製明文 → 同演算法加密 → 解密還原」的 round-trip fixture；對真實遊戲僅用 `skipif`（本機路徑存在才跑）smoke test，不入庫任何檔案。
- **`data/*.json` 永不修改**：執行期靠遊戲自解密 + 既有 hook 查表替換；我方解密只在部署時用於「讀原文建字典」。
- 復用既有 `Pipeline`、`deploy_mv_adapter`、監控面板；不重造。
- 解密器：通用偵測 `{uid,bid,data}` 格式 + 自動爆破 `_K`（0–255）；演算法常數以 `scheme` 收斂，預設 `bid_1.8.1`。

---

### Task 1: 加密 MZ 解密器 `core/mz_decrypt.py`

**Files:**
- Create: `core/mz_decrypt.py`
- Test: `tests/test_mz_decrypt.py`

**Interfaces:**
- Produces:
  - `is_encrypted_mz(obj: dict) -> bool`
  - `decrypt(data_b64: str, filename: str, key: int, scheme: str = "bid_1.8.1") -> dict`
  - `detect_key(sample_data_b64: str, filename: str, scheme: str = "bid_1.8.1") -> int | None`
  - `_filename_hash`, `_keystream_byte`, `_decrypt_bytes`, `_norm_name`（內部；供測試建 round-trip fixture 用）
- Consumes: 無（純標準庫）。

演算法（已對實體遊戲驗證）：每個 data 檔為 `{"uid":…,"bid":…,"data":"<base64>"}`；金鑰種子 `key`（此款 `_K=226`）；`fk = key XOR (filenameHash & 0xFF)`；反向逐位元組、以前一個明文位元組回饋解密。

- [ ] **Step 1: 寫失敗測試（round-trip + detect_key + is_encrypted_mz）**

在 `tests/test_mz_decrypt.py`：

```python
import base64
import json

from core import mz_decrypt as mz


def _encrypt(obj, filename, key, scheme="bid_1.8.1"):
    """測試專用：用與解密相同的演算法，把明文 JSON 加密成 base64（建 fixture 用）。"""
    s = mz._SCHEMES[scheme]
    plain = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    p = bytearray(plain)
    fk = (key ^ (mz._filename_hash(mz._norm_name(filename)) & 0xFF)) & 0xFF
    ct = bytearray(len(p))
    for i in range(len(p)):
        ls = fk if i == len(p) - 1 else p[i + 1]
        ct[i] = p[i] ^ mz._keystream_byte(fk, i, ls, s)
    return base64.b64encode(bytes(ct)).decode("ascii")


def test_decrypt_round_trip_recovers_japanese():
    obj = {"events": [None, {"pages": [{"list": [
        {"code": 401, "parameters": ["\\FS[28]暗闇の中その小さな穴をみる。"]},
    ]}]}]}
    data_b64 = _encrypt(obj, "Map018.json", 226)
    assert mz.decrypt(data_b64, "Map018.json", 226) == obj


def test_detect_key_finds_the_key():
    obj = {"name": "ゼシカ", "profile": "宿屋の受付"}
    data_b64 = _encrypt(obj, "Actors.json", 226)
    assert mz.detect_key(data_b64, "Actors.json") == 226


def test_detect_key_returns_none_on_garbage():
    assert mz.detect_key(base64.b64encode(b"\x00\x01\x02\x03" * 8).decode(),
                         "Map001.json") is None


def test_is_encrypted_mz():
    assert mz.is_encrypted_mz({"uid": "x", "bid": "1.8.1", "data": "abc"}) is True
    assert mz.is_encrypted_mz({"events": []}) is False
    assert mz.is_encrypted_mz({"uid": "x", "bid": "1.8.1", "data": ""}) is False
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_decrypt.py -q`
Expected: FAIL（`ModuleNotFoundError: core.mz_decrypt` 或 `AttributeError`）

- [ ] **Step 3: 寫最小實作**

`core/mz_decrypt.py`：

```python
import base64
import json
import os

# 各加密器 scheme 的常數。日後遇到別的 bid/加密器在此加一組即可，主流程不動。
_SCHEMES = {
    "bid_1.8.1": {"c_xor": 23, "k_xor": 186, "k_add": 33, "mod": 128},
}


def is_encrypted_mz(obj) -> bool:
    """判斷是否為加密 MZ data 結構：同時含 uid/bid，且 data 為非空字串。"""
    return (isinstance(obj, dict)
            and "uid" in obj and "bid" in obj
            and isinstance(obj.get("data"), str) and obj["data"] != "")


def _norm_name(filename: str) -> str:
    """與遊戲一致：去路徑、去 .json、轉小寫（金鑰依此檔名派生）。"""
    base = os.path.basename(filename)
    if base.lower().endswith(".json"):
        base = base[:-5]
    return base.lower()


def _filename_hash(name: str) -> int:
    """JS: t = ((t<<5) - t + charCode) | 0；此處以 32 位遮罩對齊。"""
    t = 0
    for ch in name:
        t = ((t << 5) - t + ord(ch)) & 0xFFFFFFFF
    return t


def _keystream_byte(fk: int, i: int, ls: int, s: dict) -> int:
    """單一位元組的金鑰流；ls 為回饋值（前一個已解出的明文位元組）。"""
    c = fk ^ s["c_xor"]
    p = (ls << 2) ^ (ls >> 3)
    return (((c + (i % s["mod"]) + p) ^ s["k_xor"]) + s["k_add"]) & 0xFF


def _decrypt_bytes(cipher: bytes, norm_name: str, key: int, s: dict) -> bytes:
    b = bytearray(cipher)
    fk = (key ^ (_filename_hash(norm_name) & 0xFF)) & 0xFF
    ls = fk
    for i in range(len(b) - 1, -1, -1):
        v = b[i] ^ _keystream_byte(fk, i, ls, s)
        b[i] = v
        ls = v
    return bytes(b)


def decrypt(data_b64: str, filename: str, key: int, scheme: str = "bid_1.8.1") -> dict:
    """解密單一 data 檔的 base64 內容，回傳 json.loads 後的物件。"""
    s = _SCHEMES[scheme]
    raw = _decrypt_bytes(base64.b64decode(data_b64), _norm_name(filename), key, s)
    return json.loads(raw.decode("utf-8"))


def detect_key(sample_data_b64: str, filename: str, scheme: str = "bid_1.8.1"):
    """自動爆破 _K：0–255 全試，取「解出合法 UTF-8 且 json 可 parse」者；找不到回 None。"""
    s = _SCHEMES[scheme]
    cipher = base64.b64decode(sample_data_b64)
    norm = _norm_name(filename)
    for key in range(256):
        try:
            raw = _decrypt_bytes(cipher, norm, key, s)
            json.loads(raw.decode("utf-8"))
            return key
        except (UnicodeDecodeError, ValueError):
            continue
    return None
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_decrypt.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5:（可選）加真檔 skipif smoke test**

在 `tests/test_mz_decrypt.py` 末端加（指向本機遊戲、不入庫；路徑不存在就跳過）：

```python
import os as _os
import pytest

_GAME = r"D:\7-Zip\tmp\ゆうべは大変おたのしみでしたね。"


@pytest.mark.skipif(not _os.path.isdir(_GAME), reason="需本機實體遊戲，非 CI")
def test_real_game_decrypts_to_japanese():
    with open(_os.path.join(_GAME, "data", "Map003.json"), encoding="utf-8") as f:
        c = json.load(f)
    key = mz.detect_key(c["data"], "Map003.json")
    assert key == 226
    obj = mz.decrypt(c["data"], "Map003.json", key)
    blob = json.dumps(obj, ensure_ascii=False)
    assert "空室" in blob  # 該圖已知日文片段
```

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_decrypt.py -q`
Expected: PASS（本機 5 passed；CI 上該項 skipped）

- [ ] **Step 6: Commit（先取得使用者明確同意）**

```bash
git add core/mz_decrypt.py tests/test_mz_decrypt.py
git commit -m "feat: 加密 MZ data 解密器（自動爆破 _K + round-trip 測試）"
```

---

### Task 2: MZ 文字抽取器 `core/mz_extract.py`

**Files:**
- Create: `core/mz_extract.py`
- Test: `tests/test_mz_extract.py`

**Interfaces:**
- Produces:
  - `has_japanese(s: str) -> bool`
  - `extract_strings(data_name: str, data_obj) -> list[str]`（依檔名分派，回傳去重前的可翻字串清單，僅含日文者）
- Consumes: 無。

規則：事件指令中連續 `401` 分組成一則訊息（以 `\n` 串接、對齊執行期 `convertEscapeCharacters` 所見）；`405` 逐則；`102` 選項逐項；`402` 選項分支文字。資料庫檔取 `name/nickname/description/profile/message1..4`；System 取 `terms`（basic/commands/params/messages）與 `gameTitle`。一律只保留含假名/漢字者。

- [ ] **Step 1: 寫失敗測試**

`tests/test_mz_extract.py`：

```python
from core import mz_extract as ex


def test_has_japanese():
    assert ex.has_japanese("暗闇の中")
    assert ex.has_japanese("\\FS[28]んっ…♥")
    assert not ex.has_japanese("\\FS[28][0]")
    assert not ex.has_japanese("ABC123")


def test_extract_map_groups_consecutive_401():
    data = {"events": [None, {"pages": [{"list": [
        {"code": 101, "parameters": ["", 0, 0, 2]},
        {"code": 401, "parameters": ["\\FS[28]かすかな音から起こっている事に"]},
        {"code": 401, "parameters": ["確信めいたものを感じる。"]},
        {"code": 102, "parameters": [["はい", "いいえ"], 0]},
        {"code": 401, "parameters": ["別のメッセージ。"]},
    ]}]}]}
    got = ex.extract_strings("Map018.json", data)
    assert "\\FS[28]かすかな音から起こっている事に\n確信めいたものを感じる。" in got
    assert "はい" in got and "いいえ" in got
    assert "別のメッセージ。" in got


def test_extract_database_names_and_descriptions():
    data = [None,
            {"name": "ゼシカ", "nickname": "", "description": "", "profile": "宿屋の受付"},
            {"name": "エイト", "description": "勇者", "profile": ""}]
    got = ex.extract_strings("Actors.json", data)
    assert "ゼシカ" in got and "エイト" in got
    assert "宿屋の受付" in got and "勇者" in got


def test_extract_system_terms():
    data = {"gameTitle": "ゆうべ", "terms": {"commands": ["攻撃", "", "防御"],
            "basic": ["レベル"], "params": [], "messages": {"actionFailure": "ミス！"}}}
    got = ex.extract_strings("System.json", data)
    assert "攻撃" in got and "防御" in got and "レベル" in got and "ミス！" in got


def test_extract_skips_non_japanese():
    data = {"events": [None, {"pages": [{"list": [
        {"code": 401, "parameters": ["\\SE[0]\\W[1,0]"]},
    ]}]}]}
    assert ex.extract_strings("Map001.json", data) == []
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_extract.py -q`
Expected: FAIL（`ModuleNotFoundError: core.mz_extract`）

- [ ] **Step 3: 寫最小實作**

`core/mz_extract.py`：

```python
import re

# 假名（U+3040–30FF）與常用漢字（U+4E00–9FFF）
_JP_RE = re.compile("[぀-ヿ一-鿿]")


def has_japanese(s) -> bool:
    return isinstance(s, str) and bool(_JP_RE.search(s))


def _extract_event_list(cmds, out):
    """處理單一事件指令陣列：連續 401 分組、405/102/402 個別處理。"""
    buf = []
    for cmd in cmds or []:
        code = cmd.get("code")
        params = cmd.get("parameters") or []
        if code == 401:
            buf.append(params[0] if params and isinstance(params[0], str) else "")
            continue
        if buf:
            out.append("\n".join(buf))
            buf = []
        if code == 405:
            if params and isinstance(params[0], str):
                out.append(params[0])
        elif code == 102 and params and isinstance(params[0], list):
            for choice in params[0]:
                if isinstance(choice, str):
                    out.append(choice)
        elif code == 402 and len(params) >= 2 and isinstance(params[1], str):
            out.append(params[1])
    if buf:
        out.append("\n".join(buf))


def _extract_events(events, out):
    for ev in events or []:
        if not ev:
            continue
        for pg in ev.get("pages") or []:
            _extract_event_list(pg.get("list"), out)


def _extract_map(obj, out):
    _extract_events(obj.get("events"), out)


def _extract_common_events(obj, out):
    for ce in obj or []:
        if ce:
            _extract_event_list(ce.get("list"), out)


def _extract_troops(obj, out):
    for tr in obj or []:
        if not tr:
            continue
        for pg in tr.get("pages") or []:
            _extract_event_list(pg.get("list"), out)


_DB_FIELDS = ("name", "nickname", "description", "profile",
              "message1", "message2", "message3", "message4")


def _extract_database(obj, out):
    for row in obj or []:
        if not isinstance(row, dict):
            continue
        for f in _DB_FIELDS:
            v = row.get(f)
            if isinstance(v, str):
                out.append(v)


def _extract_system(obj, out):
    out.append(obj.get("gameTitle", ""))
    terms = obj.get("terms") or {}
    for key in ("basic", "commands", "params"):
        for v in terms.get(key) or []:
            if isinstance(v, str):
                out.append(v)
    for v in (terms.get("messages") or {}).values():
        if isinstance(v, str):
            out.append(v)


def extract_strings(data_name: str, data_obj) -> list:
    """依 data 檔名分派抽取，回傳僅含日文的可翻字串（未去重，順序穩定）。"""
    out = []
    base = data_name.rsplit(".", 1)[0]
    if base.startswith("Map") and base != "MapInfos":
        _extract_map(data_obj, out)
    elif base == "CommonEvents":
        _extract_common_events(data_obj, out)
    elif base == "Troops":
        _extract_troops(data_obj, out)
    elif base == "System":
        _extract_system(data_obj, out)
    else:
        _extract_database(data_obj, out)
    return [s for s in out if has_japanese(s)]
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_extract.py -q`
Expected: PASS（5 passed）

- [ ] **Step 5: Commit（先取得使用者明確同意）**

```bash
git add core/mz_extract.py tests/test_mz_extract.py
git commit -m "feat: MZ data 文字抽取器（訊息分組 + 資料庫/System 詞條）"
```

---

### Task 3: 控制碼保護翻譯器 `core/translators/protect.py`

**Files:**
- Create: `core/translators/protect.py`
- Test: `tests/test_protect.py`

**Interfaces:**
- Consumes: `core.translators.base.Translator`（既有抽象；`translate(texts, target_lang, source_lang=None) -> list[str]`）
- Produces: `ControlCodeTranslator(inner: Translator)`，同樣實作 `translate(...)`；送翻前把 `\XX`/`\XX[...]` 控制碼換成不易被模型改動的 placeholder、翻完還原。還原採 best-effort：placeholder 遺失就保留模型輸出。

- [ ] **Step 1: 寫失敗測試**

`tests/test_protect.py`：

```python
from core.translators.protect import ControlCodeTranslator, _mask, _restore


class _FakeInner:
    """把送進來的（已遮罩）文字原樣回傳，模擬「保留 placeholder」的理想模型。"""
    def __init__(self):
        self.seen = None

    def translate(self, texts, target_lang, source_lang=None):
        self.seen = list(texts)
        return list(texts)


def test_mask_restore_round_trip():
    s = "\\SE[0]\\W[1,0]\\FS[28]んっ…\\FS[24]んんっ…♥"
    masked, tokens = _mask(s)
    assert "\\FS" not in masked          # 控制碼已被遮罩
    assert "んっ" in masked              # 日文保留
    assert _restore(masked, tokens) == s


def test_wrapper_masks_before_inner_and_restores_after():
    inner = _FakeInner()
    w = ControlCodeTranslator(inner)
    out = w.translate(["\\FS[28]あ", "\\SE[0]い"], "ZH")
    # 送進 inner 的是遮罩後、不含反斜線控制碼的字串
    assert all("\\FS" not in t and "\\SE" not in t for t in inner.seen)
    # 還原後控制碼回來了
    assert out == ["\\FS[28]あ", "\\SE[0]い"]


def test_restore_is_best_effort_when_placeholder_dropped():
    # 模型把 placeholder 弄丟時，不應炸掉，回傳去掉該碼的結果
    masked, tokens = _mask("\\FS[28]あ")
    assert _restore("あ", tokens) == "あ"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_protect.py -q`
Expected: FAIL（`ModuleNotFoundError: core.translators.protect`）

- [ ] **Step 3: 寫最小實作**

`core/translators/protect.py`：

```python
import re

from .base import Translator

# 比對 RPG Maker 控制碼：反斜線 + 字母，後面可帶 [ ... ]。例：\FS[28]、\SE[0]、\|、\.
_CONTROL_RE = re.compile(r"\\(?:[A-Za-z]+(?:\[[^\]]*\])?|[|.^!<>$])")

# placeholder 用私有區字元包住序號，模型幾乎不會動到它，也不含反斜線/日文。
_PH_L = "\uE000"
_PH_R = "\uE001"


def _mask(s: str):
    """把控制碼換成 placeholder，回傳 (masked, tokens)；tokens[i] 為第 i 個控制碼原字串。"""
    tokens = []

    def repl(m):
        tokens.append(m.group(0))
        return "%s%d%s" % (_PH_L, len(tokens) - 1, _PH_R)

    return _CONTROL_RE.sub(repl, s), tokens


def _restore(s: str, tokens) -> str:
    """把 placeholder 還原成控制碼；找不到的 placeholder（模型弄丟）就略過。"""
    def repl(m):
        idx = int(m.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else ""
    return re.sub(_PH_L + r"(\d+)" + _PH_R, repl, s)


class ControlCodeTranslator(Translator):
    """裝飾器：包住任一翻譯引擎，送翻前遮罩控制碼、翻完還原。keying 不受影響
    （Pipeline 仍以原字串為 key）。"""

    def __init__(self, inner: Translator):
        self.inner = inner

    def translate(self, texts, target_lang, source_lang=None):
        masked, token_lists = [], []
        for t in texts:
            m, toks = _mask(t)
            masked.append(m)
            token_lists.append(toks)
        out = self.inner.translate(masked, target_lang, source_lang)
        return [_restore(o, toks) for o, toks in zip(out, token_lists)]
```

> 註：`core/translators/base.py` 的 `Translator` 若為抽象基底，`ControlCodeTranslator` 需實作其抽象方法 `translate`（已實作）。若基底建構子有必要參數，於 `__init__` 不呼叫 `super().__init__()` 即可（本裝飾器不需基底狀態）。

- [ ] **Step 4: 執行測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_protect.py -q`
Expected: PASS（3 passed）

- [ ] **Step 5: Commit（先取得使用者明確同意）**

```bash
git add core/translators/protect.py tests/test_protect.py
git commit -m "feat: 控制碼保護翻譯器裝飾器（遮罩/還原 RPG Maker 控制碼）"
```

---

### Task 4: 偵測器加 `encrypted` 旗標

**Files:**
- Modify: `core/detector.py`（`Detection` dataclass 加欄位；`detect()` MZ 分支 peek 一個 data 檔）
- Test: `tests/test_detector.py`（既有檔，補測試）

**Interfaces:**
- Produces: `Detection.encrypted: bool = False`（向後相容預設 False）；MZ 且 `data/*.json` 首個檔為 `{uid,bid,data}` 時為 True。
- Consumes: `core.mz_decrypt.is_encrypted_mz`（Task 1）。

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_detector.py` 末端加：

```python
import json as _json


def _make_mz(tmp_path, data_files):
    js = tmp_path / "js"
    js.mkdir()
    (js / "rmmz_core.js").write_text("// core", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    for name, content in data_files.items():
        (data / name).write_text(_json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return str(tmp_path / "Game.exe")


def test_detect_mz_plain_is_not_encrypted(tmp_path):
    from core.detector import detect
    exe = _make_mz(tmp_path, {"Map001.json": {"events": []}})
    d = detect(exe)
    assert d.engine == "mz"
    assert d.encrypted is False


def test_detect_mz_encrypted_flag(tmp_path):
    from core.detector import detect
    exe = _make_mz(tmp_path, {"Map001.json": {"uid": "x", "bid": "1.8.1", "data": "QUJD"}})
    d = detect(exe)
    assert d.engine == "mz"
    assert d.encrypted is True
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_detector.py -q`
Expected: FAIL（`Detection` 無 `encrypted` 屬性 / 值不符）

- [ ] **Step 3: 寫最小實作**

在 `core/detector.py`：

1) `Detection` 加欄位（在 `web_dir` 之後）：

```python
    web_dir: str | None = None
    encrypted: bool = False
```

2) 於 MZ 命中的兩處 `return Detection("mz", ...)` 改為先算 `encrypted` 再回傳。將原本：

```python
        if os.path.isfile(os.path.join(js_dir, "rmmz_core.js")):
            www = base if os.path.basename(base) == "www" else None
            return Detection("mz", game_dir, www, js_dir, os.path.dirname(js_dir))
```

改為：

```python
        if os.path.isfile(os.path.join(js_dir, "rmmz_core.js")):
            www = base if os.path.basename(base) == "www" else None
            web_dir = os.path.dirname(js_dir)
            return Detection("mz", game_dir, www, js_dir, web_dir,
                             encrypted=_mz_data_encrypted(web_dir))
```

3) 檔案頂端 import 與新輔助函式：

```python
from .mz_decrypt import is_encrypted_mz
```

```python
def _mz_data_encrypted(web_dir: str) -> bool:
    """peek data/ 內第一個 *.json（跳過空/損毀檔），判斷是否為加密 MZ 格式。"""
    import glob
    for path in sorted(glob.glob(os.path.join(web_dir, "data", "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        return is_encrypted_mz(obj)
    return False
```

（`core/detector.py` 頂端已 `import os`；需補 `import json`。）

- [ ] **Step 4: 執行測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_detector.py -q`
Expected: PASS（含既有測試全綠）

- [ ] **Step 5: Commit（先取得使用者明確同意）**

```bash
git add core/detector.py tests/test_detector.py
git commit -m "feat: 偵測器辨識加密 MZ（Detection.encrypted 旗標）"
```

---

### Task 5: 加密 MZ 批次預翻 orchestration `adapters/mz/pretranslate.py`

**Files:**
- Create: `adapters/mz/pretranslate.py`
- Create: `adapters/mz/__init__.py`（若尚不存在）
- Test: `tests/test_mz_pretranslate.py`

**Interfaces:**
- Consumes: `core.mz_decrypt`（Task 1）、`core.mz_extract`（Task 2）、`core.pipeline.Pipeline`（既有；`translate(texts, progress_cb=None)`、`.cache.as_dict()`）
- Produces:
  - `pretranslate_encrypted_mz(web_dir: str, pipeline, progress_cb=None) -> dict`
    解密 `web_dir/data/*.json`、抽字去重、`pipeline.translate(...)` 填滿 cache，回傳 `pipeline.cache.as_dict()`（完整離線字典）。找不到金鑰時 `raise RuntimeError`。**不修改任何 data 檔。**

- [ ] **Step 1: 寫失敗測試**

`tests/test_mz_pretranslate.py`：

```python
import base64
import json

import pytest

from core.cache import DictCache
from core.pipeline import Pipeline
from adapters.mz.pretranslate import pretranslate_encrypted_mz
from tests.test_mz_decrypt import _encrypt  # 復用 round-trip 加密輔助


class _EchoTranslator:
    """把每句翻成「譯:<原文>」，方便驗證。"""
    def translate(self, texts, target_lang, source_lang=None):
        return ["譯:" + t for t in texts]


def _write_encrypted(data_dir, name, obj, key=226):
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {"uid": "u", "bid": "1.8.1", "data": _encrypt(obj, name, key)}
    (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def test_pretranslate_fills_cache_from_encrypted_maps(tmp_path):
    web = tmp_path
    data = web / "data"
    _write_encrypted(data, "Map001.json", {"events": [None, {"pages": [{"list": [
        {"code": 401, "parameters": ["暗闇の中。"]},
    ]}]}]})
    _write_encrypted(data, "Actors.json", [None, {"name": "ゼシカ"}])

    cache = DictCache(str(tmp_path / "translator_dict.json"))
    pipe = Pipeline(cache, _EchoTranslator(), target_lang="ZH", source_lang="JA")
    result = pretranslate_encrypted_mz(str(web), pipe)

    assert result["暗闇の中。"] == "譯:暗闇の中。"
    assert result["ゼシカ"] == "譯:ゼシカ"


def test_pretranslate_raises_when_key_not_found(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "Map001.json").write_text(
        json.dumps({"uid": "u", "bid": "1.8.1",
                    "data": base64.b64encode(b"\x00\x01\x02\x03" * 8).decode()}),
        encoding="utf-8")
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, _EchoTranslator(), target_lang="ZH", source_lang="JA")
    with pytest.raises(RuntimeError):
        pretranslate_encrypted_mz(str(tmp_path), pipe)
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_pretranslate.py -q`
Expected: FAIL（`ModuleNotFoundError: adapters.mz.pretranslate`）

- [ ] **Step 3: 寫最小實作**

`adapters/mz/__init__.py`（若不存在，建空檔）：

```python
```

`adapters/mz/pretranslate.py`：

```python
import glob
import json
import os

from core import mz_decrypt, mz_extract


def pretranslate_encrypted_mz(web_dir: str, pipeline, progress_cb=None) -> dict:
    """解密 web_dir/data/*.json、抽字、以 pipeline 批次預翻填滿 cache，回傳完整字典。

    - 不修改任何 data 檔（只讀）。
    - 找不到可用金鑰時 raise RuntimeError。
    """
    paths = sorted(glob.glob(os.path.join(web_dir, "data", "*.json")))

    # 1) 用第一個加密檔偵測 _K（全庫共用）
    key = None
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if mz_decrypt.is_encrypted_mz(obj):
            key = mz_decrypt.detect_key(obj["data"], os.path.basename(path))
            if key is not None:
                break
    if key is None:
        raise RuntimeError("無法偵測加密金鑰（_K）：可能非 bid_1.8.1 加密或資料異常")

    # 2) 逐檔解密 + 抽字（去重、保留首次出現順序）
    texts, seen = [], set()
    for path in paths:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not mz_decrypt.is_encrypted_mz(obj):
            continue
        try:
            data_obj = mz_decrypt.decrypt(obj["data"], name, key)
        except (ValueError, UnicodeDecodeError):
            # 單檔解密失敗不整批中斷，跳過續跑
            continue
        for s in mz_extract.extract_strings(name, data_obj):
            if s not in seen:
                seen.add(s)
                texts.append(s)

    # 3) 併入遊戲現成 MTool 字典當底（存在才做；已在 cache 者不覆蓋，避免重翻）
    mtool = os.path.join(web_dir, "翻译文件.json")
    if os.path.isfile(mtool):
        try:
            with open(mtool, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if (isinstance(k, str) and isinstance(v, str)
                            and pipeline.cache.get(k) is None):
                        pipeline.cache.put(k, v)
        except (json.JSONDecodeError, OSError, AttributeError):
            pass  # 現成字典損毀/格式非 dict 就略過，不影響主流程

    # 4) 批次預翻（Pipeline 內部邊翻邊存、可續跑），回傳完整字典
    pipeline.translate(texts, progress_cb=progress_cb)
    return pipeline.cache.as_dict()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_mz_pretranslate.py -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit（先取得使用者明確同意）**

```bash
git add adapters/mz/__init__.py adapters/mz/pretranslate.py tests/test_mz_pretranslate.py
git commit -m "feat: 加密 MZ 批次預翻 orchestration（解密→抽字→Pipeline 填字典）"
```

---

### Task 6: GUI 整合（加密 MZ 走背景預翻 + 監控面板 + 離線嵌入）

**Files:**
- Modify: `gui/app.py`（`_on_start_rpgmaker` 分流：`detection.encrypted` 時走背景預翻 worker，接監控面板，完成後 `deploy_mv_adapter` 離線嵌入並啟動）
- Test: `tests/test_gui_state.py`（補純函式分流判斷測試）

**Interfaces:**
- Consumes: `adapters.mz.pretranslate.pretranslate_encrypted_mz`（Task 5）、`core.translators.protect.ControlCodeTranslator`（Task 3）、既有 `deploy_mv_adapter`、`gui/monitor.py`、既有 `TyranoDeployWorker` 執行緒模式。
- Produces: `should_pretranslate_mz(detection, mode) -> bool`（純函式，供分流與測試）。

> 說明：加密 MZ 的離線字典要靠引擎（Sakura/DeepL）預翻填出，故僅在 `mode in ("local", "deepl")` 時走預翻；`mode == "offline"`（只有現成字典、無引擎）則維持既有行為（嵌入現有 cache）。`_build_pipeline` 產生的 translator 在預翻路徑要用 `ControlCodeTranslator` 包一層以保護控制碼。

- [ ] **Step 1: 寫失敗測試（純函式分流）**

在 `tests/test_gui_state.py` 末端加：

```python
def test_should_pretranslate_mz():
    from gui.app import should_pretranslate_mz
    from core.detector import Detection

    enc = Detection("mz", "/g", None, "/g/js", "/g", encrypted=True)
    plain = Detection("mz", "/g", None, "/g/js", "/g", encrypted=False)

    assert should_pretranslate_mz(enc, "local") is True
    assert should_pretranslate_mz(enc, "deepl") is True
    assert should_pretranslate_mz(enc, "offline") is False   # 無引擎，不預翻
    assert should_pretranslate_mz(plain, "local") is False    # 未加密，走既有路徑
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gui_state.py -q`
Expected: FAIL（`ImportError: cannot import name 'should_pretranslate_mz'`）

- [ ] **Step 3: 寫最小實作（純函式）**

在 `gui/app.py` 適當位置（模組層級，靠近 `choose_translator_mode`）加：

```python
def should_pretranslate_mz(detection, mode: str) -> bool:
    """加密 MZ 且選了會翻譯的引擎（local/deepl）時，需先批次預翻建字典。"""
    return (getattr(detection, "encrypted", False)
            and detection.engine == "mz"
            and mode in ("local", "deepl"))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_gui_state.py -q`
Expected: PASS

- [ ] **Step 5: 接上背景預翻流程（比照 Tyrano worker）**

在 `gui/app.py`：

1) 於 `_on_start_rpgmaker` 開頭，讀完 `maps`、建好 `pipe` 後，加入分流（在既有 `offline_dict = ...` 之前）：

```python
            if should_pretranslate_mz(d, mode):
                self._on_start_encrypted_mz(d, pipe)
                return
```

2) 新增背景 worker 與方法（比照既有 `TyranoDeployWorker` 與 `_on_start_tyrano` 的執行緒／signal 收尾寫法；`segment_progress` 接 `self.monitor.set_progress`）：

```python
class EncryptedMzWorker(QObject):
    finished = Signal(dict)          # 回傳完整 offline_dict
    error = Signal(str)
    segment_progress = Signal(int, int)

    def __init__(self, web_dir: str, pipeline):
        super().__init__()
        self.web_dir = web_dir
        self.pipeline = pipeline

    def run(self):
        try:
            from adapters.mz.pretranslate import pretranslate_encrypted_mz
            result = pretranslate_encrypted_mz(
                self.web_dir, self.pipeline,
                progress_cb=lambda done, total: self.segment_progress.emit(done, total))
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 — 背景執行緒需吞例外轉成 error signal
            self.error.emit(str(e))
```

```python
    def _on_start_encrypted_mz(self, d, pipe):
        # 加密 MZ：背景預翻 → 完成後離線嵌入 + 啟動。比照 Tyrano 的執行緒收尾。
        self.start_btn.setEnabled(False)
        self.info.setText("翻譯中（加密 MZ）：解密與預翻…")
        self.monitor.reset()

        thread = QThread()
        worker = EncryptedMzWorker(d.web_dir, pipe)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.segment_progress.connect(self.monitor.set_progress)
        worker.finished.connect(lambda dic: self._on_encrypted_mz_finished(d, dic))
        worker.error.connect(self._on_tyrano_error)   # 復用既有錯誤顯示
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_tyrano_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._tyrano_thread = thread
        self._tyrano_worker = worker
        thread.start()

    def _on_encrypted_mz_finished(self, d, offline_dict):
        try:
            if self.traditional_checkbox.isChecked():
                convert = make_traditional_converter()
                offline_dict = {k: convert(v) for k, v in offline_dict.items()}
            port = self.server.port if self.server else 0
            bridge = resource_path(os.path.join("adapters", "mv", "ZZ_Translator_Bridge.js"))
            deploy_mv_adapter(d.web_dir, port, [], bridge_src=os.path.abspath(bridge),
                              offline_dict=offline_dict)
            if self.auto_launch_checkbox.isChecked():
                launch_game(self.exe_path)
                self.info.setText("已啟動（加密 MZ 離線字典模式）")
            else:
                self.info.setText("已部署（加密 MZ），未啟動")
        except Exception as e:
            self.info.setText(f"部署失敗：{e}")
        finally:
            self.start_btn.setEnabled(True)
```

3) 於 `_build_pipeline` 產生 translator 之後、建立 `Pipeline` 之前，對「加密 MZ 預翻」路徑用 `ControlCodeTranslator` 包住 translator。最小改法：在 `EncryptedMzWorker.run` 前，於 `_on_start_encrypted_mz` 建 worker 時，把 `pipe.translator` 換成包裹版：

```python
        from core.translators.protect import ControlCodeTranslator
        pipe.translator = ControlCodeTranslator(pipe.translator)
```

（置於 `_on_start_encrypted_mz` 開頭、建 worker 之前。）

- [ ] **Step 6: 跑全套測試確認無回歸**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS（既有全部 + 本計畫新增，全綠；`test_server.py` 若偶發 Windows socket flaky 單獨重跑）

- [ ] **Step 7: Commit（先取得使用者明確同意）**

```bash
git add gui/app.py tests/test_gui_state.py
git commit -m "feat: GUI 支援加密 MZ 背景預翻（監控面板 + 離線嵌入 + 控制碼保護）"
```

---

### Task 7: 實機驗收與文件（鐵則 #7）

**Files:**
- Modify: `README.md`（支援矩陣把「加密 MZ」由規劃中移到已支援）
- Modify: `docs/superpowers/specs/2026-07-04-handoff.md`（2.2 標記完成、記錄實測結果）
- 報告：`.superpowers/sdd/`（gitignored）

- [ ] **Step 1: 打包前先跑全測**

Run: `.\.venv\Scripts\python.exe -m pytest -q`
Expected: PASS（全綠）

- [ ] **Step 2: 對實體遊戲部署 + 啟動驗收**

1) 開工具 → 選 `D:\7-Zip\tmp\ゆうべは大変おたのしみでしたね。\Game.exe` → 應顯示「MZ（加密）」。
2) 引擎選「本地 Ollama」、模型 `sakura`、勾繁體 → 開始。
3) 監控面板應顯示解密/預翻進度、GPU 遙測。
4) 預翻完成自動啟動 → **進遊戲實際對話視窗確認顯示中文**（Map003 開場、Map018 劇情等）。
5) 量測命中率、記錄未命中樣本到 `.superpowers/sdd/`。

- [ ] **Step 3: 命中率不足時的校準（若需要）**

若對話未被替換：對照遊戲執行期 `convertEscapeCharacters` 實際收到的字串 vs `mz_extract` 產出的 key，調整 §Task 2 的訊息分組規則（多半是 401 分組邊界或控制碼位置），補測試後重跑。

- [ ] **Step 4: 還原驗證**

GUI 按「還原遊戲」→ 確認 `index.html`/`plugins.js` 還原、我方新增檔刪除、`data/*.json` 未被更動（本就唯讀）。

- [ ] **Step 5: 更新文件 + Commit（先取得使用者明確同意）**

```bash
git add README.md docs/superpowers/specs/2026-07-04-handoff.md
git commit -m "docs: 加密 MZ 支援完成，更新支援矩陣與交接文件"
```

---

## 驗收清單（全部達成才算完成）

- [ ] `pytest -q` 全綠（新增 4 個測試檔 + 既有）。
- [ ] 實體加密遊戲部署後，**對話視窗實際顯示中文**、覆蓋率明顯高於原 1739 條（附證據，鐵則 #7）。
- [ ] `data/*.json` 全程未被修改；「還原遊戲」可完整復原。
- [ ] 未把任何遊戲內容 commit 進 repo。
- [ ] 每次 commit 皆事前取得使用者明確同意。
