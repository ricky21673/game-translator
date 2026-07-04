# 測試 GUI 離線模式啟動流程：把 DictCache 整份內容當 offline_dict 傳給 deploy_mv_adapter。
# 需要建立真的 QWidget，故用 offscreen 平台以支援無頭環境（CI/終端機）執行。
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import gui.app as app_module
from core.detector import Detection

# MainWindow 是 QWidget，建構前必須先有 QApplication 實例存在，否則會直接崩潰。
_qapp = QApplication.instance() or QApplication([])


def _mk_mv_game(tmp_path):
    # 建立最小可用的 MV 遊戲資料夾（含 plugins.js、index.html、rpg_core.js 供 detect() 判型）
    game_dir = tmp_path / "game"
    www = game_dir / "www"
    js = www / "js"
    js.mkdir(parents=True)
    (js / "rpg_core.js").write_text("// stub", encoding="utf-8")
    (js / "plugins.js").write_text("var $plugins =\n[\n];\n", encoding="utf-8")
    (www / "index.html").write_text(
        "<html><body>"
        "<script type='text/javascript' src='js/plugins.js'></script>"
        "</body></html>", encoding="utf-8")
    (www / "data").mkdir()
    return game_dir, www


def test_offline_mode_passes_full_dict_to_deploy(tmp_path, monkeypatch):
    # 離線模式（選了字典 JSON、沒填 key）：deploy_mv_adapter 應收到整份字典內容
    game_dir, www = _mk_mv_game(tmp_path)

    # 準備既有字典 JSON，供使用者「選擇既有字典 JSON」
    dict_path = tmp_path / "seed_dict.json"
    dict_path.write_text(json.dumps({"はい": "是", "いいえ": "否"}, ensure_ascii=False),
                         encoding="utf-8")

    captured = {}

    def fake_deploy(www_dir, port, maps, bridge_src, offline_dict=None):
        captured["offline_dict"] = offline_dict
        return "dummy_dst"

    def fake_launch(exe_path):
        return None  # 不真的開遊戲行程

    monkeypatch.setattr(app_module, "deploy_mv_adapter", fake_deploy)
    monkeypatch.setattr(app_module, "launch_game", fake_launch)

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = str(dict_path)
    win.key_edit.setText("")  # 沒填 key → 離線模式

    win.on_start()

    assert captured["offline_dict"] == {"はい": "是", "いいえ": "否"}
    if win.server:
        win.server.stop()


def test_traditional_checkbox_default_checked():
    # 「繁體中文（台灣用語）」勾選框預設應為勾選狀態（使用者要繁體）
    win = app_module.MainWindow()
    assert win.traditional_checkbox.isChecked() is True


def test_offline_mode_with_traditional_checked_converts_dict_values(tmp_path, monkeypatch):
    # 離線整字典模式 + 勾選繁體：offline_dict 的每個「值」都要被簡轉繁，
    # 但「鍵」（原文，通常是日文）保持不變
    game_dir, www = _mk_mv_game(tmp_path)

    dict_path = tmp_path / "seed_dict.json"
    # 用簡體中文譯文模擬「現成字典/DeepL/Ollama 多半輸出簡體」的情境
    dict_path.write_text(json.dumps({"はい": "软件", "いいえ": "信息"}, ensure_ascii=False),
                         encoding="utf-8")

    captured = {}

    def fake_deploy(www_dir, port, maps, bridge_src, offline_dict=None):
        captured["offline_dict"] = offline_dict
        return "dummy_dst"

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "deploy_mv_adapter", fake_deploy)
    monkeypatch.setattr(app_module, "launch_game", fake_launch)

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = str(dict_path)
    win.key_edit.setText("")  # 沒填 key → 離線模式
    win.traditional_checkbox.setChecked(True)

    win.on_start()

    # 鍵（原文）不變，值（譯文）被轉為繁體台灣用語
    offline_dict = captured["offline_dict"]
    assert set(offline_dict.keys()) == {"はい", "いいえ"}
    assert offline_dict["はい"] == "軟體"
    assert offline_dict["いいえ"] == "資訊"
    if win.server:
        win.server.stop()


def test_offline_mode_with_traditional_unchecked_keeps_original_values(tmp_path, monkeypatch):
    # 離線整字典模式 + 未勾選繁體：offline_dict 的值應維持原文，不做任何轉換
    game_dir, www = _mk_mv_game(tmp_path)

    dict_path = tmp_path / "seed_dict.json"
    dict_path.write_text(json.dumps({"はい": "软件", "いいえ": "信息"}, ensure_ascii=False),
                         encoding="utf-8")

    captured = {}

    def fake_deploy(www_dir, port, maps, bridge_src, offline_dict=None):
        captured["offline_dict"] = offline_dict
        return "dummy_dst"

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "deploy_mv_adapter", fake_deploy)
    monkeypatch.setattr(app_module, "launch_game", fake_launch)

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = str(dict_path)
    win.key_edit.setText("")
    win.traditional_checkbox.setChecked(False)

    win.on_start()

    assert captured["offline_dict"] == {"はい": "软件", "いいえ": "信息"}
    if win.server:
        win.server.stop()


def test_deepl_mode_passes_none_to_deploy(tmp_path, monkeypatch):
    # DeepL 線上模式（填了 key）：offline_dict 必須是 None，維持既有 server 路徑不受影響
    game_dir, www = _mk_mv_game(tmp_path)

    captured = {}

    def fake_deploy(www_dir, port, maps, bridge_src, offline_dict=None):
        captured["offline_dict"] = offline_dict
        return "dummy_dst"

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "deploy_mv_adapter", fake_deploy)
    monkeypatch.setattr(app_module, "launch_game", fake_launch)

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None
    win.key_edit.setText("sk-dummy-key-not-real")

    win.on_start()

    assert captured["offline_dict"] is None
    if win.server:
        win.server.stop()
