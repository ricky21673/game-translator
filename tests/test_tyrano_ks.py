from adapters.tyrano.ks import extract_segments, apply_translations


# 內嵌測試用 .ks 範例：涵蓋標籤行、#name 行、//註解、結尾 [p]、行內 [n2]、純英數行
SAMPLE_KS = """[chara_part name="alice" face="face1"]
#alice
;這是分號開頭的行
* ラベル
@jump target=next
//これはコメントです
こんにちは、世界。[p]
元気です[n2]か？[p]
Hello World 123
"""


def test_extract_segments_skips_non_text_lines():
    # 只抽出真正該翻的日文可翻行，跳過標籤/名字/分號/星號/@/註解/純英數
    segments = extract_segments(SAMPLE_KS)

    assert "こんにちは、世界。" in segments
    assert "元気です[n2]か？" in segments
    # 非文字行、註解、純英數行都不該出現
    assert not any("chara_part" in s for s in segments)
    assert not any(s.startswith("#") for s in segments)
    assert not any(s.startswith(";") for s in segments)
    assert not any(s.startswith("*") for s in segments)
    assert not any(s.startswith("@") for s in segments)
    assert not any("コメント" in s for s in segments)
    assert "Hello World 123" not in segments


def test_apply_translations_replaces_and_preserves_structure():
    mapping = {
        "こんにちは、世界。": "Hello, world.",
        "元気です[n2]か？": "Are you doing well[n2]?",
    }
    result = apply_translations(SAMPLE_KS, mapping)
    lines = result.splitlines()

    # 非文字行原樣保留
    assert lines[0] == '[chara_part name="alice" face="face1"]'
    assert lines[1] == "#alice"
    assert lines[2] == ";這是分號開頭的行"
    assert lines[3] == "* ラベル"
    assert lines[4] == "@jump target=next"
    assert lines[5] == "//これはコメントです"

    # 結尾 [p] 保留，核心被替換
    assert lines[6] == "Hello, world.[p]"
    # 行內 [n2] 保留在核心中間，結尾 [p] 保留
    assert lines[7] == "Are you doing well[n2]?[p]"

    # mapping 沒有對應的英數行原樣不動
    assert lines[8] == "Hello World 123"

    # 換行結構（行數）不變
    assert len(lines) == len(SAMPLE_KS.splitlines())


def test_apply_translations_keeps_original_when_translation_missing_empty_or_same():
    text = "こんにちは、世界。[p]\n"
    # mapping 缺此key -> 原樣保留
    assert apply_translations(text, {}) == text
    # 譯文為空字串 -> 原樣保留
    assert apply_translations(text, {"こんにちは、世界。": ""}) == text
    # 譯文等於原文 -> 原樣保留
    assert apply_translations(text, {"こんにちは、世界。": "こんにちは、世界。"}) == text


def test_apply_translations_multiple_trailing_tags_preserved():
    text = "さようなら[l][r]\n"
    mapping = {"さようなら": "Goodbye"}
    result = apply_translations(text, mapping)
    assert result == "Goodbye[l][r]\n"


def test_extract_segments_handles_multiple_trailing_tags():
    text = "さようなら[l][r]\n"
    segments = extract_segments(text)
    assert segments == ["さようなら"]
