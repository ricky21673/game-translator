# Game Translator P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通「選遊戲主程式 → 自動判型 → DeepL 翻譯 → MV 遊戲內出現中文」整條垂直骨架，且全程不遠端注入。

**Architecture:** Python 為大腦（引擎偵測、翻譯引擎抽象 + DeepL、快取字典、localhost 伺服器、PySide6 GUI）。遊戲端只放一支 MV JS plugin（遊戲自己載入）當薄傳聲筒，開機抽字串 → 向 localhost 要譯文 → 查表替換顯示。

**Tech Stack:** Python 3.10+、PySide6、requests、pytest；MV adapter 為原生 RPG Maker MV 1.6.1 plugin（JavaScript）。

## Global Constraints

- **禁止遠端注入**：adapter 一律「遊戲自己載入」（MV 走 plugins.js 註冊）。不得使用 `inject.exe`／`CreateRemoteThread` 類手段。
- **DeepL 一切依官方文檔（已查證，數值不得臆測）**：
  - 端點 free `https://api-free.deepl.com/v2/translate`、pro `https://api.deepl.com/v2/translate`
  - `POST`；認證 header `Authorization: DeepL-Auth-Key <key>`
  - body：`text`（陣列，單次上限 50 筆、總大小 ≤128 KiB）、`target_lang`（必填）、`source_lang`（選填，省略即自動偵測）
  - 成功回應 HTTP `200`，結構 `{"translations":[{"detected_source_language":"...","text":"..."}]}`（順序對應輸入）
  - 錯誤碼：`456` 額度用盡、`429` 速率過高、`500` 服務端錯誤、`403` 認證失敗（以 DeepL 規格處理，實作時再核）
- **字典格式**：扁平 JSON `{ "原文": "譯文" }`，UTF-8，與遊戲附的 `AI翻译文件.json` 同款。
- **伺服器只綁 `127.0.0.1`**，不對外開放。
- **git commit 需 Ricky 當次明確指示**（Ricky 全域鐵則第 2 條）：每個 Task 的最後一步只做 `git add`（staging）並**停下等 Ricky 指示**，不自動 commit。
- **驗收白老鼠**：`D:\7-Zip\tmp\禰鳥村 愛虐と淫艶の祀 ver1.01`（已確認 RPG Maker MV 1.6.1 / NW.js）。
- 全程回覆與註解使用中文。

## File Structure

```
game-translator/
├─ core/
│  ├─ __init__.py
│  ├─ detector.py              # 引擎偵測
│  ├─ cache.py                 # 快取字典 load/save/get/put
│  ├─ pipeline.py              # 先查快取、未命中呼叫引擎、寫回快取
│  ├─ server.py                # localhost HTTP: POST /translate
│  └─ translators/
│     ├─ __init__.py
│     ├─ base.py               # Translator 抽象介面
│     └─ deepl.py              # DeepLTranslator
├─ adapters/
│  └─ mv/
│     └─ ZZ_Translator_Bridge.js   # MV plugin 樣板
├─ gui/
│  ├─ __init__.py
│  └─ app.py                   # PySide6 視窗 + 狀態機
├─ launcher.py                 # 部署 adapter + 起 server + 開遊戲
├─ main.py                     # 進入點：開 GUI
├─ requirements.txt
└─ tests/
   ├─ test_detector.py
   ├─ test_cache.py
   ├─ test_deepl.py
   ├─ test_pipeline.py
   ├─ test_server.py
   └─ test_launcher.py
```

---

### Task 1: 專案骨架 + 引擎偵測器

**Files:**
- Create: `requirements.txt`, `core/__init__.py`, `core/translators/__init__.py`, `gui/__init__.py`
- Create: `core/detector.py`
- Test: `tests/test_detector.py`

**Interfaces:**
- Produces: `detect(exe_path: str) -> Detection`；`Detection` 具欄位 `engine: str`（`'mv'|'mz'|'unity'|'tyrano'|'unknown'`）、`game_dir: str`、`www_dir: str | None`、`js_dir: str | None`。

- [ ] **Step 1: 建立骨架檔**

`requirements.txt`：
```
PySide6==6.7.*
requests==2.32.*
pytest==8.*
```
建立空檔：`core/__init__.py`、`core/translators/__init__.py`、`gui/__init__.py`、`tests/__init__.py`。

- [ ] **Step 2: 寫失敗測試**

