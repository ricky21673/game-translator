# 測試 NullTranslator：離線恆等翻譯，不呼叫任何網路 API。
from core.translators.null import NullTranslator


def test_returns_same_texts():
    # 回傳內容應與輸入完全相同（原文原樣保留）
    t = NullTranslator()
    texts = ["こんにちは", "さようなら"]
    out = t.translate(texts, target_lang="ZH")
    assert out == texts


def test_returns_same_length():
    # 回傳長度需與輸入一致
    t = NullTranslator()
    texts = [f"s{i}" for i in range(10)]
    out = t.translate(texts, target_lang="ZH", source_lang="JA")
    assert len(out) == len(texts)


def test_empty_list_returns_empty():
    # 空輸入應回傳空 list，不應報錯
    t = NullTranslator()
    assert t.translate([], target_lang="ZH") == []


def test_returns_new_list_not_same_object():
    # 回傳應為獨立 list（避免呼叫端誤改到原始輸入）
    t = NullTranslator()
    texts = ["a", "b"]
    out = t.translate(texts, target_lang="ZH")
    assert out is not texts
    assert out == texts
