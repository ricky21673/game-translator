"""本地 Ollama 健檢/掃描：確認服務有沒有開、裝了哪些模型、逐一實測哪顆真的能翻。

供 GUI「掃描/測試模型」用：讓使用者在部署遊戲、跑整片翻譯「之前」，先一眼看出
- Ollama 服務是否啟動（連得上）
- 裝了哪些模型
- 每顆模型「叫不叫得動」（綠燈 = 可用；紅燈 = 名字對不上/沒 chat template 等）

避免像之前那樣：選了個名字對不上的模型、按下去才噴滿屏 404、整片遊戲一句沒翻。
探測只驗「叫得動且有吐字」，不評翻譯品質。
"""
from dataclasses import dataclass, field

import requests

from .ollama_util import DEFAULT_HOST, DEFAULT_PORT
from .translators.local import LocalTranslator
from .translators.deepl import TranslationError

PROBE_SAMPLE = "こんにちは"  # 拿來試翻的日文樣本（極短，只為探測）
SERVICE_TIMEOUT = 5  # 查服務/清單，逾時不用等太久


@dataclass
class ModelProbe:
    """單顆模型的探測結果。ok=True 時 detail 放譯文樣本；False 時放失敗原因。"""
    name: str
    ok: bool
    detail: str = ""


@dataclass
class OllamaDiagnosis:
    """一次完整健檢的結果。"""
    service_up: bool
    detail: str = ""
    models: list[str] = field(default_factory=list)
    probes: list[ModelProbe] = field(default_factory=list)

    @property
    def usable_models(self) -> list[str]:
        # 實測可用（綠燈）的模型名稱，保留偵測順序。
        return [p.name for p in self.probes if p.ok]


def check_service(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                  session=None) -> tuple[bool, list[str], str]:
    """探測 Ollama 服務。回 (service_up, models, detail)。

    - 連得上且 GET /api/tags 回 200 → service_up=True，並解析模型清單。
    - 連不上（服務沒開）與「開著但沒模型」是兩回事，這裡分得清楚：前者 up=False。
    全程不拋例外，任何異常都轉成 up=False + 說明字串。
    """
    sess = session or requests.Session()
    try:
        resp = sess.get(f"http://{host}:{port}/api/tags", timeout=SERVICE_TIMEOUT)
    except requests.RequestException:
        return False, [], "連不上 Ollama 服務，請確認 Ollama 已啟動（工作列圖示還在）"
    if resp.status_code != 200:
        return False, [], f"Ollama 服務回應非 200（{resp.status_code}）"
    try:
        models = [m["name"] for m in resp.json().get("models", [])]
    except (ValueError, KeyError, TypeError):
        return True, [], "服務有回應，但模型清單格式無法解析"
    return True, models, f"服務正常，偵測到 {len(models)} 個模型"


def probe_model(model: str, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                session=None, sample: str = PROBE_SAMPLE) -> ModelProbe:
    """對單顆模型試翻一句，判斷是否可用。

    用 LocalTranslator 走的就是「實際翻譯路徑」，並把 abort_after 設為 1，讓
    單次失敗立刻現形（不會被 fail-soft 吞掉）。成功且吐出非空、非原樣的譯文 → 可用。
    """
    t = LocalTranslator(model, host=host, port=port, session=session, abort_after=1)
    try:
        out = t.translate([sample], target_lang="ZH")
    except TranslationError as e:
        return ModelProbe(model, False, str(e))
    text = (out[0] if out else "").strip()
    if not text or text == sample:
        return ModelProbe(model, False, "模型有回應，但沒吐出有效譯文")
    return ModelProbe(model, True, text)


def format_scan_result(diag: "OllamaDiagnosis") -> str:
    """把一次健檢結果組成給使用者看的多行文字（純函式，方便單測）。"""
    if not diag.service_up:
        return "✗ " + diag.detail
    if not diag.models:
        return "✓ Ollama 服務正常，但尚未安裝任何模型（請先 ollama pull 或匯入 Sakura）"
    lines = ["Ollama 服務正常，共 %d 個模型：" % len(diag.models), ""]
    for p in diag.probes:
        if p.ok:
            lines.append("🟢 可用　%s　（試翻：%s）" % (p.name, p.detail))
        else:
            lines.append("🔴 不可用　%s　（%s）" % (p.name, p.detail))
    usable = diag.usable_models
    lines.append("")
    if usable:
        lines.append("建議在模型欄選用：%s" % usable[0])
    else:
        lines.append("沒有任何模型試翻成功，請用 `ollama list` 核對名稱或重新安裝模型。")
    return "\n".join(lines)


def diagnose(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, session=None,
             probe: bool = True, only=None) -> OllamaDiagnosis:
    """完整健檢：服務 → 清單 → 逐一試翻。

    - probe=False：只查服務與清單，不試翻（快，供狀態燈用）。
    - only：可選，只探測清單中屬於這個集合的模型（例如只測使用者選的那顆）。
    """
    up, models, detail = check_service(host, port, session=session)
    diag = OllamaDiagnosis(service_up=up, detail=detail, models=models)
    if not up or not probe:
        return diag
    for m in models:
        if only is not None and m not in only:
            continue
        diag.probes.append(probe_model(m, host, port, session=session))
    return diag