`tests/test_detector.py`：
```python
import os
from core.detector import detect

def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").close()

def test_detects_mv_with_www(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "www" / "js" / "rpg_core.js"))
    _touch(str(game / "Game.exe"))
    d = detect(str(game / "Game.exe"))
    assert d.engine == "mv"
    assert d.www_dir == str(game / "www")
    assert d.js_dir == str(game / "www" / "js")

def test_detects_mz_at_root(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "js" / "rmmz_core.js"))
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "mz"

def test_detects_unity(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "UnityPlayer.dll"))
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "unity"

def test_unknown(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "unknown"
```

- [ ] **Step 3: 執行測試確認失敗**

Run: `pytest tests/test_detector.py -v`
Expected: FAIL（`ModuleNotFoundError: core.detector`）

- [ ] **Step 4: 實作 detector**

`core/detector.py`：
```python
import os
from dataclasses import dataclass


@dataclass
class Detection:
    engine: str
    game_dir: str
    www_dir: str | None = None
    js_dir: str | None = None


def detect(exe_path: str) -> Detection:
    game_dir = os.path.dirname(os.path.abspath(exe_path))
    # MV/MZ 的 js 可能在 <dir>/www/js 或 <dir>/js
    for base in (os.path.join(game_dir, "www"), game_dir):
        js_dir = os.path.join(base, "js")
        if os.path.isfile(os.path.join(js_dir, "rpg_core.js")):
            www = base if os.path.basename(base) == "www" else None
            return Detection("mv", game_dir, www, js_dir)
        if os.path.isfile(os.path.join(js_dir, "rmmz_core.js")):
            www = base if os.path.basename(base) == "www" else None
            return Detection("mz", game_dir, www, js_dir)
    # Unity：UnityPlayer.dll 或任何 *_Data 目錄
    if os.path.isfile(os.path.join(game_dir, "UnityPlayer.dll")):
        return Detection("unity", game_dir)
    for name in os.listdir(game_dir):
        if name.endswith("_Data") and os.path.isdir(os.path.join(game_dir, name)):
            return Detection("unity", game_dir)
    # TyranoScript
    if os.path.isdir(os.path.join(game_dir, "data", "scenario")):
        return Detection("tyrano", game_dir)
    return Detection("unknown", game_dir)
```

- [ ] **Step 5: 執行測試確認通過**

Run: `pytest tests/test_detector.py -v`
Expected: PASS（4 passed）

- [ ] **Step 6: Stage 並等 Ricky 指示 commit**

```bash
git add requirements.txt core/ gui/__init__.py tests/
```
停下，回報並等 Ricky 說 commit。

---

### Task 2: 快取字典

**Files:**
- Create: `core/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: 無。
- Produces: `class DictCache(path: str)`，方法 `get(text: str) -> str | None`、`put(text: str, translation: str) -> None`、`save() -> None`；建構時若檔案存在則載入，格式為扁平 `{原文:譯文}` JSON。

- [ ] **Step 1: 寫失敗測試**

`tests/test_cache.py`：
```python
import json
from core.cache import DictCache

def test_put_get_roundtrip(tmp_path):
    p = tmp_path / "dict.json"
    c = DictCache(str(p))
    assert c.get("はい") is None
    c.put("はい", "是")
    assert c.get("はい") == "是"

def test_save_and_reload(tmp_path):
    p = tmp_path / "dict.json"
    c = DictCache(str(p))
    c.put("いいえ", "否")
    c.save()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["いいえ"] == "否"
    c2 = DictCache(str(p))
    assert c2.get("いいえ") == "否"

def test_loads_existing_mtool_dict(tmp_path):
    p = tmp_path / "dict.json"
    p.write_text(json.dumps({"戻る": "返回"}, ensure_ascii=False), encoding="utf-8")
    assert DictCache(str(p)).get("戻る") == "返回"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_cache.py -v`
Expected: FAIL（`ModuleNotFoundError: core.cache`）

- [ ] **Step 3: 實作 cache**

`core/cache.py`：
```python
import json
import os


class DictCache:
    def __init__(self, path: str):
        self.path = path
        self._data: dict[str, str] = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                self._data = json.load(f)

    def get(self, text: str) -> str | None:
        return self._data.get(text)

    def put(self, text: str, translation: str) -> None:
        self._data[text] = translation

    def save(self) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_cache.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Stage 並等 Ricky 指示 commit**

```bash
git add core/cache.py tests/test_cache.py
```
停下等指示。

---

### Task 3: 翻譯引擎抽象 + DeepL 實作

**Files:**
- Create: `core/translators/base.py`, `core/translators/deepl.py`
- Test: `tests/test_deepl.py`

