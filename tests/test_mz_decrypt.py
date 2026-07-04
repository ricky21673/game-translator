import base64
import json

from core import mz_decrypt as mz


def _encrypt(obj, filename, key, scheme="bid_1.8.1"):
    """測試專用：用與解密相同的演算法，把明文 JSON 加密成 base64（建 fixture 用）。"""
    s = mz._SCHEMES[scheme]
    plain = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    p = bytearray(plain)
    fk = (key ^ (mz._filename_hash(mz._norm_name(filename)) & 0xFF)) & 0xFF
    ct = bytearray(len(p))
    for i in range(len(p)):
        ls = fk if i == len(p) - 1 else p[i + 1]
        ct[i] = p[i] ^ mz._keystream_byte(fk, i, ls, s)
    return base64.b64encode(bytes(ct)).decode("ascii")


def test_decrypt_round_trip_recovers_japanese():
    obj = {"events": [None, {"pages": [{"list": [
        {"code": 401, "parameters": ["\\FS[28]暗闇の中その小さな穴をみる。"]},
    ]}]}]}
    data_b64 = _encrypt(obj, "Map018.json", 226)
    assert mz.decrypt(data_b64, "Map018.json", 226) == obj


def test_detect_key_finds_the_key():
    obj = {"name": "ゼシカ", "profile": "宿屋の受付"}
    data_b64 = _encrypt(obj, "Actors.json", 226)
    assert mz.detect_key(data_b64, "Actors.json") == 226


def test_detect_key_returns_none_on_garbage():
    assert mz.detect_key(base64.b64encode(b"\x00\x01\x02\x03" * 8).decode(),
                         "Map001.json") is None


def test_is_encrypted_mz():
    assert mz.is_encrypted_mz({"uid": "x", "bid": "1.8.1", "data": "abc"}) is True
    assert mz.is_encrypted_mz({"events": []}) is False
    assert mz.is_encrypted_mz({"uid": "x", "bid": "1.8.1", "data": ""}) is False


import os as _os
import pytest

_GAME = r"D:\7-Zip\tmp\ゆうべは大変おたのしみでしたね。"


@pytest.mark.skipif(not _os.path.isdir(_GAME), reason="需本機實體遊戲，非 CI")
def test_real_game_decrypts_to_japanese():
    with open(_os.path.join(_GAME, "data", "Map003.json"), encoding="utf-8") as f:
        c = json.load(f)
    key = mz.detect_key(c["data"], "Map003.json")
    assert key == 226
    obj = mz.decrypt(c["data"], "Map003.json", key)
    blob = json.dumps(obj, ensure_ascii=False)
    assert "空室" in blob  # 該圖已知日文片段
