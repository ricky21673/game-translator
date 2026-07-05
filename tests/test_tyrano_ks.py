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


# --- 資料陣列型文字（回想/畫廊清單）支援 ---

def test_extract_segments_data_array_extracts_japanese_strings():
    # 資料陣列行 [編號,"標題","描述"]：抽出兩個含日文的引號字串
    text = '[11,"標題日文ですます","説明の日本語テキスト"],\n'
    segments = extract_segments(text)
    assert "標題日文ですます" in segments
    assert "説明の日本語テキスト" in segments
    # 恰好兩個（編號 11 不是引號字串，不會被抽）
    assert len(segments) == 2


def test_apply_translations_data_array_replaces_only_quoted_content():
    # 兩個引號內容各給中文譯文，替換後只換引號內容、保留 [11, 與結構
    text = '[11,"標題日文ですます","説明の日本語テキスト"],\n'
    mapping = {
        "標題日文ですます": "中文標題",
        "説明の日本語テキスト": "中文說明",
    }
    result = apply_translations(text, mapping)
    assert result == '[11,"中文標題","中文說明"],\n'


def test_data_array_line_does_not_touch_tag_line_identifier():
    # tyrano 標籤行 [chara_part name="夢乃"]：不抽 name 值（識別字，翻了會壞遊戲）
    text = '[chara_part name="夢乃"]\n'
    segments = extract_segments(text)
    assert "夢乃" not in segments
    assert segments == []
    # apply_translations 也不動它（就算 mapping 給了對應也不碰）
    result = apply_translations(text, {"夢乃": "Yumeno"})
    assert result == text


def test_extract_segments_data_array_ascii_only_not_extracted():
    # 純英數資料陣列行：無日文，不抽
    text = '[1,"ok","start"]\n'
    segments = extract_segments(text)
    assert segments == []


def test_apply_translations_data_array_keeps_non_japanese_and_unmapped():
    # 一行含日文與英數混合：只換有對應譯文的日文引號，英數/未對應者原樣不動
    text = '[3,"start","開始ですか"]\n'
    mapping = {"開始ですか": "要開始嗎"}
    result = apply_translations(text, mapping)
    assert result == '[3,"start","要開始嗎"]\n'


# --- 標籤屬性顯示文字支援（新增）---


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
