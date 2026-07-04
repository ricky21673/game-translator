import glob
import json
import os

from core import mz_decrypt, mz_extract


def pretranslate_encrypted_mz(web_dir: str, pipeline, progress_cb=None) -> dict:
    """解密 web_dir/data/*.json、抽字、以 pipeline 批次預翻填滿 cache，回傳完整字典。

    - 不修改任何 data 檔（只讀）。
    - 找不到可用金鑰時 raise RuntimeError。
    """
    paths = sorted(glob.glob(os.path.join(web_dir, "data", "*.json")))

    # 1) 用第一個加密檔偵測 _K（全庫共用）
    key = None
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if mz_decrypt.is_encrypted_mz(obj):
            key = mz_decrypt.detect_key(obj["data"], os.path.basename(path))
            if key is not None:
                break
    if key is None:
        raise RuntimeError("無法偵測加密金鑰（_K）：可能非 bid_1.8.1 加密或資料異常")

    # 2) 逐檔解密 + 抽字（去重、保留首次出現順序）
    texts, seen = [], set()
    for path in paths:
        name = os.path.basename(path)
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not mz_decrypt.is_encrypted_mz(obj):
            continue
        try:
            data_obj = mz_decrypt.decrypt(obj["data"], name, key)
        except (ValueError, UnicodeDecodeError):
            # 單檔解密失敗不整批中斷，跳過續跑
            continue
        for s in mz_extract.extract_strings(name, data_obj):
            if s not in seen:
                seen.add(s)
                texts.append(s)

    # 3) 併入遊戲現成 MTool 字典當底（存在才做；已在 cache 者不覆蓋，避免重翻）
    mtool = os.path.join(web_dir, "翻译文件.json")
    if os.path.isfile(mtool):
        try:
            with open(mtool, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if (isinstance(k, str) and isinstance(v, str)
                            and pipeline.cache.get(k) is None):
                        pipeline.cache.put(k, v)
        except (json.JSONDecodeError, OSError, AttributeError):
            pass  # 現成字典損毀/格式非 dict 就略過，不影響主流程

    # 4) 批次預翻（Pipeline 內部邊翻邊存、可續跑），回傳完整字典
    pipeline.translate(texts, progress_cb=progress_cb)
    return pipeline.cache.as_dict()
