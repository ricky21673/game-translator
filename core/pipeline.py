from .cache import DictCache
from .translators.base import Translator


class Pipeline:
    def __init__(self, cache: DictCache, translator: Translator,
                 target_lang: str, source_lang: str | None = None):
        # 初始化管線：快取、翻譯引擎、目標語言、來源語言（選選項）
        self.cache = cache
        self.translator = translator
        self.target_lang = target_lang
        self.source_lang = source_lang

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
        return [self.cache.get(t) for t in texts]
