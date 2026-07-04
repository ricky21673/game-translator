import requests
from .base import Translator

# DeepL 官方文檔端點
FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"
BATCH = 50  # 官方文檔：單次最多 50 筆


class TranslationError(Exception):
    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind


class DeepLTranslator(Translator):
    def __init__(self, auth_key: str, free: bool = True, session=None):
        self.auth_key = auth_key
        self.url = FREE_URL if free else PRO_URL
        self.session = session or requests.Session()

    def translate(self, texts, target_lang, source_lang=None):
        # 批次處理：最多 50 筆為一批
        out: list[str] = []
        for i in range(0, len(texts), BATCH):
            out.extend(self._call(texts[i:i + BATCH], target_lang, source_lang))
        return out

    def _call(self, texts, target_lang, source_lang):
        # 構建 DeepL 請求
        headers = {"Authorization": f"DeepL-Auth-Key {self.auth_key}"}
        data = [("target_lang", target_lang)]
        if source_lang:
            data.append(("source_lang", source_lang))
        data.extend(("text", t) for t in texts)

        # 發送請求
        try:
            resp = self.session.post(self.url, headers=headers, data=data, timeout=30)
        except requests.RequestException as e:
            raise TranslationError("network", str(e))

        # 處理回應狀態碼與錯誤分類
        code = resp.status_code
        if code == 200:
            return [item["text"] for item in resp.json()["translations"]]
        if code == 456:
            raise TranslationError("quota", "DeepL 額度用盡 (456)")
        if code == 403:
            raise TranslationError("auth", "DeepL 認證失敗 (403)")
        if code == 429:
            raise TranslationError("rate", "DeepL 速率過高 (429)")
        raise TranslationError("server", f"DeepL 回應非預期狀態碼: {code}")