**Interfaces:**
- Consumes: 無。
- Produces:
  - `class Translator`（抽象）：`translate(self, texts: list[str], target_lang: str, source_lang: str | None = None) -> list[str]`
  - `class DeepLTranslator(Translator)`：建構 `DeepLTranslator(auth_key: str, free: bool = True, session=None)`；`translate(...)` 依官方文檔呼叫 API，回傳與輸入等長的譯文陣列。
  - `class TranslationError(Exception)`，具 `kind: str`（`'quota'|'auth'|'rate'|'server'|'network'`）。

- [ ] **Step 1: 寫失敗測試（用假 session，不打真網路）**

`tests/test_deepl.py`：
```python
import pytest
from core.translators.deepl import DeepLTranslator, TranslationError


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.last = None
    def post(self, url, headers=None, data=None, timeout=None):
        self.last = {"url": url, "headers": headers, "data": data}
        return self.resp


def test_translate_success_returns_texts():
    resp = FakeResp(200, {"translations": [
        {"detected_source_language": "JA", "text": "是"},
        {"detected_source_language": "JA", "text": "否"},
    ]})
    sess = FakeSession(resp)
    t = DeepLTranslator("key-123", free=True, session=sess)
    out = t.translate(["はい", "いいえ"], target_lang="ZH")
    assert out == ["是", "否"]

def test_uses_free_endpoint_and_auth_header():
    sess = FakeSession(FakeResp(200, {"translations": [{"text": "是"}]}))
    DeepLTranslator("key-123", free=True, session=sess).translate(["はい"], target_lang="ZH")
    assert sess.last["url"] == "https://api-free.deepl.com/v2/translate"
    assert sess.last["headers"]["Authorization"] == "DeepL-Auth-Key key-123"

def test_uses_pro_endpoint():
    sess = FakeSession(FakeResp(200, {"translations": [{"text": "是"}]}))
    DeepLTranslator("k", free=False, session=sess).translate(["はい"], target_lang="ZH")
    assert sess.last["url"] == "https://api.deepl.com/v2/translate"

def test_quota_exceeded_raises():
    sess = FakeSession(FakeResp(456))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "quota"

def test_auth_failure_raises():
    sess = FakeSession(FakeResp(403))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "auth"

def test_rate_limit_raises():
    sess = FakeSession(FakeResp(429))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "rate"
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_deepl.py -v`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 實作 base 與 deepl**

`core/translators/base.py`：
```python
from abc import ABC, abstractmethod


class Translator(ABC):
    @abstractmethod
    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        ...
```

`core/translators/deepl.py`：
```python
import requests
from .base import Translator

FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"
BATCH = 50  # 官方文檔：單次最多 50 筆


class TranslationError(Exception):
    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


class DeepLTranslator(Translator):
    def __init__(self, auth_key: str, free: bool = True, session=None):
        self.auth_key = auth_key
        self.url = FREE_URL if free else PRO_URL
        self.session = session or requests.Session()

    def translate(self, texts, target_lang, source_lang=None):
        out: list[str] = []
        for i in range(0, len(texts), BATCH):
            out.extend(self._call(texts[i:i + BATCH], target_lang, source_lang))
        return out

    def _call(self, texts, target_lang, source_lang):
        headers = {"Authorization": f"DeepL-Auth-Key {self.auth_key}"}
        data = [("target_lang", target_lang)]
        if source_lang:
            data.append(("source_lang", source_lang))
        data.extend(("text", t) for t in texts)
        try:
            resp = self.session.post(self.url, headers=headers, data=data, timeout=30)
        except requests.RequestException as e:
            raise TranslationError("network", str(e))
        code = resp.status_code
        if code == 200:
            return [item["text"] for item in resp.json()["translations"]]
        if code == 456:
            raise TranslationError("quota", "DeepL 額度用盡 (456)")
        if code == 403:
            raise TranslationError("auth", "DeepL 認證失敗 (403)")
        if code == 429:
            raise TranslationError("rate", "DeepL 速率過高 (429)")
        raise TranslationError("server", f"DeepL 回應非預期狀態碼: {code}")
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_deepl.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: Stage 並等 Ricky 指示 commit**

```bash
git add core/translators/ tests/test_deepl.py
```

---

### Task 4: 翻譯管線（快取 + 引擎）

**Files:**
- Create: `core/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `DictCache`（Task 2）、`Translator`（Task 3）。
- Produces: `class Pipeline(cache: DictCache, translator: Translator, target_lang: str, source_lang: str | None = None)`；方法 `translate(texts: list[str]) -> list[str]`：對每筆先查快取，僅未命中者送引擎、翻完寫回快取並 `save()`，回傳與輸入等長且順序一致的譯文。

