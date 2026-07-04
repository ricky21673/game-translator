# 測試 core/paths.py：全域共用字典路徑的解析與父目錄建立行為。
import os

from core.paths import global_dict_path


def test_path_ends_with_global_dict_json(monkeypatch, tmp_path):
    # 用 monkeypatch 假造家目錄，驗證回傳路徑落在 <home>/.game_translator/global_dict.json
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows：os.path.expanduser 看這個
    monkeypatch.setenv("HOME", str(tmp_path))  # 非 Windows 平台看這個，雙設不衝突
    path = global_dict_path()
    assert path == os.path.join(str(tmp_path), ".game_translator", "global_dict.json")


def test_parent_directory_is_created(monkeypatch, tmp_path):
    # 呼叫前父目錄不存在，呼叫後應自動建立（os.makedirs exist_ok=True）
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    parent = tmp_path / ".game_translator"
    assert not parent.exists()

    path = global_dict_path()

    assert os.path.isdir(os.path.dirname(path))

    # 再呼叫一次確認 exist_ok 不會因目錄已存在而丟例外
    global_dict_path()
