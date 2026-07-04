from core.cache import DictCache
from core.pipeline import Pipeline


class SpyTranslator:
    def __init__(self):
        self.calls = []
    def translate(self, texts, target_lang, source_lang=None):
        self.calls.append(list(texts))
        return [t + "_翻" for t in texts]


def test_uncached_go_to_engine_and_are_cached(tmp_path):
    # 未在快取中的文字應送引擎翻譯，結果寫回快取
    cache = DictCache(str(tmp_path / "d.json"))
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B"])
    assert out == ["A_翻", "B_翻"]
    assert tr.calls == [["A", "B"]]
    assert cache.get("A") == "A_翻"

def test_cached_are_not_sent_to_engine(tmp_path):
    # 已在快取中的文字不應送引擎，直接取快取結果
    cache = DictCache(str(tmp_path / "d.json"))
    cache.put("A", "已有")
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B"])
    assert out == ["已有", "B_翻"]
    assert tr.calls == [["B"]]  # 只送未命中的 B

def test_order_preserved_with_mixed_and_duplicates(tmp_path):
    # 保留原始順序，重複的文字去重後只送一次引擎
    cache = DictCache(str(tmp_path / "d.json"))
    cache.put("B", "B已")
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B", "A"])
    assert out == ["A_翻", "B已", "A_翻"]
    assert tr.calls == [["A"]]  # 重複的 A 只送一次
