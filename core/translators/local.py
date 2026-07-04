import requests
from .base import Translator
from .deepl import TranslationError

# Ollama 官方文檔端點：POST http://<host>:<port>/api/chat
# 預設 host=127.0.0.1、port=11434
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11434
TIMEOUT = 120  # 本地 LLM 可能較慢，timeout 拉長
MAX_RETRIES = 2  # 單句失敗後最多重試次數（不含第一次嘗試）

SYSTEM_PROMPT = (
    "你是專業的日文遊戲翻譯，把使用者輸入翻成簡體中文；"
    "只輸出譯文本身，不要任何解釋、註解、引號；"
    "保留原文中的控制碼與符號（如 \\C[1]、\\n、%1）。"
)

# Sakura 專用提示詞（依 SakuraLLM 官方格式，非通用提示）。
# Sakura（如 sakura、Sakura-GalTransl 系列模型）是專為日文輕小說／galgame
# 翻譯微調的模型，只認得它固定的 system + user 格式，用通用提示會發揮不出實力。
# system 提示固定不變、不含控制碼保留等額外指示。
SAKURA_SYSTEM_PROMPT = (
    "你是一个轻小说翻译模型，可以流畅通顺地以日本轻小说的风格将日文翻译成简体"
    "中文，并联系上下文正确使用人称代词，不擅自添加原文中没有的代词。"
)
# user 內容固定前綴 + 日文原文，兩者直接相接，中間不加空白。
SAKURA_USER_PREFIX = "将下面的日文文本翻译成中文："


class LocalTranslator(Translator):
    """透過本機 Ollama 服務呼叫本地 LLM 做日文→中文翻譯的引擎。

    離線、無審查、可 GPU 加速：不需要任何線上 API key，只要本機
    Ollama 服務已啟動並安裝好對應模型即可使用。
    """

    def __init__(self, model: str, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, session=None):
        self.model = model
        self.url = f"http://{host}:{port}/api/chat"
        self.session = session or requests.Session()
        # 模型名含 "sakura"（大小寫不拘）即視為 Sakura 系列模型，
        # 送 /api/chat 時改用 Sakura 專用提示詞格式。
        self._sakura = "sakura" in model.lower()

    def translate(self, texts: list[str], target_lang: str = "ZH",
                  source_lang: str | None = None) -> list[str]:
        # 逐句呼叫 /api/chat，最可靠；批次優化留待日後
        #
        # 容錯設計：長時間全翻（上萬句、跑好幾小時）任一句因逾時/忙碌/斷線
        # 失敗都不該讓整批中斷。因此每句都有獨立的重試與降級機制：
        # 先重試最多 MAX_RETRIES 次，仍失敗就保留原文、印出警告後繼續下一句，
        # 絕不向外拋出例外（fail-soft，不 fail-fast）。
        out: list[str] = []
        for text in texts:
            out.append(self._call_with_retry(text))
        return out

    def _call_with_retry(self, text: str) -> str:
        # 對單一句子做重試：第一次嘗試 + 最多 MAX_RETRIES 次重試
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._call(text)
            except TranslationError as e:
                last_err = e

        # 重試用盡仍失敗：保留原文，繼續下一句，不中斷整批
        preview = text[:20]
        print(f"[警告] 翻譯失敗，已保留原文繼續下一句：{preview}（原因：{last_err}）")
        return text

    def _call(self, text: str) -> str:
        if self._sakura:
            system_prompt = SAKURA_SYSTEM_PROMPT
            user_content = SAKURA_USER_PREFIX + text
        else:
            system_prompt = SYSTEM_PROMPT
            user_content = text

        body = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }

        try:
            resp = self.session.post(self.url, json=body, timeout=TIMEOUT)
        except requests.RequestException as e:
            raise TranslationError("network", str(e))

        code = resp.status_code
        if code == 200:
            return resp.json()["message"]["content"].strip()
        if code == 404:
            raise TranslationError("model", "模型未安裝，請先 ollama pull")
        raise TranslationError("server", f"Ollama 回應狀態碼 {code}")
