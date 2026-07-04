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
                 postprocess=None, global_cache: DictCache | None = None,
                 store_converted: bool = False):
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
        # store_converted：只在「有 postprocess（例如開了繁體）」時才有意義，
        # 決定「引擎新翻的條目」寫進 cache/global_cache 時要存哪種內容：
        # - False（預設）：原樣（通常是簡體）寫進去，維持現況——JSON 存簡體，
        #   輸出時再由既有 postprocess 邏輯轉繁。
        # - True：先套用 postprocess（轉繁）再寫進去，JSON 裡就是繁體；
        #   輸出時仍會再套一次 postprocess，但 s2twp 對已是繁體的文字近乎無變化
        #   （等冪），故安全、不會壞。
        # 注意：這個開關只影響「引擎新翻的條目」，既有種子字典載入的舊條目不會被
        # 回頭轉換，維持原樣——想要整份 JSON 全繁體，需從 0 翻或改用繁體種子字典。
        self.store_converted = store_converted

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

    def translate(self, texts: list[str], progress_cb=None) -> list[str]:
        # progress_cb（可選）：句級進度回呼 callable(done, total)，回報「未命中、
        # 實際要送引擎翻的段落」翻了幾句 / 共幾句。與 GUI 檔案級/階段級的 phase
        # progress 語意不同（那是檔案數），故獨立成一條回呼，交由呼叫端接到獨立的
        # segment_progress signal。全部命中快取時 total=0，只回報一次 (0, 0)，
        # 讓 GUI 能立刻把進度條歸零/顯示「無需翻譯」。預設 None 時完全不回報，
        # 行為與加這個功能之前一致。
        #
        # 收集未命中且去重（保留首次出現順序）。用 _lookup 判斷，
        # 讓「全域字典已有但遊戲私有字典沒有」的句子直接算命中，不必再送引擎。
        missing: list[str] = []
        seen: set[str] = set()
        for t in texts:
            if self._lookup(t) is None and t not in seen:
                seen.add(t)
                missing.append(t)

        total_missing = len(missing)
        if progress_cb is not None:
            # 一開始先回報一次總數（done=0），讓 GUI 知道要翻幾句、能算速度/ETA。
            progress_cb(0, total_missing)

        # 若有未命中的文字，切成小批逐批送引擎翻譯、寫回快取並保存。
        # 邊翻邊存：每一批翻完就立刻 save 一次，中途崩潰最多只丟最後一批，
        # 已存進 JSON 的部分下次載入即會命中快取、可從中斷處續跑。
        # 同時寫回全域共用字典（若有設定），讓這批新翻譯之後在其他遊戲也能直接命中。
        if missing:
            done = 0
            for i in range(0, len(missing), BATCH):
                batch = missing[i:i + BATCH]
                translated = self.translator.translate(
                    batch, self.target_lang, self.source_lang)
                for src, dst in zip(batch, translated):
                    # 只有「開了 postprocess 且 store_converted=True」時，才把
                    # 轉換後（例如已轉繁）的內容寫進 cache/global_cache；
                    # 否則維持原樣（dst，通常是簡體）寫入，行為與現況一致。
                    to_store = (
                        self.postprocess(dst)
                        if (self.store_converted and self.postprocess) else dst)
                    self.cache.put(src, to_store)
                    if self.global_cache is not None:
                        self.global_cache.put(src, to_store)
                self.cache.save()
                if self.global_cache is not None:
                    self.global_cache.save()
                # 每翻完一批就回報一次句級進度（done 為累計已翻句數）。
                done += len(batch)
                if progress_cb is not None:
                    progress_cb(done, total_missing)

        # 回傳與輸入等長且順序一致的譯文（分層查詢：私有字典優先，其次全域字典）
        results = [self._lookup(t) for t in texts]

        # 若有設定後處理，對「每一個輸出字串」套用（不論來自快取命中或引擎新翻），
        # 維持與輸入等長、順序一致
        if self.postprocess is not None:
            results = [self.postprocess(r) for r in results]

        return results
