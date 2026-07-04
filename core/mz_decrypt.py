import base64
import json
import os

# 各加密器 scheme 的常數。日後遇到別的 bid/加密器在此加一組即可，主流程不動。
_SCHEMES = {
    "bid_1.8.1": {"c_xor": 23, "k_xor": 186, "k_add": 33, "mod": 128},
}


def is_encrypted_mz(obj) -> bool:
    """判斷是否為加密 MZ data 結構：同時含 uid/bid，且 data 為非空字串。"""
    return (isinstance(obj, dict)
            and "uid" in obj and "bid" in obj
            and isinstance(obj.get("data"), str) and obj["data"] != "")


def _norm_name(filename: str) -> str:
    """與遊戲一致：去路徑、去 .json、轉小寫（金鑰依此檔名派生）。"""
    base = os.path.basename(filename)
    if base.lower().endswith(".json"):
        base = base[:-5]
    return base.lower()


def _filename_hash(name: str) -> int:
    """JS: t = ((t<<5) - t + charCode) | 0；此處以 32 位遮罩對齊。"""
    t = 0
    for ch in name:
        t = ((t << 5) - t + ord(ch)) & 0xFFFFFFFF
    return t


def _keystream_byte(fk: int, i: int, ls: int, s: dict) -> int:
    """單一位元組的金鑰流；ls 為回饋值（前一個已解出的明文位元組）。"""
    c = fk ^ s["c_xor"]
    p = (ls << 2) ^ (ls >> 3)
    return (((c + (i % s["mod"]) + p) ^ s["k_xor"]) + s["k_add"]) & 0xFF


def _decrypt_bytes(cipher: bytes, norm_name: str, key: int, s: dict) -> bytes:
    b = bytearray(cipher)
    fk = (key ^ (_filename_hash(norm_name) & 0xFF)) & 0xFF
    ls = fk
    for i in range(len(b) - 1, -1, -1):
        v = b[i] ^ _keystream_byte(fk, i, ls, s)
        b[i] = v
        ls = v
    return bytes(b)


def decrypt(data_b64: str, filename: str, key: int, scheme: str = "bid_1.8.1") -> dict:
    """解密單一 data 檔的 base64 內容，回傳 json.loads 後的物件。"""
    s = _SCHEMES[scheme]
    raw = _decrypt_bytes(base64.b64decode(data_b64), _norm_name(filename), key, s)
    return json.loads(raw.decode("utf-8"))


def detect_key(sample_data_b64: str, filename: str, scheme: str = "bid_1.8.1"):
    """自動爆破 _K：0–255 全試，取「解出合法 UTF-8 且 json 可 parse」者；找不到回 None。"""
    s = _SCHEMES[scheme]
    cipher = base64.b64decode(sample_data_b64)
    norm = _norm_name(filename)
    for key in range(256):
        try:
            raw = _decrypt_bytes(cipher, norm, key, s)
            json.loads(raw.decode("utf-8"))
            return key
        except (UnicodeDecodeError, ValueError):
            continue
    return None
