# 測試 LocalTranslator（本地 Ollama 引擎）：用假 session，不打真的 Ollama 服務。
import pytest
import requests
from core.translators.local import LocalTranslator
from core.translators.deepl import TranslationError


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []  # 記錄每次呼叫的 url/headers/json
    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.resp


class RaisingSession:
    # 拋 requests 異常的假 session
    def post(self, *args, **kwargs):
        raise requests.RequestException("boom")


class SequenceFakeSession:
    # 依序回傳不同結果的假 session（用於測試多句翻譯順序）
    def __init__(self, contents):
        self.contents = contents
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        idx = len(self.calls) - 1
        content = self.contents[idx]
        return FakeResp(200, {"message": {"content": content}})


def test_translate_success_returns_text():
    # 測試：成功翻譯回傳譯文清單
    sess = FakeSession(FakeResp(200, {"message": {"content": "你好"}}))
    t = LocalTranslator("qwen2.5:14b", session=sess)
    out = t.translate(["こんにちは"], target_lang="ZH")
    assert out == ["你好"]


def test_uses_chat_endpoint_and_body_with_model_and_messages():
    # 測試：使用正確的端點，body 帶 model 與 messages（system+user）
    sess = FakeSession(FakeResp(200, {"message": {"content": "你好"}}))
    LocalTranslator("qwen2.5:14b", host="127.0.0.1", port=11434, session=sess).translate(
        ["こんにちは"], target_lang="ZH")
    call = sess.calls[0]
    assert call["url"] == "http://127.0.0.1:11434/api/chat"
    body = call["json"]
    assert body["model"] == "qwen2.5:14b"
    assert body["stream"] is False
    messages = body["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "こんにちは"


def test_model_not_found_raises_model_kind():
    # 測試：模型未安裝(404) 拋出 model 錯誤
    sess = FakeSession(FakeResp(404))
    t = LocalTranslator("no-such-model", session=sess)
    with pytest.raises(TranslationError) as e:
        t.translate(["こんにちは"], target_lang="ZH")
    assert e.value.kind == "model"


def test_other_status_code_raises_server():
    # 測試：其他非預期狀態碼拋出 server 錯誤
    sess = FakeSession(FakeResp(500))
    t = LocalTranslator("qwen2.5:14b", session=sess)
    with pytest.raises(TranslationError) as e:
        t.translate(["こんにちは"], target_lang="ZH")
    assert e.value.kind == "server"


def test_request_exception_raises_network():
    # 測試：requests 例外拋出 network 錯誤
    sess = RaisingSession()
    t = LocalTranslator("qwen2.5:14b", session=sess)
    with pytest.raises(TranslationError) as e:
        t.translate(["こんにちは"], target_lang="ZH")
    assert e.value.kind == "network"


def test_multiple_sentences_preserve_order_and_length():
    # 測試：多句翻譯時，回傳長度與輸入一致、順序一致（逐句呼叫）
    sess = SequenceFakeSession(["你好", "再見", "謝謝"])
    t = LocalTranslator("qwen2.5:14b", session=sess)
    out = t.translate(["こんにちは", "さようなら", "ありがとう"], target_lang="ZH")
    assert out == ["你好", "再見", "謝謝"]
    assert len(sess.calls) == 3
