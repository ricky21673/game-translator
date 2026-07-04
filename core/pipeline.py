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
                 postprocess=None, global_cache: DictCache | None = None):
        # 初始化管線：快取、翻譯引擎、目標語言、來源語言（可選項）、
        # 後處理函式（可選項，callable(str) -> str，例如簡轉繁；預設 None 表示不處理，
        # 完全維持既有行為）
        self.cache = cache
        self.translator = translator
        self.target_lang = target_lang
        self.source_lang = source_lang
        self.postprocess = postprocess
        # 全域共用字典（可選項）：跨所有遊戲累積的翻譯快取。預設 None 時，
        # 查詢與寫回都只碰 self.cache，行為與加這個功能之前完全一致。
        self.global_cache = global_cache

    def _lookup(self, t: str) -> str | None:
        # 分層查詢：遊戲私有字典（self.cache）優先，命中就直接回傳；
        # 沒命中才查全域共用字典（self.global_cache，若有設定）；
        # 兩者都沒有就回 None，交由呼叫端判定為「未命中」。
        hit = self.cache.get(t)
        if hit is not None:
            return hit
        if self.global_cache is not None:
            return self.global_cache.get(t)
        return None

    def translate(self, texts: list[str]) -> list[str]:
        # 收集未命中且去重（保留首次出現順序）。用 _lookup 判斷，
        # 讓「全域字典已有但遊戲私有字典沒有」的句子直接算命中，不必再送引擎。
        missing: list[str] = []
        seen: set[str] = set()
        for t in texts:
            if self._lookup(t) is None and t not in seen:
                seen.add(t)
                missing.append(t)

        # 若有未命中的文字，切成小批逐批送引擎翻譯、寫回快取並保存。
        # 邊翻邊存：每一批翻完就立刻 save 一次，中途崩潰最多只丟最後一批，
        # 已存進 JSON 的部分下次載入即會命中快取、可從中斷處續跑。
        # 同時寫回全域共用字典（若有設定），讓這批新翻譯之後在其他遊戲也能直接命中。
        if missing:
            for i in range(0, len(missing), BATCH):
                batch = missing[i:i + BATCH]
                translated = self.translator.translate(
                    batch, self.target_lang, self.source_lang)
                for src, dst in zip(batch, translated):
                    self.cache.put(src, dst)
                    if self.global_cache is not None:
                        self.global_cache.put(src, dst)
                self.cache.save()
                if self.global_cache is not None:
                    self.global_cache.save()

        # 回傳與輸入等長且順序一致的譯文（分層查詢：私有字典優先，其次全域字典）
        results = [self._lookup(t) for t in texts]

        # 若有設定後處理，對「每一個輸出字串」套用（不論來自快取命中或引擎新翻），
        # 維持與輸入等長、順序一致
        if self.postprocess is not None:
            results = [self.postprocess(r) for r in results]

        return results
