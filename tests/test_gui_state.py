# 測試 GUI 狀態機（can_start）：不建立 QWidget，headless 環境下可跑。
from core.detector import Detection
from gui.app import can_start


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
