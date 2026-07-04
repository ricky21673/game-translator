# 譯文後處理：提供「簡轉繁（台灣用語）」轉換器，供 Pipeline 與離線字典嵌入共用。
# 翻譯來源（現成字典、DeepL、Ollama）多半輸出簡體，統一在輸出處過一次 OpenCC，
# 不管來源一律轉成繁體台灣用語，符合使用者需求。


def make_traditional_converter():
    """
    回傳一個 callable(str) -> str 的繁體中文轉換器。

    - 內部使用 OpenCC 的 s2twp 設定（簡體 → 繁體，含台灣慣用語轉換，
      例如「软件」→「軟體」、「信息」→「資訊」）。
    - opencc 於函式內 lazy import：避免專案在未安裝 opencc 的環境下，
      只是 import 這支模組（甚至只是 import 整個專案）就直接爆炸。
    - 轉換器對非字串或空字串安全：非字串或空字串原樣回傳，不丟例外。
    """
    import opencc  # lazy import：延後到真正建立轉換器時才需要 opencc 已安裝

    converter = opencc.OpenCC("s2twp")

    def convert(text):
        # 非字串（None、數字等）或空字串：原樣回傳，避免 OpenCC 對非法輸入丟例外
        if not isinstance(text, str) or text == "":
            return text
        return converter.convert(text)

    return convert
