import pytest
import requests
from core.translators.deepl import DeepLTranslator, TranslationError


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.last = None
    def post(self, url, headers=None, data=None, timeout=None):
        self.last = {"url": url, "headers": headers, "data": data}
        return self.resp


class RaisingSession:
    # 拋 requests 異常的假 session
    def post(self, *args, **kwargs):
        raise requests.RequestException("boom")


class CountingFakeSession:
    # 回傳對應數量譯文的假 session（用於測試批次分割）
    def __init__(self):
        self.calls = 0
    def post(self, url, headers=None, data=None, timeout=None):
        self.calls += 1
        # 從 data（list of tuples）中挑出 key 為 "text" 的值
        texts = [val for key, val in data if key == "text"]
        # 每筆輸入回傳 "original_t" 格式
        payload = {
            "translations": [{"text": f"{t}_t"} for t in texts]
        }
        return FakeResp(200, payload)


def test_translate_success_returns_texts():
    # 測試：成功翻譯回傳譯文清單
    resp = FakeResp(200, {"translations": [
        {"detected_source_language": "JA", "text": "是"},
        {"detected_source_language": "JA", "text": "否"},
    ]})
    sess = FakeSession(resp)
    t = DeepLTranslator("key-123", free=True, session=sess)
    out = t.translate(["はい", "いいえ"], target_lang="ZH")
    assert out == ["是", "否"]

def test_uses_free_endpoint_and_auth_header():
    # 測試：使用 free 端點與正確的授權標頭
    sess = FakeSession(FakeResp(200, {"translations": [{"text": "是"}]}))
    DeepLTranslator("key-123", free=True, session=sess).translate(["はい"], target_lang="ZH")
    assert sess.last["url"] == "https://api-free.deepl.com/v2/translate"
    assert sess.last["headers"]["Authorization"] == "DeepL-Auth-Key key-123"

def test_uses_pro_endpoint():
    # 測試：使用 pro 端點
    sess = FakeSession(FakeResp(200, {"translations": [{"text": "是"}]}))
    DeepLTranslator("k", free=False, session=sess).translate(["はい"], target_lang="ZH")
    assert sess.last["url"] == "https://api.deepl.com/v2/translate"

def test_quota_exceeded_raises():
    # 測試：額度用盡(456)拋出 quota 錯誤
    sess = FakeSession(FakeResp(456))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "quota"

def test_auth_failure_raises():
    # 測試：認證失敗(403)拋出 auth 錯誤
    sess = FakeSession(FakeResp(403))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "auth"

def test_rate_limit_raises():
    # 測試：速率限制(429)拋出 rate 錯誤
    sess = FakeSession(FakeResp(429))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "rate"

def test_other_status_code_raises_server():
    # 測試：其他非預期狀態碼(400/413)拋出 server 錯誤
    sess = FakeSession(FakeResp(400))
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "server"

def test_request_exception_raises_network():
    # 測試：requests 例外拋出 network 錯誤
    sess = RaisingSession()
    with pytest.raises(TranslationError) as e:
        DeepLTranslator("k", session=sess).translate(["はい"], target_lang="ZH")
    assert e.value.kind == "network"

def test_batch_splits_over_50_items():
    # 測試：超過 50 筆會分批且順序正確
    sess = CountingFakeSession()
    texts = [f"s{i}" for i in range(60)]
    t = DeepLTranslator("k", session=sess)
    out = t.translate(texts, target_lang="ZH")

    # 驗證分批次數：50 + 10 = 2 次
    assert sess.calls == 2
    # 驗證回傳結果長度 60
    assert len(out) == 60
    # 驗證順序與輸入一致
    for i in range(60):
        assert out[i] == f"s{i}_t"
