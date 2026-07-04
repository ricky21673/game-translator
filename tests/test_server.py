import requests
from core.cache import DictCache
from core.pipeline import Pipeline
from core.server import TranslationServer


class StubTranslator:
    def translate(self, texts, target_lang, source_lang=None):
        return [t + "_zh" for t in texts]


def test_translate_endpoint(tmp_path):
    # 測試 localhost 伺服器能正確接收 POST /translate 並回傳譯文
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


def test_not_found_invalid_path(tmp_path):
    # 非 /translate 路徑應回 404
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, StubTranslator(), target_lang="ZH")
    srv = TranslationServer(pipe, port=0)
    port = srv.start()
    try:
        r = requests.post(f"http://127.0.0.1:{port}/foo",
                          json={"texts": ["test"]}, timeout=5)
        assert r.status_code == 404
    finally:
        srv.stop()


def test_empty_texts_array(tmp_path):
    # texts 為空陣列應回 200 且 translations 為空陣列
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, StubTranslator(), target_lang="ZH")
    srv = TranslationServer(pipe, port=0)
    port = srv.start()
    try:
        r = requests.post(f"http://127.0.0.1:{port}/translate",
                          json={"texts": []}, timeout=5)
        assert r.status_code == 200
        assert r.json()["translations"] == []
    finally:
        srv.stop()


def test_invalid_input_bad_json(tmp_path):
    # 送非法 JSON 應回 400
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, StubTranslator(), target_lang="ZH")
    srv = TranslationServer(pipe, port=0)
    port = srv.start()
    try:
        r = requests.post(f"http://127.0.0.1:{port}/translate",
                          data="not valid json", timeout=5)
        assert r.status_code == 400
        assert "error" in r.json()
    finally:
        srv.stop()


def test_invalid_input_texts_not_list(tmp_path):
    # texts 不是 list 應回 400
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, StubTranslator(), target_lang="ZH")
    srv = TranslationServer(pipe, port=0)
    port = srv.start()
    try:
        r = requests.post(f"http://127.0.0.1:{port}/translate",
                          json={"texts": "not a list"}, timeout=5)
        assert r.status_code == 400
        assert "error" in r.json()
    finally:
        srv.stop()
