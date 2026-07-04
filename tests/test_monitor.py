"""
測試 gui/monitor.py：
- 純函式 format_speed / format_eta / compute_eta / format_gpu 的邊界與正常值。
- TranslationMonitor.set_progress 用注入的假時鐘與假取樣器驗證進度/速度/ETA 文字，
  以及 GPU 每秒刷新（用注入 sampler，不依賴真卡）。
需要建立 QWidget，故用 offscreen 平台以支援無頭環境執行。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.gpu import GpuSnapshot
from gui.monitor import (
    TranslationMonitor, compute_eta, format_eta, format_gpu, format_speed,
)

_qapp = QApplication.instance() or QApplication([])


# -- 純函式 --------------------------------------------------------------
def test_format_speed_normal():
    assert format_speed(100, 10) == "10.0 句/秒"
    assert format_speed(5, 2) == "2.5 句/秒"


def test_format_speed_guards_zero():
    # 沒經過時間或沒完成句數時不可除以 0，回占位字串
    assert format_speed(0, 0) == "-- 句/秒"
    assert format_speed(10, 0) == "-- 句/秒"
    assert format_speed(0, 5) == "-- 句/秒"


def test_format_eta_none_and_zero():
    assert format_eta(None) == "計算中…"
    assert format_eta(0) == "即將完成"


def test_format_eta_units():
    assert format_eta(45) == "45秒"
    assert format_eta(90) == "1分30秒"
    assert format_eta(3661) == "1時1分1秒"


def test_compute_eta():
    # 100 句 10 秒翻了 25 句 → 速度 2.5 句/秒，剩 75 句 → 30 秒
    assert compute_eta(25, 100, 10) == 30.0
    # 還沒開始/沒時間 → None
    assert compute_eta(0, 100, 10) is None
    assert compute_eta(25, 100, 0) is None
    # 已完成 → 0
    assert compute_eta(100, 100, 10) == 0.0


def test_format_gpu_available():
    snap = GpuSnapshot(available=True, name="RTX 3080", gpu_util=73,
                       mem_used=6 * 1024 ** 3, mem_total=10 * 1024 ** 3,
                       temperature=70)
    s = format_gpu(snap)
    assert "RTX 3080" in s
    assert "73%" in s
    assert "70°C" in s
    assert "6144/10240 MB" in s


def test_format_gpu_unavailable():
    snap = GpuSnapshot(available=False, detail="無 NVIDIA GPU")
    s = format_gpu(snap)
    assert "不可用" in s
    assert "無 NVIDIA GPU" in s


# -- TranslationMonitor --------------------------------------------------
class _FakeSampler:
    def __init__(self, snap):
        self.snap = snap
        self.calls = 0
        self.closed = False
    def sample(self):
        self.calls += 1
        return self.snap
    def close(self):
        self.closed = True


class _FakeClock:
    def __init__(self):
        self.t = 0.0
    def __call__(self):
        return self.t


def _make_monitor(snap=None):
    if snap is None:
        snap = GpuSnapshot(available=False, detail="測試無卡")
    sampler = _FakeSampler(snap)
    clock = _FakeClock()
    mon = TranslationMonitor(sampler=sampler, clock=clock)
    return mon, sampler, clock


def test_monitor_refreshes_gpu_on_construct():
    # 建立時就先拉一次 GPU 取樣，畫面不必等第一個 timer tick
    snap = GpuSnapshot(available=True, name="G", gpu_util=10,
                       mem_used=1024 ** 3, mem_total=2 * 1024 ** 3, temperature=40)
    mon, sampler, _ = _make_monitor(snap)
    assert sampler.calls >= 1
    assert "使用率 10%" in mon.gpu_label.text()
    mon.stop()


def test_monitor_progress_speed_and_eta():
    mon, _sampler, clock = _make_monitor()
    # 第一次進度：total=100，記起始時間（clock=0），done=0
    mon.set_progress(0, 100)
    assert "0/100" in mon.progress_label.text()
    # 時間走 10 秒，翻了 25 句 → 速度 2.5 句/秒、ETA 30 秒
    clock.t = 10.0
    mon.set_progress(25, 100)
    assert "25/100" in mon.progress_label.text()
    assert "25%" in mon.progress_label.text()
    assert mon.progress_bar.value() == 25
    assert "2.5 句/秒" in mon.speed_label.text()
    assert "30秒" in mon.eta_label.text()
    mon.stop()


def test_monitor_all_cached_shows_no_translation_needed():
    # total=0（全部命中快取）→ 顯示無需翻譯、進度條滿
    mon, _sampler, _clock = _make_monitor()
    mon.set_progress(0, 0)
    assert "無需翻譯" in mon.progress_label.text()
    assert mon.progress_bar.value() == 100
    mon.stop()


def test_monitor_reset():
    mon, _sampler, clock = _make_monitor()
    mon.set_progress(50, 100)
    mon.reset()
    assert "尚未開始" in mon.progress_label.text()
    assert mon.progress_bar.value() == 0
    assert mon._start_time is None
    mon.stop()


def test_monitor_stop_closes_sampler():
    mon, sampler, _clock = _make_monitor()
    mon.stop()
    assert sampler.closed is True
