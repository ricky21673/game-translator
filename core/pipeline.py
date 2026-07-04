from .cache import DictCache
from .translators.base import Translator

# 分批大小：長時間全翻（上萬句、跑好幾小時）若「全部翻完才存一次」，
# 中途當機/斷線會讓前面全部白做。改成每 BATCH 句就寫回快取並存檔一次，
# 中途出錯最多只丟最後一批未存進去的進度，重跑時已存的部分會直接命中快取續翻。
# 之後如需調整分批大小，改這個常數即可。
BATCH = 50


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

        # 若有未命中的文字，切成小批逐批送引擎翻譯、寫回快取並保存。
        # 邊翻邊存：每一批翻完就立刻 save 一次，中途崩潰最多只丟最後一批，
        # 已存進 JSON 的部分下次載入即會命中快取、可從中斷處續跑。
        if missing:
            for i in range(0, len(missing), BATCH):
                batch = missing[i:i + BATCH]
                translated = self.translator.translate(
                    batch, self.target_lang, self.source_lang)
                for src, dst in zip(batch, translated):
                    self.cache.put(src, dst)
                self.cache.save()

        # 回傳與輸入等長且順序一致的譯文（全部從快取取得）
        results = [self.cache.get(t) for t in texts]

        # 若有設定後處理，對「每一個輸出字串」套用（不論來自快取命中或引擎新翻），
        # 維持與輸入等長、順序一致
        if self.postprocess is not None:
            results = [self.postprocess(r) for r in results]

        return results
