"""
GPU 監控取樣：用 nvidia-ml-py（提供的模組名為 pynvml）讀 NVIDIA GPU 的
使用率 / 顯存 / 溫度，供翻譯監控面板每秒刷新顯示。

設計原則：
- 全程優雅降級：沒有 NVIDIA GPU、驅動未安裝、或 pynvml 匯入失敗時，
  一律回傳「不可用」快照（available=False），絕不拋例外中斷 GUI。
  本地 Ollama 常跑在有卡的機器、但也可能被搬到沒卡的環境跑 DeepL/離線模式，
  所以「沒有卡」必須是正常路徑，而非錯誤。
- 純資料取樣，不碰 Qt、不碰執行緒；GUI 端自行用 QTimer 每秒呼叫 sample()。
- 依 nvidia-ml-py 官方 API：nvmlInit / nvmlDeviceGetHandleByIndex /
  nvmlDeviceGetUtilizationRates / nvmlDeviceGetMemoryInfo /
  nvmlDeviceGetTemperature（NVML_TEMPERATURE_GPU）/ nvmlShutdown。
  nvmlDeviceGetName 在不同版本可能回 bytes 或 str，兩者都處理。
"""
from __future__ import annotations

from dataclasses import dataclass

try:  # pynvml 由 nvidia-ml-py 套件提供；未安裝時整組功能降級為不可用
    import pynvml  # type: ignore
    _PYNVML_IMPORT_ERROR: Exception | None = None
except Exception as e:  # pragma: no cover - 端視環境是否裝了 nvidia-ml-py
    pynvml = None  # type: ignore
    _PYNVML_IMPORT_ERROR = e


@dataclass(frozen=True)
class GpuSnapshot:
    """
    單次 GPU 取樣結果（不可變）。available=False 時其餘欄位皆為 None，
    detail 帶不可用原因（例如「未安裝 nvidia-ml-py」或「找不到 NVIDIA GPU」）。
    """
    available: bool
    name: str | None = None
    gpu_util: int | None = None          # GPU 使用率 %
    mem_used: int | None = None          # 已用顯存 bytes
    mem_total: int | None = None         # 總顯存 bytes
    temperature: int | None = None       # 溫度 °C
    detail: str | None = None            # 不可用時的說明

    @property
    def mem_used_mb(self) -> int | None:
        return None if self.mem_used is None else self.mem_used // (1024 * 1024)

    @property
    def mem_total_mb(self) -> int | None:
        return None if self.mem_total is None else self.mem_total // (1024 * 1024)

    @property
    def mem_percent(self) -> float | None:
        if not self.mem_used or not self.mem_total:
            return None
        return self.mem_used / self.mem_total * 100.0


def _decode_name(name) -> str:
    # nvmlDeviceGetName 舊版回 bytes、新版回 str，統一成 str。
    if isinstance(name, bytes):
        return name.decode("utf-8", errors="replace")
    return str(name)


class GpuSampler:
    """
    GPU 取樣器：第一次 sample() 時惰性初始化 NVML；之後每次呼叫直接讀值。

    - 惰性初始化：建構時不觸碰 NVML，避免「只是 import gui」就去戳驅動。
      這也讓沒有卡的環境建立 GpuSampler 完全無副作用。
    - 執行緒安全定位：本類別本身不加鎖，設計上由 GUI 主執行緒的 QTimer 單一
      呼叫者定期呼叫 sample()，不跨執行緒共用。翻譯工作在另一條執行緒跑，
      兩者不共用這個物件，故無資料競爭。
    - 任一 NVML 呼叫拋錯都被吞掉並回傳不可用快照，確保 GUI 不因取樣失敗而崩潰。
    """

    def __init__(self, index: int = 0):
        self.index = index
        self._inited = False
        self._init_failed_detail: str | None = None

    def _ensure_init(self) -> bool:
        if self._inited:
            return True
        if pynvml is None:
            self._init_failed_detail = (
                "未安裝 nvidia-ml-py（pynvml 匯入失敗：%s）" % _PYNVML_IMPORT_ERROR)
            return False
        try:
            pynvml.nvmlInit()
        except Exception as e:  # 驅動未安裝 / 無 NVIDIA GPU
            self._init_failed_detail = "NVML 初始化失敗：%s" % e
            return False
        self._inited = True
        return True

    def sample(self) -> GpuSnapshot:
        if not self._ensure_init():
            return GpuSnapshot(available=False, detail=self._init_failed_detail)
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(self.index)
            name = _decode_name(pynvml.nvmlDeviceGetName(handle))
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            temp = pynvml.nvmlDeviceGetTemperature(
                handle, pynvml.NVML_TEMPERATURE_GPU)
            return GpuSnapshot(
                available=True,
                name=name,
                gpu_util=int(util.gpu),
                mem_used=int(mem.used),
                mem_total=int(mem.total),
                temperature=int(temp),
            )
        except Exception as e:  # 取樣中任何失敗都降級，不讓 GUI 崩潰
            return GpuSnapshot(available=False, detail="GPU 取樣失敗：%s" % e)

    def close(self) -> None:
        # 對稱釋放 NVML；重複呼叫或未初始化都安全（吞例外）。
        if self._inited and pynvml is not None:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._inited = False
