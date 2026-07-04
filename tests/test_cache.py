import json
from core.cache import DictCache


def test_put_get_roundtrip(tmp_path):
    # 測試：快取初始為空，put 後 get 能取回
    p = tmp_path / "dict.json"
    c = DictCache(str(p))
    assert c.get("はい") is None
    c.put("はい", "是")
    assert c.get("はい") == "是"


def test_save_and_reload(tmp_path):
    # 測試：save() 寫入檔案，新建快取能讀出之前的資料
    p = tmp_path / "dict.json"
    c = DictCache(str(p))
    c.put("いいえ", "否")
    c.save()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["いいえ"] == "否"
    c2 = DictCache(str(p))
    assert c2.get("いいえ") == "否"


def test_loads_existing_mtool_dict(tmp_path):
    # 測試：快取初始化時若檔案存在，自動載入格式為 {原文:譯文} 的 JSON
    p = tmp_path / "dict.json"
    p.write_text(json.dumps({"戻る": "返回"}, ensure_ascii=False), encoding="utf-8")
    assert DictCache(str(p)).get("戻る") == "返回"


def test_init_with_empty_file_falls_back_to_empty_dict(tmp_path):
    # 測試：指向一個 0 byte 的空檔，建構不應崩潰，退回空字典
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    c = DictCache(str(p))
    assert c.get("任何key") is None


def test_init_with_corrupted_json_falls_back_to_empty_dict(tmp_path):
    # 測試：指向內容為壞 JSON 的檔案，建構不應崩潰，退回空字典
    p = tmp_path / "broken.json"
    p.write_text("{ broken", encoding="utf-8")
    c = DictCache(str(p))
    assert c.get("任何key") is None
