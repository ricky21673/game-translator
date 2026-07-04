# 查詢本機 Ollama 服務已安裝的模型清單，供 GUI「本地 Ollama」引擎的模型下拉選單使用。
#
# 依 Ollama 官方 API 文檔：GET /api/tags 會列出本機已下載的模型，
# 回應格式為 {"models": [{"name": "qwen2.5:14b", ...}, ...]}（每個模型物件至少含 name 欄位）。
# 這裡只取 name，組成給 GUI 下拉選單用的字串清單。
import requests

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11434
TIMEOUT = 5  # 只是查清單，逾時不必等太久，避免 GUI 卡住


def list_ollama_models(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                        session=None) -> list[str]:
    """
    查詢本機 Ollama 已安裝的模型名稱清單。

    - 呼叫 GET http://{host}:{port}/api/tags（Ollama 官方文檔端點）。
    - 成功（200）→ 回傳 [m["name"] for m in resp.json()["models"]]。
    - 任何失敗（連不上 Ollama、逾時、非 200、回應格式不符預期等）一律回傳
      空清單 []，不拋出例外——呼叫端（GUI）不需要 try/except 包這個函式，
      抓不到就顯示空清單，讓使用者退回手動輸入模型名稱。
    """
    sess = session or requests.Session()
    try:
        resp = sess.get(f"http://{host}:{port}/api/tags", timeout=TIMEOUT)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        # 涵蓋 requests.RequestException（連不上/逾時）、JSON 解析失敗、
        # 回應結構不符（缺 name 鍵等）——任何情況都靜默降級為空清單。
        return []