- [ ] **Step 1: 寫失敗測試**

`tests/test_pipeline.py`：
```python
from core.cache import DictCache
from core.pipeline import Pipeline


class SpyTranslator:
    def __init__(self):
        self.calls = []
    def translate(self, texts, target_lang, source_lang=None):
        self.calls.append(list(texts))
        return [t + "_翻" for t in texts]


def test_uncached_go_to_engine_and_are_cached(tmp_path):
    cache = DictCache(str(tmp_path / "d.json"))
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B"])
    assert out == ["A_翻", "B_翻"]
    assert tr.calls == [["A", "B"]]
    assert cache.get("A") == "A_翻"

def test_cached_are_not_sent_to_engine(tmp_path):
    cache = DictCache(str(tmp_path / "d.json"))
    cache.put("A", "已有")
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B"])
    assert out == ["已有", "B_翻"]
    assert tr.calls == [["B"]]  # 只送未命中的 B

def test_order_preserved_with_mixed_and_duplicates(tmp_path):
    cache = DictCache(str(tmp_path / "d.json"))
    cache.put("B", "B已")
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B", "A"])
    assert out == ["A_翻", "B已", "A_翻"]
    assert tr.calls == [["A"]]  # 重複的 A 只送一次
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL（`ModuleNotFoundError: core.pipeline`）

- [ ] **Step 3: 實作 pipeline**

`core/pipeline.py`：
```python
from .cache import DictCache
from .translators.base import Translator


class Pipeline:
    def __init__(self, cache: DictCache, translator: Translator,
                 target_lang: str, source_lang: str | None = None):
        self.cache = cache
        self.translator = translator
        self.target_lang = target_lang
        self.source_lang = source_lang

    def translate(self, texts: list[str]) -> list[str]:
        # 收集未命中且去重（保留首次出現順序）
        missing: list[str] = []
        seen: set[str] = set()
        for t in texts:
            if self.cache.get(t) is None and t not in seen:
                seen.add(t)
                missing.append(t)
        if missing:
            translated = self.translator.translate(
                missing, self.target_lang, self.source_lang)
            for src, dst in zip(missing, translated):
                self.cache.put(src, dst)
            self.cache.save()
        return [self.cache.get(t) for t in texts]
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: Stage 並等 Ricky 指示 commit**

```bash
git add core/pipeline.py tests/test_pipeline.py
```

---

### Task 5: localhost 伺服器

**Files:**
- Create: `core/server.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `Pipeline`（Task 4）。
- Produces: `class TranslationServer(pipeline, host="127.0.0.1", port=0)`；方法 `start() -> int`（在背景執行緒啟動，回傳實際埠號）、`stop() -> None`。HTTP `POST /translate`，request body `{"texts":[...]}`，response `{"translations":[...]}`。僅綁 `127.0.0.1`。

- [ ] **Step 1: 寫失敗測試（起真 server，用 requests 打本機）**

`tests/test_server.py`：
```python
import requests
from core.cache import DictCache
from core.pipeline import Pipeline
from core.server import TranslationServer


class StubTranslator:
    def translate(self, texts, target_lang, source_lang=None):
        return [t + "_zh" for t in texts]


