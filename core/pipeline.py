from .cache import DictCache
from .translators.base import Translator


class Pipeline:
    def __init__(self, cache: DictCache, translator: Translator,
                 target_lang: str, source_lang: str | None = None,
                 postprocess=None):
        # 初始化管線：快取、翻譯引擎、目標語言、來源語言（可選項）、
        # 後處理函式（可選項，callable(str) -> str，例如簡轉繁；預設 None 表示不處理，
        # 完全維持既有行為）
        self.cache = cache
        self.translator = translator
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.postprocess = postprocess

    def translate(self, texts: list[str]) -> list[str]:
        # 收集未命中且去重（保留首次出現順序）
        missing: list[str] = []
        seen: set[str] = set()
        for t in texts:
            if self.cache.get(t) is None and t not in seen:
                seen.add(t)
                missing.append(t)

        # 若有未命中的文字，送引擎翻譯、寫回快取並保存
        if missing:
            translated = self.translator.translate(
                missing, self.target_lang, self.source_lang)
            for src, dst in zip(missing, translated):
                self.cache.put(src, dst)
            self.cache.save()

        # 回傳與輸入等長且順序一致的譯文（全部從快取取得）
        results = [self.cache.get(t) for t in texts]

        # 若有設定後處理，對「每一個輸出字串」套用（不論來自快取命中或引擎新翻），
        # 維持與輸入等長、順序一致
        if self.postprocess is not None:
            results = [self.postprocess(r) for r in results]

        return results
