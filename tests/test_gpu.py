"""
測試 core/gpu.py 的 GPU 取樣：重點在「優雅降級」——沒有 pynvml、NVML 初始化失敗、
或取樣中途拋錯時，都必須回傳 available=False 的快照而不是拋例外。
真的有 NVIDIA GPU 時附一個非嚴格的 smoke test（沒有卡就 skip，不讓測試依賴硬體）。
"""
import types

import pytest

import core.gpu as gpu
from core.gpu import GpuSampler, GpuSnapshot


class _FakeUtil:
    def __init__(self, g, m):
        self.gpu = g
        self.memory = m


class _FakeMem:
    def __init__(self, used, total):
        self.used = used
        self.total = total


def _make_fake_pynvml(name=b"FAKE GPU", util=42, mem_used=2 * 1024 ** 3,
                      mem_total=8 * 1024 ** 3, temp=55, fail_on=None):
    """
    造一個假的 pynvml 模組，用來在沒有真卡的環境驗證取樣邏輯。
    fail_on 可指定某個函式名在被呼叫時拋 NVMLError，模擬中途失敗。
    """
    calls = {"init": 0, "shutdown": 0}

    class NVMLError(Exception):
        pass

    def _maybe_fail(fname):
        if fail_on == fname:
            raise NVMLError(f"boom in {fname}")

    m = types.SimpleNamespace()
    m.NVMLError = NVMLError
    m.NVML_TEMPERATURE_GPU = 0

    def nvmlInit():
        _maybe_fail("nvmlInit")
        calls["init"] += 1
    def nvmlShutdown():
        calls["shutdown"] += 1
    def nvmlDeviceGetHandleByIndex(i):
        _maybe_fail("nvmlDeviceGetHandleByIndex")
        return object()
    def nvmlDeviceGetName(h):
        return name
    def nvmlDeviceGetUtilizationRates(h):
        return _FakeUtil(util, 30)
    def nvmlDeviceGetMemoryInfo(h):
        return _FakeMem(mem_used, mem_total)
    def nvmlDeviceGetTemperature(h, sensor):
        return temp

    m.nvmlInit = nvmlInit
    m.nvmlShutdown = nvmlShutdown
    m.nvmlDeviceGetHandleByIndex = nvmlDeviceGetHandleByIndex
    m.nvmlDeviceGetName = nvmlDeviceGetName
    m.nvmlDeviceGetUtilizationRates = nvmlDeviceGetUtilizationRates
    m.nvmlDeviceGetMemoryInfo = nvmlDeviceGetMemoryInfo
    m.nvmlDeviceGetTemperature = nvmlDeviceGetTemperature
    m._calls = calls
    return m


def test_sample_returns_unavailable_when_pynvml_missing(monkeypatch):
    # pynvml 為 None（套件未安裝）時，sample 要回不可用快照、不拋例外
    monkeypatch.setattr(gpu, "pynvml", None)
    monkeypatch.setattr(gpu, "_PYNVML_IMPORT_ERROR", ImportError("no pynvml"))
    snap = GpuSampler().sample()
    assert snap.available is False
    assert snap.gpu_util is None
    assert "nvidia-ml-py" in (snap.detail or "")


def test_sample_returns_unavailable_when_init_fails(monkeypatch):
    # NVML 初始化拋錯（無卡/無驅動）→ 不可用快照、不拋例外
    fake = _make_fake_pynvml(fail_on="nvmlInit")
    monkeypatch.setattr(gpu, "pynvml", fake)
    snap = GpuSampler().sample()
    assert snap.available is False
    assert "初始化失敗" in (snap.detail or "")


def test_sample_returns_unavailable_when_read_fails(monkeypatch):
    # 初始化成功但取樣中途拋錯 → 降級為不可用，不讓 GUI 崩潰
    fake = _make_fake_pynvml(fail_on="nvmlDeviceGetHandleByIndex")
    monkeypatch.setattr(gpu, "pynvml", fake)
    snap = GpuSampler().sample()
    assert snap.available is False
    assert "取樣失敗" in (snap.detail or "")


def test_sample_reads_values_and_decodes_bytes_name(monkeypatch):
    # 正常路徑：回傳可用快照，bytes 型別的名稱要被 decode 成 str
    fake = _make_fake_pynvml(name=b"NVIDIA Test", util=73,
                             mem_used=6 * 1024 ** 3, mem_total=10 * 1024 ** 3,
                             temp=70)
    monkeypatch.setattr(gpu, "pynvml", fake)
    snap = GpuSampler().sample()
    assert snap.available is True
    assert snap.name == "NVIDIA Test"
    assert snap.gpu_util == 73
    assert snap.temperature == 70
    assert snap.mem_total_mb == 10 * 1024
    assert snap.mem_used_mb == 6 * 1024
    assert abs(snap.mem_percent - 60.0) < 0.01


def test_sample_handles_str_name(monkeypatch):
    # 新版 pynvml 的 nvmlDeviceGetName 回 str，也要正常
    fake = _make_fake_pynvml(name="RTX 3080")
    monkeypatch.setattr(gpu, "pynvml", fake)
    snap = GpuSampler().sample()
    assert snap.available is True
    assert snap.name == "RTX 3080"


def test_close_calls_shutdown_after_init(monkeypatch):
    # close() 應在初始化過後呼叫 nvmlShutdown，且可重複呼叫不出錯
    fake = _make_fake_pynvml()
    monkeypatch.setattr(gpu, "pynvml", fake)
    s = GpuSampler()
    s.sample()
    assert fake._calls["init"] == 1
    s.close()
    assert fake._calls["shutdown"] == 1
    s.close()  # 重複呼叫安全，不再 shutdown
    assert fake._calls["shutdown"] == 1


def test_snapshot_helpers_none_safe():
    # 不可用快照的衍生屬性都要回 None、不炸
    snap = GpuSnapshot(available=False, detail="x")
    assert snap.mem_used_mb is None
    assert snap.mem_total_mb is None
    assert snap.mem_percent is None


def test_real_gpu_smoke():
    # 有真的 NVIDIA GPU 時做非嚴格 smoke test；沒有就 skip（不讓測試依賴硬體）。
    real = GpuSampler()
    snap = real.sample()
    real.close()
    if not snap.available:
        pytest.skip("本機無 NVIDIA GPU 或未安裝驅動，略過真卡 smoke test")
    assert snap.name
    assert snap.mem_total and snap.mem_total > 0
    assert 0 <= snap.gpu_util <= 100
