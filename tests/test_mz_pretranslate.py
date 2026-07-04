import base64
import json

import pytest

from core.cache import DictCache
from core.pipeline import Pipeline
from adapters.mz.pretranslate import pretranslate_encrypted_mz
from tests.test_mz_decrypt import _encrypt  # 復用 round-trip 加密輔助


class _EchoTranslator:
    """把每句翻成「譯:<原文>」，方便驗證。"""
    def translate(self, texts, target_lang, source_lang=None):
        return ["譯:" + t for t in texts]


def _write_encrypted(data_dir, name, obj, key=226):
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {"uid": "u", "bid": "1.8.1", "data": _encrypt(obj, name, key)}
    (data_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def test_pretranslate_fills_cache_from_encrypted_maps(tmp_path):
    web = tmp_path
    data = web / "data"
    _write_encrypted(data, "Map001.json", {"events": [None, {"pages": [{"list": [
        {"code": 401, "parameters": ["暗闇の中。"]},
    ]}]}]})
    _write_encrypted(data, "Actors.json", [None, {"name": "ゼシカ"}])

    cache = DictCache(str(tmp_path / "translator_dict.json"))
    pipe = Pipeline(cache, _EchoTranslator(), target_lang="ZH", source_lang="JA")
    result = pretranslate_encrypted_mz(str(web), pipe)

    assert result["暗闇の中。"] == "譯:暗闇の中。"
    assert result["ゼシカ"] == "譯:ゼシカ"


def test_pretranslate_raises_when_key_not_found(tmp_path):
    data = tmp_path / "data"
    data.mkdir(parents=True)
    (data / "Map001.json").write_text(
        json.dumps({"uid": "u", "bid": "1.8.1",
                    "data": base64.b64encode(b"\x00\x01\x02\x03" * 8).decode()}),
        encoding="utf-8")
    cache = DictCache(str(tmp_path / "d.json"))
    pipe = Pipeline(cache, _EchoTranslator(), target_lang="ZH", source_lang="JA")
    with pytest.raises(RuntimeError):
        pretranslate_encrypted_mz(str(tmp_path), pipe)
