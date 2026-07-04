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
