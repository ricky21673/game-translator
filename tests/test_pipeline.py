from core.cache import DictCache
from core.pipeline import Pipeline, BATCH


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

def test_all_cached_no_engine_call_and_no_save(tmp_path):
    # 驗證全部命中快取時，引擎不被呼叫且不執行 save
    cache = DictCache(str(tmp_path / "d.json"))
    cache.put("X", "X譯")
    cache.put("Y", "Y譯")
    cache.put("Z", "Z譯")
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")

    # 追蹤 save 被呼叫的次數
    save_count = [0]
    original_save = cache.save
    def counting_save():
        save_count[0] += 1
        return original_save()
    cache.save = counting_save

    out = p.translate(["X", "Y", "Z"])
    assert out == ["X譯", "Y譯", "Z譯"]
    assert tr.calls == []  # 引擎完全沒被呼叫
    assert save_count[0] == 0  # save 完全沒被呼叫

def test_postprocess_applied_to_cache_hit_and_engine_output(tmp_path):
    # postprocess 應套用在「每一個輸出字串」，不論來自快取命中或引擎新翻，
    # 且不影響順序與長度
    cache = DictCache(str(tmp_path / "d.json"))
    cache.put("A", "已有")
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH", postprocess=lambda s: s + "X")
    out = p.translate(["A", "B", "A"])
    assert out == ["已有X", "B_翻X", "已有X"]
    assert len(out) == 3
    assert tr.calls == [["B"]]  # 只送未命中的 B，postprocess 不影響去重邏輯

def test_postprocess_none_keeps_existing_behavior(tmp_path):
    # postprocess 預設為 None 時，行為必須與現況完全一致
    cache = DictCache(str(tmp_path / "d.json"))
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")
    out = p.translate(["A", "B"])
    assert out == ["A_翻", "B_翻"]


def test_large_missing_set_is_translated_and_saved_in_batches(tmp_path):
    # 核心情境：長時間全翻（上萬句）時不能「全部翻完才存一次」，
    # 否則中途崩潰前面全白做。送出超過 BATCH 筆未命中文字，
    # 驗證：翻譯引擎被分批呼叫（每批最多 BATCH 筆）、cache.save 被呼叫多次
    # （分批存，而非全部翻完才存一次）、結果仍正確且順序一致。
    cache = DictCache(str(tmp_path / "d.json"))
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")

    # 追蹤 save 被呼叫的次數
    save_count = [0]
    original_save = cache.save
    def counting_save():
        save_count[0] += 1
        return original_save()
    cache.save = counting_save

    n = BATCH * 2 + 7  # 刻意跨 3 個批次（非整除 BATCH）
    texts = [f"S{i}" for i in range(n)]

    out = p.translate(texts)

    # 結果正確、順序一致、長度與輸入相同
    assert out == [f"S{i}_翻" for i in range(n)]
    assert len(out) == n

    # 引擎應被分批呼叫，每批筆數不超過 BATCH
    assert len(tr.calls) == 3  # ceil(107 / 50) = 3
    for batch_call in tr.calls:
        assert len(batch_call) <= BATCH
    # 攤平後應等於完整未命中清單，順序不變
    flattened = [t for batch_call in tr.calls for t in batch_call]
    assert flattened == texts

    # save 應被呼叫多次（分批存），次數與批次數一致
    assert save_count[0] == 3

    # 中途存檔的效果：直接檢查快取檔案已包含每一批的內容（邊翻邊存）
    reloaded = DictCache(str(tmp_path / "d.json"))
    for t in texts:
        assert reloaded.get(t) == t + "_翻"


def test_missing_not_exceeding_batch_saves_once(tmp_path):
    # 未命中筆數未超過 BATCH 時，維持原本「翻完存一次」的行為（只是分批邏輯的邊界情況）
    cache = DictCache(str(tmp_path / "d.json"))
    tr = SpyTranslator()
    p = Pipeline(cache, tr, target_lang="ZH")

    save_count = [0]
    original_save = cache.save
    def counting_save():
        save_count[0] += 1
        return original_save()
    cache.save = counting_save

    out = p.translate(["A", "B"])
    assert out == ["A_翻", "B_翻"]
    assert save_count[0] == 1
    assert tr.calls == [["A", "B"]]
