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
