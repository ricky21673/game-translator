# 測試 list_ollama_models：用假 session，不打真的 Ollama 服務。
from core.ollama_util import list_ollama_models


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp = resp
        self.exc = exc
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append({"url": url, "timeout": timeout})
        if self.exc is not None:
            raise self.exc
        return self.resp


def test_list_ollama_models_parses_names_from_tags_response():
    # 正常情況：/api/tags 回 200 + models 陣列 → 回傳模型名稱清單
    payload = {"models": [{"name": "qwen2.5:14b"}, {"name": "sakura-galtransl:latest"}]}
    sess = FakeSession(resp=FakeResp(200, payload))
    out = list_ollama_models(session=sess)
    assert out == ["qwen2.5:14b", "sakura-galtransl:latest"]
    assert sess.calls[0]["url"] == "http://127.0.0.1:11434/api/tags"


def test_list_ollama_models_empty_models_returns_empty_list():
    # models 陣列為空 → 回傳空清單
    sess = FakeSession(resp=FakeResp(200, {"models": []}))
    assert list_ollama_models(session=sess) == []


def test_list_ollama_models_non_200_returns_empty_list():
    # 非 200（如服務未啟動但有東西回應、或 404）→ 回傳空清單，不拋例外
    sess = FakeSession(resp=FakeResp(500))
    assert list_ollama_models(session=sess) == []


def test_list_ollama_models_connection_error_returns_empty_list():
    # 連不上 Ollama（ConnectionError 等）→ 回傳空清單，不拋例外
    sess = FakeSession(exc=ConnectionError("boom"))
    assert list_ollama_models(session=sess) == []


def test_list_ollama_models_malformed_response_returns_empty_list():
    # 回應格式不符預期（缺 name 鍵）→ 回傳空清單，不拋例外
    sess = FakeSession(resp=FakeResp(200, {"models": [{"unexpected": "field"}]}))
    assert list_ollama_models(session=sess) == []


def test_list_ollama_models_custom_host_and_port():
    # 自訂 host/port 應反映在請求網址上
    sess = FakeSession(resp=FakeResp(200, {"models": []}))
    list_ollama_models(host="192.168.1.5", port=12345, session=sess)
    assert sess.calls[0]["url"] == "http://192.168.1.5:12345/api/tags"
