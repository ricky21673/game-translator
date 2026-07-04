# 測試 core/postprocess.py 的繁體中文轉換器（OpenCC s2twp：簡轉繁，含台灣慣用語）。
from core.postprocess import make_traditional_converter


def test_converts_simplified_to_traditional_taiwan_terms():
    # s2twp 除了字形轉繁體，也會轉台灣慣用語（如「软件」→「軟體」、「信息」→「資訊」）
    convert = make_traditional_converter()
    assert convert("软件里的信息") == "軟體裡的資訊"


def test_empty_string_is_safe():
    # 空字串應原樣回傳，不應丟例外
    convert = make_traditional_converter()
    assert convert("") == ""


def test_non_string_input_is_safe():
    # 非字串輸入（如 None、數字）應原樣回傳，不應丟例外
    convert = make_traditional_converter()
    assert convert(None) is None
    assert convert(123) == 123