def test_translate_endpoint(tmp_path):
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, StubTranslator(), target_lang="ZH")
    srv = TranslationServer(pipe, port=0)
    port = srv.start()
    try:
        r = requests.post(f"http://127.0.0.1:{port}/translate",
                          json={"texts": ["はい", "いいえ"]}, timeout=5)
        assert r.status_code == 200
        assert r.json()["translations"] == ["はい_zh", "いいえ_zh"]
    finally:
        srv.stop()
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_server.py -v`
Expected: FAIL（`ModuleNotFoundError: core.server`）

- [ ] **Step 3: 實作 server（用標準庫 http.server，零額外依賴）**

`core/server.py`：
```python
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class TranslationServer:
    def __init__(self, pipeline, host="127.0.0.1", port=0):
        self.pipeline = pipeline
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None

    def start(self) -> int:
        pipeline = self.pipeline

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass  # 靜音

            def do_POST(self):
                if self.path != "/translate":
                    self.send_response(404)
                    self.end_headers()
                    return
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                texts = body.get("texts", [])
                result = pipeline.translate(texts)
                payload = json.dumps(
                    {"translations": result}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_server.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: Stage 並等 Ricky 指示 commit**

```bash
git add core/server.py tests/test_server.py
```

---

### Task 6: MV JS adapter plugin 樣板

**Files:**
- Create: `adapters/mv/ZZ_Translator_Bridge.js`
- 本 Task 無自動化測試（JS 於遊戲執行環境內，改由 Task 8 的整合驗收 + 手動驗證）。以「檔案內容 + 手動 smoke」交付。

**Interfaces:**
- Produces: 一支 MV plugin，讀取由 launcher 注入的全域設定 `window.$TRANSLATOR_PORT`，開機時抽 `$dataXXX` 可見字串批次送 `POST /translate`，建立記憶體字典後 hook `Window_Base.prototype.convertEscapeCharacters` 做整串查表替換。

> **給實作者的背景（已於 MV 1.6.1 實機確認）**：`convertEscapeCharacters` 在 `rpg_windows.js:278`、`drawTextEx` 在 `:263`。此遊戲載入 `YEP_MessageCore` 等 plugin，故本 bridge 必須是 **plugins.js 最後一個**，wrap 時才能包住前面 plugin 的行為。

- [ ] **Step 1: 撰寫 plugin 樣板**

`adapters/mv/ZZ_Translator_Bridge.js`：
```javascript
//=============================================================================
// ZZ_Translator_Bridge.js  (P1)
// 由 game-translator 產生。遊戲自己載入，不做任何注入。
//=============================================================================
(function () {
  "use strict";

  var PORT = window.$TRANSLATOR_PORT || 0;
  var ENDPOINT = "http://127.0.0.1:" + PORT + "/translate";
  var dict = Object.create(null); // 原文 -> 譯文

  // --- 從 $dataXXX 抽可見字串（P1：抽對話事件文字與基本名稱）---
  function collectStrings() {
    var set = Object.create(null);
    function add(s) {
      if (typeof s === "string" && s.trim() && /[぀-ヿ一-鿿]/.test(s)) set[s] = 1;
    }
    // 各資料庫的 name / description
    [$dataActors, $dataItems, $dataSkills, $dataWeapons, $dataArmors,
     $dataStates, $dataClasses, $dataEnemies].forEach(function (arr) {
      if (!arr) return;
      arr.forEach(function (o) { if (o) { add(o.name); add(o.description); } });
    });
    // 地圖事件中的「顯示文字(code 401)/選項(102)」等指令參數
    (window.$translatorMaps || []).forEach(function (map) {
      if (!map || !map.events) return;
      map.events.forEach(function (ev) {
        if (!ev || !ev.pages) return;
        ev.pages.forEach(function (pg) {
          (pg.list || []).forEach(function (cmd) {
            if ([401, 405, 102, 101, 402].indexOf(cmd.code) >= 0) {
              (cmd.parameters || []).forEach(function (p) {
                if (typeof p === "string") add(p);
                else if (Array.isArray(p)) p.forEach(add);
              });
            }
          });
        });
      });
    });
    return Object.keys(set);
  }

  // --- 送 localhost 大腦翻譯，回填記憶體字典 ---
  function requestTranslation(texts, done) {
    if (!texts.length || !PORT) { done(); return; }
    var xhr = new XMLHttpRequest();
    xhr.open("POST", ENDPOINT, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      try {
        if (xhr.status === 200) {
          var res = JSON.parse(xhr.responseText).translations || [];
          for (var i = 0; i < texts.length; i++) {
            if (res[i]) dict[texts[i]] = res[i];
          }
        }
      } catch (e) { /* 失敗則維持原文，不崩 */ }
      done();
    };
    xhr.send(JSON.stringify({ texts: texts }));
  }

  // --- hook：整串查表替換（查不到就回原文）---
  var _conv = Window_Base.prototype.convertEscapeCharacters;
  Window_Base.prototype.convertEscapeCharacters = function (text) {
    if (dict[text]) text = dict[text];
    return _conv.call(this, text);
  };

  // --- 開機流程：資料載完 → 抽字串 → 翻譯 ---
  var _onLoad = Scene_Boot.prototype.start;
  Scene_Boot.prototype.start = function () {
    try {
      var texts = collectStrings();
      requestTranslation(texts, function () {});
    } catch (e) { /* 不影響遊戲啟動 */ }
    _onLoad.call(this);
  };
})();
```

- [ ] **Step 2: 手動 smoke（語法檢查）**

Run: `node --check adapters/mv/ZZ_Translator_Bridge.js`
Expected: 無輸出（語法正確）。

- [ ] **Step 3: Stage 並等 Ricky 指示 commit**

```bash
git add adapters/mv/ZZ_Translator_Bridge.js
```

> 註：地圖資料 `$dataMapXXX` 於遊戲中逐張載入。P1 由 launcher 在部署時把 `www/data/Map*.json` 內容預先讀出、以 `window.$translatorMaps` 形式供 bridge 抽字串（見 Task 7）。若日後要更精準，改為 hook `DataManager.loadMapData` 於每張地圖載入時增量翻譯——列為 P1 之後的優化，不在本階段。

---

### Task 7: Launcher（部署 adapter + 起 server + 開遊戲）

**Files:**
- Create: `launcher.py`
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `Detection`（Task 1）、`TranslationServer`（Task 5）、`adapters/mv/ZZ_Translator_Bridge.js`（Task 6）。
- Produces:
  - `deploy_mv_adapter(www_dir: str, port: int, maps: list[dict]) -> str`：把 bridge 複製到 `www/js/plugins/ZZ_Translator_Bridge.js`，在 `www/js/plugins.js` 末端註冊該 plugin（若尚未註冊），並寫一支 `www/js/translator_boot.js` 定義 `window.$TRANSLATOR_PORT`、`window.$translatorMaps`，再確保 `index.html` 於載入 plugins 前引入它。回傳 plugin 路徑。（可重入：重複呼叫不重複註冊。）
  - `launch_game(exe_path: str) -> subprocess.Popen`：直接以遊戲 exe 啟動（**不經 inject.exe**）。

- [ ] **Step 1: 寫失敗測試（純檔案操作，不真的開遊戲）**

`tests/test_launcher.py`：
```python
import os
from launcher import deploy_mv_adapter

def _mk_mv(tmp_path):
    www = tmp_path / "www"
    js = www / "js"
    js.mkdir(parents=True)
    (js / "plugins.js").write_text("var $plugins =\n[\n];\n", encoding="utf-8")
    (www / "index.html").write_text(
        "<html><body>"
        "<script type='text/javascript' src='js/plugins.js'></script>"
        "</body></html>", encoding="utf-8")
    return str(www)

def test_deploy_copies_plugin_and_registers(tmp_path):
    www = _mk_mv(tmp_path)
    # 準備來源 bridge
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 12345, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))
    # 檔案已複製
    assert os.path.isfile(os.path.join(www, "js", "plugins", "ZZ_Translator_Bridge.js"))
    # plugins.js 已註冊
    plugins = open(os.path.join(www, "js", "plugins.js"), encoding="utf-8").read()
    assert "ZZ_Translator_Bridge" in plugins
    # boot 檔含 port
    boot = open(os.path.join(www, "js", "translator_boot.js"), encoding="utf-8").read()
    assert "12345" in boot
    # index.html 於 plugins.js 前引入 boot
    html = open(os.path.join(www, "index.html"), encoding="utf-8").read()
    assert html.index("translator_boot.js") < html.index("plugins.js")

def test_deploy_is_reentrant(tmp_path):
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    b = str(src / "ZZ_Translator_Bridge.js")
    deploy_mv_adapter(www, 1, maps=[], bridge_src=b)
    deploy_mv_adapter(www, 1, maps=[], bridge_src=b)
    plugins = open(os.path.join(www, "js", "plugins.js"), encoding="utf-8").read()
    assert plugins.count("ZZ_Translator_Bridge") == 1  # 不重複註冊
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_launcher.py -v`
Expected: FAIL（`ModuleNotFoundError: launcher`）

- [ ] **Step 3: 實作 launcher**

`launcher.py`：
```python
import json
import os
import re
import shutil
import subprocess

_PLUGIN_NAME = "ZZ_Translator_Bridge"


def deploy_mv_adapter(www_dir: str, port: int, maps: list[dict],
                      bridge_src: str) -> str:
    js_dir = os.path.join(www_dir, "js")
    plugins_dir = os.path.join(js_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    # 1) 複製 bridge
    dst = os.path.join(plugins_dir, _PLUGIN_NAME + ".js")
    shutil.copyfile(bridge_src, dst)

    # 2) 寫 boot（設定 port 與地圖資料）
    boot_path = os.path.join(js_dir, "translator_boot.js")
    with open(boot_path, "w", encoding="utf-8") as f:
        f.write("window.$TRANSLATOR_PORT = %d;\n" % port)
        f.write("window.$translatorMaps = %s;\n"
                % json.dumps(maps, ensure_ascii=False))

    # 3) 於 plugins.js 末端註冊（可重入）
    plugins_js = os.path.join(js_dir, "plugins.js")
    text = open(plugins_js, encoding="utf-8").read()
    if _PLUGIN_NAME not in text:
        entry = '{"name":"%s","status":true,"description":"","parameters":{}}' % _PLUGIN_NAME
        idx = text.rstrip().rfind("]")
        head = text[:idx].rstrip()
        sep = "" if head.endswith("[") else ",\n"
        text = head + sep + entry + "\n" + text[idx:]
        with open(plugins_js, "w", encoding="utf-8") as f:
            f.write(text)

    # 4) 確保 index.html 於 plugins.js 前引入 boot（可重入）
    index = os.path.join(www_dir, "index.html")
    html = open(index, encoding="utf-8").read()
    if "translator_boot.js" not in html:
        tag = '<script type="text/javascript" src="js/translator_boot.js"></script>\n'
        html = re.sub(r'(<script[^>]*src=["\']js/plugins\.js["\'][^>]*>)',
                      tag + r"\1", html, count=1)
        with open(index, "w", encoding="utf-8") as f:
            f.write(html)
    return dst


def launch_game(exe_path: str) -> subprocess.Popen:
    return subprocess.Popen([exe_path], cwd=os.path.dirname(os.path.abspath(exe_path)))
```

- [ ] **Step 4: 執行測試確認通過**

Run: `pytest tests/test_launcher.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: Stage 並等 Ricky 指示 commit**

```bash
git add launcher.py tests/test_launcher.py
```

---

### Task 8: 最小 GUI（PySide6）+ 整合驗收

**Files:**
- Create: `gui/app.py`, `main.py`
- Test: `tests/test_gui_state.py`（只測狀態機邏輯，不起視窗）

**Interfaces:**
- Consumes: 全部前面 Task。
- Produces:
  - `def can_start(detection, engine_supported=("mv",)) -> bool`：未選遊戲（`detection is None`）或引擎不支援 → `False`。
  - `class MainWindow(QWidget)`：選 exe → 呼叫 `detect` 顯示判型 → 依 `can_start` 鎖/解鎖「開始」→ 按開始執行整合流程（讀地圖 → 起 server → 部署 adapter → 開遊戲）。
  - `main.py`：`QApplication` 進入點。

- [ ] **Step 1: 寫失敗測試（狀態機）**

`tests/test_gui_state.py`：
```python
from core.detector import Detection
from gui.app import can_start

def test_no_selection_cannot_start():
    assert can_start(None) is False

def test_mv_can_start():
    assert can_start(Detection("mv", "/g", "/g/www", "/g/www/js")) is True

def test_unknown_cannot_start():
    assert can_start(Detection("unknown", "/g")) is False

def test_unity_cannot_start_in_p1():
    assert can_start(Detection("unity", "/g")) is False
```

- [ ] **Step 2: 執行測試確認失敗**

Run: `pytest tests/test_gui_state.py -v`
Expected: FAIL（`ImportError: cannot import name can_start`）

- [ ] **Step 3: 實作 GUI**

`gui/app.py`：
```python
import glob
import json
import os

from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QVBoxLayout, QFileDialog,
)

