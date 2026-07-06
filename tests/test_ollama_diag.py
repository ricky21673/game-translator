# 測試 ollama_diag（本地 Ollama 健檢/掃描）：用假 session，不打真的 Ollama。
import pytest
import requests

from core.ollama_diag import (
    check_service,
    probe_model,
    diagnose,
    format_scan_result,
    ModelProbe,
    OllamaDiagnosis,
)


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class RoutingSession:
    """同時支援 GET /api/tags 與 POST /api/chat 的假 session。

    - get：回固定的模型清單。
    - post：依 body 的 model 名決定成功（200 吐譯文）或失敗（404）。
    """

    def __init__(self, models, ok_models=(), tags_status=200):
        self.models = list(models)
        self.ok_models = set(ok_models)
        self.tags_status = tags_status
        self.get_calls = []
        self.post_calls = []

    def get(self, url, timeout=None):
        self.get_calls.append(url)
        return FakeResp(self.tags_status,
                        {"models": [{"name": n} for n in self.models]})

    def post(self, url, json=None, timeout=None):
        self.post_calls.append(json)
        model = json["model"]
        if model in self.ok_models:
            return FakeResp(200, {"message": {"content": "你好"}})
        return FakeResp(404)


class DownSession:
    # GET 一律拋連線例外（模擬 Ollama 沒開）
    def get(self, url, timeout=None):
        raise requests.RequestException("connection refused")


# -- check_service ------------------------------------------------------------


def test_check_service_down_when_connection_refused():
    up, models, detail = check_service(session=DownSession())
    assert up is False
    assert models == []
    assert "Ollama" in detail


def test_check_service_up_lists_models():
    sess = RoutingSession(["a:latest", "b:latest"])
    up, models, detail = check_service(session=sess)
    assert up is True
    assert models == ["a:latest", "b:latest"]
    assert "2" in detail


def test_check_service_up_but_empty_is_distinct_from_down():
    # 服務有開但沒裝模型：up=True、清單空——與「沒開」明確區分
    sess = RoutingSession([])
    up, models, _ = check_service(session=sess)
    assert up is True
    assert models == []


def test_check_service_non_200_is_down():
    sess = RoutingSession(["x"], tags_status=500)
    up, _, detail = check_service(session=sess)
    assert up is False
    assert "500" in detail


# -- probe_model --------------------------------------------------------------


def test_probe_model_ok_returns_sample_translation():
    sess = RoutingSession(["good"], ok_models=["good"])
    p = probe_model("good", session=sess)
    assert p.ok is True
    assert p.detail == "你好"


def test_probe_model_fail_points_at_model_name():
    sess = RoutingSession(["bad"], ok_models=[])  # 一律 404
    p = probe_model("bad", session=sess)
    assert p.ok is False
    assert "bad" in p.detail  # 失敗原因要點名是哪顆模型


# -- diagnose（整合）---------------------------------------------------------


def test_diagnose_reports_only_usable_models_as_green():
    sess = RoutingSession(
        ["good:latest", "bad:latest", "good2:latest"],
        ok_models=["good:latest", "good2:latest"])
    diag = diagnose(session=sess)
    assert isinstance(diag, OllamaDiagnosis)
    assert diag.service_up is True
    assert diag.models == ["good:latest", "bad:latest", "good2:latest"]
    # 只有實測可用的兩顆是綠燈，保留偵測順序
    assert diag.usable_models == ["good:latest", "good2:latest"]
    # 每顆都探測過一次
    assert len(diag.probes) == 3


def test_diagnose_service_down_skips_probing():
    diag = diagnose(session=DownSession())
    assert diag.service_up is False
    assert diag.probes == []
    assert diag.usable_models == []


def test_diagnose_probe_false_lists_without_testing():
    sess = RoutingSession(["a", "b"], ok_models=["a"])
    diag = diagnose(session=sess, probe=False)
    assert diag.service_up is True
    assert diag.models == ["a", "b"]
    assert diag.probes == []  # 沒試翻
    assert sess.post_calls == []


def test_diagnose_only_probes_selected_model():
    sess = RoutingSession(["a", "b", "c"], ok_models=["a", "b", "c"])
    diag = diagnose(session=sess, only={"b"})
    assert [p.name for p in diag.probes] == ["b"]
    assert diag.usable_models == ["b"]


# -- format_scan_result（純函式）---------------------------------------------


def test_format_scan_result_service_down():
    diag = OllamaDiagnosis(service_up=False, detail="連不上 Ollama 服務")
    out = format_scan_result(diag)
    assert out.startswith("✗")
    assert "連不上 Ollama 服務" in out


def test_format_scan_result_up_but_no_models():
    diag = OllamaDiagnosis(service_up=True, models=[])
    out = format_scan_result(diag)
    assert "尚未安裝任何模型" in out


def test_format_scan_result_marks_green_and_red_and_suggests():
    diag = OllamaDiagnosis(
        service_up=True,
        models=["good:latest", "bad:latest"],
        probes=[ModelProbe("good:latest", True, "你好"),
                ModelProbe("bad:latest", False, "Ollama 找不到模型")])
    out = format_scan_result(diag)
    assert "🟢" in out and "good:latest" in out
    assert "🔴" in out and "bad:latest" in out
    assert "建議在模型欄選用：good:latest" in out


def test_format_scan_result_none_usable():
    diag = OllamaDiagnosis(
        service_up=True,
        models=["bad:latest"],
        probes=[ModelProbe("bad:latest", False, "叫不動")])
    out = format_scan_result(diag)
    assert "沒有任何模型試翻成功" in out
