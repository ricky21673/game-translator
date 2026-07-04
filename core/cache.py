import json
import os


class DictCache:
    """快取字典，格式為扁平 JSON {原文:譯文}"""

    def __init__(self, path: str):
        """初始化快取，若檔案存在則自動載入"""
        self.path = path
        self._data: dict[str, str] = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"[警告] 字典檔無法解析，將以空字典開始: {path} ({e})")
                self._data = {}

    def get(self, text: str) -> str | None:
        """查詢原文的譯文，不存在時回傳 None"""
        return self._data.get(text)

    def put(self, text: str, translation: str) -> None:
        """新增或更新原文及其譯文至快取"""
        self._data[text] = translation

    def save(self) -> None:
        """將快取內容寫入 JSON 檔案"""
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
