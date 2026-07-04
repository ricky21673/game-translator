# 測試 GUI 狀態機（can_start、choose_translator_mode、visible_fields）：
# 不建立 QWidget，headless 環境下可跑。
from core.detector import Detection
from gui.app import can_start, can_restore, choose_translator_mode, visible_fields


def test_no_selection_cannot_start():
    # 未選擇遊戲（detection 為 None）→ 不能開始
    assert can_start(None) is False


def test_mv_can_start():
    # 偵測到 MV 引擎且提供完整目錄資訊 → 可以開始
    assert can_start(Detection("mv", "/g", "/g/www", "/g/www/js", "/g/www")) is True


def test_mz_can_start():
    # 偵測到 MZ 引擎且提供完整目錄資訊（web_dir 為遊戲根目錄，無 www）→ 可以開始
    assert can_start(Detection("mz", "/g", None, "/g/js", "/g")) is True


def test_unknown_cannot_start():
    # 未知引擎 → 不能開始
    assert can_start(Detection("unknown", "/g")) is False


def test_unity_cannot_start_in_p1():
    # P1 尚未支援 Unity → 不能開始
    assert can_start(Detection("unity", "/g")) is False


def test_tyrano_can_start():
    # 偵測到 TyranoScript 引擎（game_dir 有值、web_dir 為 None）→ 可以開始
    assert can_start(Detection("tyrano", game_dir="/g")) is True


def test_restore_no_selection_cannot_restore():
    # 未選擇遊戲（detection 為 None）→ 還原鈕不可用
    assert can_restore(None) is False


def test_restore_mv_can_restore():
    # 偵測到 MV 引擎 → 還原鈕可用
    assert can_restore(Detection("mv", "/g", "/g/www", "/g/www/js", "/g/www")) is True


def test_restore_mz_can_restore():
    # 偵測到 MZ 引擎 → 還原鈕可用
    assert can_restore(Detection("mz", "/g", None, "/g/js", "/g")) is True


def test_restore_unknown_cannot_restore():
    # 未知引擎 → 還原鈕不可用
    assert can_restore(Detection("unknown", "/g")) is False


def test_restore_unity_cannot_restore_in_p1():
    # P1 尚未支援 Unity → 還原鈕不可用
    assert can_restore(Detection("unity", "/g")) is False


def test_restore_tyrano_can_restore():
    # 偵測到 TyranoScript 引擎 → 還原鈕可用
    assert can_restore(Detection("tyrano", game_dir="/g")) is True


# 新版 choose_translator_mode：engine 直接由「翻譯引擎」下拉決定
# （offline/deepl/local 三選一，不再有「deepl 但沒填 key 就當 offline」的隱含猜測），
# 本函式只檢查「該引擎的必要欄位是否已填」。


def test_offline_engine_with_dict_chooses_offline():
    # engine=offline 且有選字典 JSON → 離線字典模式
    assert choose_translator_mode("offline", "/g/dict.json", "") == "offline"


def test_offline_engine_without_dict_chooses_none():
    # engine=offline 但沒選字典 JSON（必選）→ 不可啟動
    assert choose_translator_mode("offline", None, "") == "none"
    assert choose_translator_mode("offline", "", "") == "none"


def test_deepl_engine_with_key_chooses_deepl():
    # engine=deepl 且有填 key → DeepL 模式（不論是否也選了字典 JSON 當種子）
    assert choose_translator_mode("deepl", None, "sk-xxx") == "deepl"
    assert choose_translator_mode("deepl", "/g/dict.json", "sk-xxx") == "deepl"


def test_deepl_engine_without_key_chooses_none():
    # engine=deepl 但沒填 key（必填）→ 不可啟動，即使有選字典 JSON 也一樣
    assert choose_translator_mode("deepl", None, "") == "none"
    assert choose_translator_mode("deepl", "/g/dict.json", "") == "none"


def test_local_engine_chooses_local_even_without_key_or_dict():
    # 引擎選擇本地 Ollama → 不需 key 也不需字典即可啟動
    assert choose_translator_mode("local", None, "") == "local"


def test_local_engine_overrides_dict_and_key():
    # 引擎選擇本地 Ollama → 即使有帶 key/dict 也優先走 local
    assert choose_translator_mode("local", "/g/dict.json", "sk-xxx") == "local"


def test_unknown_engine_chooses_none():
    # 未知 engine 值 → 保守回 none，不可啟動
    assert choose_translator_mode("unknown", "/g/dict.json", "sk-xxx") == "none"


# 測試 visible_fields：純函式，依引擎回傳該顯示的欄位鍵集合，GUI 依此 setVisible。


def test_visible_fields_offline_shows_only_dict():
    assert visible_fields("offline") == {"dict"}


def test_visible_fields_deepl_shows_dict_and_key():
    assert visible_fields("deepl") == {"dict", "key"}


def test_visible_fields_local_shows_dict_and_model():
    assert visible_fields("local") == {"dict", "model"}


def test_visible_fields_unknown_shows_nothing():
    # 未知引擎值保守起見全部隱藏，避免顯示不相關欄位
    assert visible_fields("unknown") == set()