from core.detector import detect, Detection
from core.cache import DictCache
from core.pipeline import Pipeline
from core.server import TranslationServer
from core.translators.deepl import DeepLTranslator
from launcher import deploy_mv_adapter, launch_game

SUPPORTED = ("mv",)  # P1 只支援 MV


def can_start(detection: Detection | None, engine_supported=SUPPORTED) -> bool:
    if detection is None:
        return False
    return detection.engine in engine_supported


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translator (P1)")
        self.exe_path: str | None = None
        self.detection: Detection | None = None
        self.server: TranslationServer | None = None

        self.pick_btn = QPushButton("選擇遊戲主程式…")
        self.info = QLabel("請先選擇遊戲主程式")
        self.engine_box = QComboBox(); self.engine_box.addItem("DeepL")
        self.key_edit = QLineEdit(); self.key_edit.setPlaceholderText("DeepL API Key")
        self.start_btn = QPushButton("開始"); self.start_btn.setEnabled(False)

        lay = QVBoxLayout(self)
        for w in (self.pick_btn, self.info, self.engine_box, self.key_edit, self.start_btn):
            lay.addWidget(w)

        self.pick_btn.clicked.connect(self.on_pick)
        self.start_btn.clicked.connect(self.on_start)

    def on_pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇遊戲主程式", "", "執行檔 (*.exe)")
        if not path:
            return
        self.exe_path = path
        self.detection = detect(path)
        label = {"mv": "RPG Maker MV", "mz": "RPG Maker MZ",
                 "unity": "Unity", "tyrano": "TyranoScript",
                 "unknown": "未知引擎"}[self.detection.engine]
        ok = can_start(self.detection)
        self.info.setText(
            f"偵測到：{label}" + ("" if ok else "（P1 尚未支援，之後由 OCR/專屬 adapter 處理）"))
        self.start_btn.setEnabled(ok)

    def on_start(self):
        d = self.detection
        maps = []
        for mp in sorted(glob.glob(os.path.join(d.www_dir, "data", "Map*.json"))):
            try:
                maps.append(json.load(open(mp, encoding="utf-8")))
            except Exception:
                pass
        key = self.key_edit.text().strip()
        cache = DictCache(os.path.join(d.game_dir, "translator_dict.json"))
        pipe = Pipeline(cache, DeepLTranslator(key, free=True),
                        target_lang="ZH", source_lang="JA")
        self.server = TranslationServer(pipe, port=0)
        port = self.server.start()
        bridge = os.path.join(os.path.dirname(__file__), "..",
                              "adapters", "mv", "ZZ_Translator_Bridge.js")
        deploy_mv_adapter(d.www_dir, port, maps, bridge_src=os.path.abspath(bridge))
        launch_game(self.exe_path)
        self.info.setText("已啟動遊戲，翻譯服務執行中…")
