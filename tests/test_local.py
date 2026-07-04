# 測試 LocalTranslator（本地 Ollama 引擎）：用假 session，不打真的 Ollama 服務。
import pytest
import requests
from core.translators.local import LocalTranslator, MAX_RETRIES
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
    def __init__(self):
        self.calls = []
    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
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


class PerSentenceFakeSession:
    """依「原文內容」決定行為的假 session，用於模擬單句容錯 + 重試。

    behaviors: dict，key 為原文字串，value 為該句的行為：
    - ("ok", 譯文字串)：直接成功
    - ("raise",)：一直拋 requests.RequestException（模擬逾時/斷線，重試也救不回）
    - ("fail_then_ok", 譯文字串, 需失敗次數)：前 N 次失敗（拋例外），之後成功

    每句的呼叫次數各自獨立計數（用原文字串當 key），藉此驗證重試邏輯。
    """

    def __init__(self, behaviors: dict):
        self.behaviors = behaviors
        self.calls = []
        self._call_count_by_text: dict[str, int] = {}

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        user_text = json["messages"][1]["content"]
        self._call_count_by_text[user_text] = (
            self._call_count_by_text.get(user_text, 0) + 1
        )
        call_no = self._call_count_by_text[user_text]

        behavior = self.behaviors[user_text]
        kind = behavior[0]
        if kind == "ok":
            return FakeResp(200, {"message": {"content": behavior[1]}})
        if kind == "raise":
            raise requests.RequestException("boom")
        if kind == "fail_then_ok":
            _, content, fail_times = behavior
            if call_no <= fail_times:
                raise requests.RequestException("boom")
            return FakeResp(200, {"message": {"content": content}})
        raise AssertionError(f"未知的假 session 行為: {behavior}")


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


def test_model_not_found_falls_back_to_original_text_without_raising():
    # 測試：模型未安裝(404) 重試用盡後保留原文、不拋例外（單句容錯）
    sess = FakeSession(FakeResp(404))
    t = LocalTranslator("no-such-model", session=sess)
    out = t.translate(["こんにちは"], target_lang="ZH")
    assert out == ["こんにちは"]  # 保留原文
    assert len(sess.calls) == MAX_RETRIES + 1  # 第一次嘗試 + 重試次數


def test_other_status_code_falls_back_to_original_text_without_raising():
    # 測試：其他非預期狀態碼(500) 重試用盡後保留原文、不拋例外
    sess = FakeSession(FakeResp(500))
    t = LocalTranslator("qwen2.5:14b", session=sess)
    out = t.translate(["こんにちは"], target_lang="ZH")
    assert out == ["こんにちは"]
    assert len(sess.calls) == MAX_RETRIES + 1


def test_request_exception_falls_back_to_original_text_without_raising():
    # 測試：requests 例外（逾時/斷線）重試用盡後保留原文、不拋例外
    sess = RaisingSession()
    t = LocalTranslator("qwen2.5:14b", session=sess)
    out = t.translate(["こんにちは"], target_lang="ZH")
    assert out == ["こんにちは"]
    assert len(sess.calls) == MAX_RETRIES + 1


def test_multiple_sentences_preserve_order_and_length():
    # 測試：多句翻譯時，回傳長度與輸入一致、順序一致（逐句呼叫）
    sess = SequenceFakeSession(["你好", "再見", "謝謝"])
    t = LocalTranslator("qwen2.5:14b", session=sess)
    out = t.translate(["こんにちは", "さようなら", "ありがとう"], target_lang="ZH")
    assert out == ["你好", "再見", "謝謝"]
    assert len(sess.calls) == 3


def test_single_sentence_failure_falls_back_while_others_translate_normally(capsys):
    # 核心容錯情境：一批句子中「某一句」持續拋例外（逾時/忙碌/斷線），
    # 其餘句子應正常翻譯完成，整體呼叫不拋例外，長度與順序仍與輸入一致，
    # 失敗句回傳原文，並印出繁中警告（含該句前 20 字）。
    behaviors = {
        "こんにちは": ("ok", "你好"),
        "壊れる文章": ("raise",),  # 這句持續失敗，重試也救不回
        "ありがとう": ("ok", "謝謝"),
    }
    sess = PerSentenceFakeSession(behaviors)
    t = LocalTranslator("qwen2.5:14b", session=sess)

    out = t.translate(["こんにちは", "壊れる文章", "ありがとう"], target_lang="ZH")

    # 長度與順序仍與輸入一致；失敗句保留原文，其餘句正常翻譯
    assert out == ["你好", "壊れる文章", "謝謝"]

    # 失敗句應被重試 MAX_RETRIES + 1 次，其餘句只呼叫一次
    assert sess._call_count_by_text["壊れる文章"] == MAX_RETRIES + 1
    assert sess._call_count_by_text["こんにちは"] == 1
    assert sess._call_count_by_text["ありがとう"] == 1

    # 警告訊息含前 20 字、以繁中輸出
    captured = capsys.readouterr()
    assert "警告" in captured.out
    assert "壊れる文章"[:20] in captured.out


def test_sentence_recovers_after_retry_within_max_retries():
    # 測試：某句前 1 次失敗、第 2 次（第一次重試）成功 -> 應回傳翻譯結果，
    # 不落入「保留原文」的降級分支
    behaviors = {
        "こんにちは": ("fail_then_ok", "你好", 1),  # 第一次失敗，重試後成功
    }
    sess = PerSentenceFakeSession(behaviors)
    t = LocalTranslator("qwen2.5:14b", session=sess)

    out = t.translate(["こんにちは"], target_lang="ZH")

    assert out == ["你好"]
    assert sess._call_count_by_text["こんにちは"] == 2  # 第一次失敗 + 重試成功


def test_all_sentences_fail_returns_all_original_without_raising():
    # 測試：Ollama 完全掛掉（每句都失敗）時，不 fail-fast，
    # 全部保留原文繼續，回傳長度與輸入一致
    behaviors = {
        "こんにちは": ("raise",),
        "さようなら": ("raise",),
    }
    sess = PerSentenceFakeSession(behaviors)
    t = LocalTranslator("qwen2.5:14b", session=sess)

    out = t.translate(["こんにちは", "さようなら"], target_lang="ZH")

    assert out == ["こんにちは", "さようなら"]
