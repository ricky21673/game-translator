# 測試 GUI 狀態機（can_start、choose_translator_mode）：
# 不建立 QWidget，headless 環境下可跑。
from core.detector import Detection
from gui.app import can_start, can_restore, choose_translator_mode


def test_no_selection_cannot_start():
    # 未選擇遊戲（detection 為 None）→ 不能開始
    assert can_start(None) is False


def test_mv_can_start():
    # 偵測到 MV 引擎且提供完整目錄資訊 → 可以開始
    assert can_start(Detection("mv", "/g", "/g/www", "/g/www/js")) is True


def test_unknown_cannot_start():
    # 未知引擎 → 不能開始
    assert can_start(Detection("unknown", "/g")) is False


def test_unity_cannot_start_in_p1():
    # P1 尚未支援 Unity → 不能開始
    assert can_start(Detection("unity", "/g")) is False


def test_restore_no_selection_cannot_restore():
    # 未選擇遊戲（detection 為 None）→ 還原鈕不可用
    assert can_restore(None) is False


def test_restore_mv_can_restore():
    # 偵測到 MV 引擎 → 還原鈕可用
    assert can_restore(Detection("mv", "/g", "/g/www", "/g/www/js")) is True


def test_restore_unknown_cannot_restore():
    # 未知引擎 → 還原鈕不可用
    assert can_restore(Detection("unknown", "/g")) is False


def test_restore_unity_cannot_restore_in_p1():
    # P1 尚未支援 Unity → 還原鈕不可用
    assert can_restore(Detection("unity", "/g")) is False


def test_only_dict_json_chooses_offline():
    # 只選了字典 JSON、沒填 key → 離線字典模式
    assert choose_translator_mode("/g/dict.json", "") == "offline"


def test_only_key_chooses_deepl():
    # 只填了 key、沒選字典 JSON → DeepL 模式
    assert choose_translator_mode(None, "sk-xxx") == "deepl"


def test_both_dict_and_key_chooses_deepl_with_seed():
    # 兩者都有 → 仍走 DeepL（字典 JSON 當作種子快取，由呼叫端負責複製）
    assert choose_translator_mode("/g/dict.json", "sk-xxx") == "deepl"


def test_neither_chooses_none():
    # 都沒有 → 不可啟動
    assert choose_translator_mode(None, "") == "none"
    assert choose_translator_mode("", "") == "none"