```

`main.py`：
```python
import sys
from PySide6.QtWidgets import QApplication
from gui.app import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(360, 220)
    win.show()
    sys.exit(app.exec())
```

- [ ] **Step 4: 執行狀態機測試確認通過**

Run: `pytest tests/test_gui_state.py -v`
Expected: PASS（4 passed）

- [ ] **Step 5: 全套單元測試回歸**

Run: `pytest -v`
Expected: 全部 PASS。

- [ ] **Step 6: 整合驗收（手動，用白老鼠遊戲）**

1. `python main.py` → 出現視窗。
2. 未選遊戲時「開始」為**灰色**（鎖住），狀態列顯示「請先選擇遊戲主程式」。
3. 選 `D:\7-Zip\tmp\禰鳥村 愛虐と淫艶の祀 ver1.01\Game.exe` → 顯示「偵測到：RPG Maker MV」，「開始」解鎖。
4. 填入 DeepL API Key → 按「開始」→ 遊戲啟動，主選單／對話出現中文。
5. 開工作管理員確認：只有 `Game.exe`（NW.js）在跑，**無** `inject.exe`／`mzHook32.dll`。
6. 抽掉網路或填錯 key → 有錯誤訊息或維持原文，**遊戲不崩**。
7. 確認遊戲資料夾產生 `translator_dict.json`（快取），內容為 `{原文:譯文}`。

> 驗收前置：先備份白老鼠遊戲的 `www/js/plugins.js` 與 `index.html`（本工具會改寫這兩檔）。P1 手動備份即可；自動備份/還原列為 P4。

- [ ] **Step 7: Stage 並等 Ricky 指示 commit**

```bash
git add gui/app.py main.py tests/test_gui_state.py
```

---

## Self-Review（對照 spec）

**Spec 覆蓋：**
- 引擎偵測器 → Task 1 ✅
- 翻譯引擎抽象 + DeepL（依官方文檔）→ Task 3 ✅
- 快取字典（AI翻译文件.json 同款）→ Task 2 ✅
- localhost server → Task 5 ✅
- MV/MZ JS adapter → Task 6（P1 實作 MV；MZ 偵測已具、adapter 留後）✅
- 最小 GUI（選 exe/判型/鎖解/啟動）→ Task 8 ✅
- 「沒選遊戲不能翻」→ Task 8 `can_start` + 驗收步驟 2 ✅
- 錯誤處理（DeepL 狀態碼、server 未就緒、未選遊戲）→ Task 3 / Task 6 / Task 8 ✅
- 不遠端注入 → Task 6/7 設計 + 驗收步驟 5 ✅

**已知 P1 邊界（spec 已列為非目標，計畫一致）：** OCR、Unity 實作、本地 Sugoi、LLM、簽章、GUI 美化、金手指。

**型別一致性檢查：** `Detection` 欄位、`Translator.translate` 簽章、`Pipeline.translate`、`TranslationServer.start/stop`、`deploy_mv_adapter/launch_game`、`can_start` 於各 Task 間一致。

**備註（誠實標示、非臆測）：** MV 的 `convertEscapeCharacters` 整串查表替換，對含大量控制碼（`\C[x]`、`\I[x]`）的訊息可能不命中；P1 以「資料庫名稱 + 事件文字」為主要覆蓋面，控制碼精細處理列為後續優化。此為已知取捨，非缺陷。
