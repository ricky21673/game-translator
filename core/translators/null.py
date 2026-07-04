from .base import Translator


class NullTranslator(Translator):
    """離線用的恆等翻譯器：不呼叫任何線上 API，原樣回傳輸入文字。

    用途：搭配「離線字典模式」——把使用者既有的字典 JSON 當成快取，
    所有字串理論上都會命中快取；若仍有未命中的字串，交給這個
    Translator 處理時也只會原樣回傳（等同保留原文），不會發出任何
    網路請求，因此不需要 DeepL key 也不會因斷網而崩潰。
    """

    def translate(self, texts: list[str], target_lang: str,
                  source_lang: str | None = None) -> list[str]:
        # 不做任何轉換或網路呼叫，直接回傳與輸入相同內容的新 list
        return list(texts)
