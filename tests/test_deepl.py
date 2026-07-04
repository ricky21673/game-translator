import pytest
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
