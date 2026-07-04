"""
翻譯監控面板：即時顯示「句級翻譯進度」（未命中、實際送引擎的段落翻了幾句 / 共幾句）、
翻譯速度、預估剩餘時間（ETA），以及 GPU 使用率 / 顯存 / 溫度（每秒刷新）。

分工：
- format_eta / format_speed 是純函式（不碰 Qt、不碰時鐘），把「已翻句數 + 經過秒數」
  換算成人類可讀字串，方便單測不必起 GUI。
- TranslationMonitor 是 QWidget，只負責「把資料畫出來 + 每秒拉一次 GPU 取樣」。
  進度資料由外部（翻譯背景執行緒經 Qt signal → 主執行緒）透過 set_progress(done, total)
  餵進來；GPU 取樣由本widget 自己的 QTimer 在主執行緒定期呼叫 GpuSampler.sample()。

執行緒安全：
- set_progress 必須在「主執行緒」被呼叫。實務接線是背景 worker 發 segment_progress
  signal（queued 連線）→ Qt 事件迴圈在主執行緒派送 → 呼叫 monitor.set_progress，
  故 set_progress 內部不需加鎖。
- GPU 取樣（QTimer.timeout）同樣跑在主執行緒，與 set_progress 不會並行；兩者都只碰
  主執行緒的 widget 狀態，無跨執行緒共用資料，避免鎖競爭與死鎖。
- GpuSampler 只被這個主執行緒的 timer 呼叫，翻譯執行緒完全不碰它。
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QGroupBox, QLabel, QProgressBar, QVBoxLayout

from core.gpu import GpuSampler, GpuSnapshot


def format_speed(items: int, seconds: float) -> str:
    """
    把「已完成句數 items + 經過秒數 seconds」換算成速度字串。
    - seconds <= 0 或 items <= 0（還沒開始/剛開始）→ 回「-- 句/秒」，避免除以 0 或
      一開頭跳出爆炸大的假速度。
    - 其餘 → 「X.X 句/秒」（保留一位小數）。
    """
    if seconds <= 0 or items <= 0:
        return "-- 句/秒"
    rate = items / seconds
    return f"{rate:.1f} 句/秒"


def format_eta(seconds: float | None) -> str:
    """
    把「預估剩餘秒數」換算成人類可讀字串。
    - None（無法估算：還沒開始、或速度為 0）→「計算中…」
    - 0 → 「即將完成」
    - 其餘 → 依大小組出「Xh Ym Zs / X分Y秒 / X秒」（去掉為 0 的高位）。
    """
    if seconds is None:
        return "計算中…"
    total = int(round(seconds))
    if total <= 0:
        return "即將完成"
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}時{minutes}分{secs}秒"
    if minutes > 0:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


def compute_eta(done: int, total: int, elapsed: float) -> float | None:
    """
    純函式：由已翻句數 done / 總句數 total / 已經過秒數 elapsed 估算剩餘秒數。
    - done <= 0 或 elapsed <= 0（沒進度或沒時間基準）→ None（無法估算）
    - done >= total（已全部完成）→ 0
    - 其餘 → 用目前平均速度線性外推剩餘句數所需時間。
    """
    if done <= 0 or elapsed <= 0:
        return None
    if total <= 0 or done >= total:
        return 0.0
    rate = done / elapsed          # 句/秒
    remaining = total - done
    return remaining / rate


class TranslationMonitor(QGroupBox):
    """
    翻譯監控面板 widget。放進主視窗版面即可；不需要時可 setVisible(False)。

    - set_progress(done, total)：由外部（背景翻譯執行緒經 signal）餵進句級進度。
      第一次收到 total>0 時記錄起始時間，用於算速度/ETA。
    - GPU 面板由內建 QTimer 每秒刷新（可用 gpu_interval_ms 調整）。
    - clock 參數可注入假時鐘給測試，預設 time.monotonic（單調時鐘，不受系統校時影響）。
    """

    def __init__(self, parent=None, sampler: GpuSampler | None = None,
                 gpu_interval_ms: int = 1000, clock=time.monotonic):
        super().__init__("翻譯監控", parent)
        self._clock = clock
        self._sampler = sampler if sampler is not None else GpuSampler()
        self._start_time: float | None = None
        self._done = 0
        self._total = 0

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_label = QLabel("尚未開始")
        self.speed_label = QLabel("速度：-- 句/秒")
        self.eta_label = QLabel("預估剩餘：計算中…")
        self.gpu_label = QLabel("GPU：讀取中…")

        lay = QVBoxLayout(self)
        for w in (self.progress_bar, self.progress_label, self.speed_label,
                  self.eta_label, self.gpu_label):
            lay.addWidget(w)

        # GPU 每秒刷新的 timer（跑在建立此 widget 的執行緒＝主執行緒）
        self._gpu_timer = QTimer(self)
        self._gpu_timer.setInterval(gpu_interval_ms)
        self._gpu_timer.timeout.connect(self.refresh_gpu)
        self._gpu_timer.start()
        # 建立當下先拉一次，不必等第一個 tick 才有畫面
        self.refresh_gpu()

    # -- 句級進度 --------------------------------------------------------
    def set_progress(self, done: int, total: int) -> None:
        """
        更新句級進度。必須在主執行緒呼叫（見模組說明的執行緒安全一節）。
        第一次看到 total>0 就記起始時間；total==0 代表全部命中快取、無需翻譯。
        """
        self._done = done
        self._total = total
        if total > 0 and self._start_time is None:
            self._start_time = self._clock()

        if total <= 0:
            self.progress_bar.setValue(100)
            self.progress_label.setText("無需翻譯（全部命中快取）")
            self.speed_label.setText("速度：-- 句/秒")
            self.eta_label.setText("預估剩餘：即將完成")
            return

        percent = int(done / total * 100) if total else 0
        self.progress_bar.setValue(percent)
        self.progress_label.setText(f"翻譯進度：{done}/{total} 句（{percent}%）")

        elapsed = self._elapsed()
        self.speed_label.setText("速度：" + format_speed(done, elapsed))
        eta = compute_eta(done, total, elapsed)
        self.eta_label.setText("預估剩餘：" + format_eta(eta))

    def _elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return max(0.0, self._clock() - self._start_time)

    def reset(self) -> None:
        """重置進度狀態（例如再次啟動一輪翻譯前）。"""
        self._start_time = None
        self._done = 0
        self._total = 0
        self.progress_bar.setValue(0)
        self.progress_label.setText("尚未開始")
        self.speed_label.setText("速度：-- 句/秒")
        self.eta_label.setText("預估剩餘：計算中…")

    # -- GPU ------------------------------------------------------------
    def refresh_gpu(self) -> None:
        """拉一次 GPU 取樣並更新標籤。任何情況都不拋例外（取樣器已內部降級）。"""
        snap = self._sampler.sample()
        self.gpu_label.setText(format_gpu(snap))

    def stop(self) -> None:
        """停止 GPU timer 並釋放取樣器（關閉面板/視窗時呼叫）。"""
        self._gpu_timer.stop()
        self._sampler.close()


def format_gpu(snap: GpuSnapshot) -> str:
    """把一次 GPU 取樣結果組成單行顯示字串（純函式，方便單測）。"""
    if not snap.available:
        return "GPU：不可用（%s）" % (snap.detail or "無 NVIDIA GPU 或未安裝 nvidia-ml-py")
    mem_used = snap.mem_used_mb
    mem_total = snap.mem_total_mb
    return (
        f"GPU：{snap.name}｜使用率 {snap.gpu_util}%"
        f"｜顯存 {mem_used}/{mem_total} MB｜{snap.temperature}°C")
