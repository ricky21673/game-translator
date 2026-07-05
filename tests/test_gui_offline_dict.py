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
    # 全域共用字典路徑導向 tmp_path，避免測試碰到使用者真實 home 目錄
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = str(dict_path)
    win.key_edit.setText("")  # 沒填 key → 離線模式

    win.on_start()

    assert captured["offline_dict"] == {"はい": "是", "いいえ": "否"}
    if win.server:
        win.server.stop()


def test_traditional_checkbox_default_unchecked():
    # 依使用者要求：「繁體中文（台灣用語）」勾選框改為預設關閉、且不顯示於 UI
    # （物件保留供內部流程讀取為 False）
    win = app_module.MainWindow()
    assert win.traditional_checkbox.isChecked() is False


def test_global_dict_checkbox_default_checked():
    # 「使用全域共用字典（跨遊戲加速）」勾選框預設應為勾選狀態
    win = app_module.MainWindow()
    assert win.global_dict_checkbox.isChecked() is True


def test_store_converted_checkbox_default_unchecked():
    # 「翻譯 JSON 存繁體」勾選框預設應為未勾選（預設存簡體，較通用）
    win = app_module.MainWindow()
    assert win.store_converted_checkbox.isChecked() is False


def test_new_persistent_labels_default_text():
    # item 1/2：已選遊戲與已選字典的持久顯示標籤，預設文字
    win = app_module.MainWindow()
    assert win.game_label.text() == "尚未選擇遊戲"
    assert win.dict_label.text() == "未選擇字典"


def test_traditional_and_store_converted_hidden_from_ui():
    # item 3：繁體/存繁體兩選項不加入版面（未 addWidget → parent 為 None），
    # 但物件保留、預設 False；全域字典/自動啟動仍在版面上（parent 非 None）
    win = app_module.MainWindow()
    assert win.traditional_checkbox.parent() is None
    assert win.store_converted_checkbox.parent() is None
    assert win.global_dict_checkbox.parent() is not None
    assert win.auto_launch_checkbox.parent() is not None


def test_window_title_shows_version():
    # 視窗標題應含版本號（Game Translator vX.Y）
    from version import __version__
    win = app_module.MainWindow()
    assert win.windowTitle() == f"Game Translator v{__version__}"


def test_restore_last_session_restores_game_and_dict(tmp_path):
    # 啟動還原：上次的遊戲與字典路徑仍存在 → 重開自動還原（含顯示與按鈕）
    from PySide6.QtCore import QSettings
    game_dir, www = _mk_mv_game(tmp_path)
    exe = game_dir / "Game.exe"
    exe.write_text("", encoding="utf-8")
    dict_path = tmp_path / "seed.json"
    dict_path.write_text("{}", encoding="utf-8")

    win = app_module.MainWindow()
    win.settings = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    win.settings.setValue("paths/last_exe", str(exe))
    win.settings.setValue("paths/last_dict", str(dict_path))
    win.restore_last_session()

    assert win.detection is not None and win.detection.engine == "mv"
    assert "遊戲：" in win.game_label.text()
    assert win.dict_path == str(dict_path)
    assert win.dict_label.text() == str(dict_path)
    assert win.start_btn.isEnabled() is True


def test_restore_last_session_skips_missing_paths(tmp_path):
    # 路徑已不存在（如遊戲暫存夾被清）→ 不還原、不報錯，維持初始狀態
    from PySide6.QtCore import QSettings
    win = app_module.MainWindow()
    win.settings = QSettings(str(tmp_path / "s2.ini"), QSettings.IniFormat)
    win.settings.setValue("paths/last_exe", str(tmp_path / "gone" / "Game.exe"))
    win.settings.setValue("paths/last_dict", str(tmp_path / "gone.json"))
    win.restore_last_session()

    assert win.detection is None
    assert win.game_label.text() == "尚未選擇遊戲"
    assert win.dict_label.text() == "未選擇字典"


def test_store_converted_checkbox_checked_passes_true_to_pipeline(tmp_path, monkeypatch):
    # 勾選「翻譯 JSON 存繁體」時，_build_pipeline 應把 store_converted=True 傳給 Pipeline
    game_dir, www = _mk_mv_game(tmp_path)

    monkeypatch.setattr(app_module, "launch_game", lambda exe_path: None)
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None
    win.key_edit.setText("")
    win.store_converted_checkbox.setChecked(True)

    pipe = win._build_pipeline(win.detection, "offline", "")

    assert pipe.store_converted is True


def test_store_converted_checkbox_unchecked_passes_false_to_pipeline(tmp_path, monkeypatch):
    # 未勾選「翻譯 JSON 存繁體」時，_build_pipeline 應把 store_converted=False 傳給
    # Pipeline（維持預設「存簡體」行為）
    game_dir, www = _mk_mv_game(tmp_path)

    monkeypatch.setattr(app_module, "launch_game", lambda exe_path: None)
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None
    win.key_edit.setText("")
    win.store_converted_checkbox.setChecked(False)

    pipe = win._build_pipeline(win.detection, "offline", "")

    assert pipe.store_converted is False


def test_global_dict_checked_passes_global_cache_to_pipeline(tmp_path, monkeypatch):
    # 勾選全域共用字典時，_build_pipeline 應把 DictCache(global_dict_path()) 傳給 Pipeline
    game_dir, www = _mk_mv_game(tmp_path)

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "launch_game", fake_launch)
    global_path = str(tmp_path / "global_dict.json")
    monkeypatch.setattr(app_module, "global_dict_path", lambda: global_path)

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None
    win.key_edit.setText("")  # 離線模式（offline），不需 key
    win.global_dict_checkbox.setChecked(True)

    pipe = win._build_pipeline(win.detection, "offline", "")

    assert pipe.global_cache is not None
    assert pipe.global_cache.path == global_path


def test_global_dict_unchecked_passes_none_to_pipeline(tmp_path, monkeypatch):
    # 未勾選全域共用字典時，_build_pipeline 應傳 global_cache=None（維持既有行為）
    game_dir, www = _mk_mv_game(tmp_path)

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "launch_game", fake_launch)
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None
    win.key_edit.setText("")
    win.global_dict_checkbox.setChecked(False)

    pipe = win._build_pipeline(win.detection, "offline", "")

    assert pipe.global_cache is None


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
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

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
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

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
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None
    win.engine_box.setCurrentText("DeepL")  # 引擎下拉需明確切到 DeepL 才會走 deepl 分支
    win.key_edit.setText("sk-dummy-key-not-real")

    win.on_start()

    assert captured["offline_dict"] is None
    if win.server:
        win.server.stop()


def test_launch_only_launches_selected_game(monkeypatch):
    # 有選遊戲 → on_launch_only 呼叫 launch_game(exe_path)
    called = {}
    monkeypatch.setattr(app_module, "launch_game", lambda p: called.setdefault("path", p))
    win = app_module.MainWindow()
    win.exe_path = r"C:\game\Game.exe"
    win.on_launch_only()
    assert called.get("path") == r"C:\game\Game.exe"
    assert "已直接啟動" in win.info.text()


def test_launch_only_no_game_does_nothing(monkeypatch):
    # 沒選遊戲 → 不呼叫 launch_game、不崩、提示先選遊戲
    called = {}
    monkeypatch.setattr(app_module, "launch_game", lambda p: called.setdefault("path", p))
    win = app_module.MainWindow()
    win.exe_path = None
    win.on_launch_only()
    assert "path" not in called
    assert "請先選擇遊戲" in win.info.text()


def test_launch_only_handles_exception(monkeypatch):
    # launch_game 丟例外 → 狀態列顯示失敗、不逸出
    def boom(p):
        raise RuntimeError("x")
    monkeypatch.setattr(app_module, "launch_game", boom)
    win = app_module.MainWindow()
    win.exe_path = r"C:\game\Game.exe"
    win.on_launch_only()
    assert "啟動失敗" in win.info.text()


def test_launch_btn_disabled_initially_enabled_after_apply(tmp_path):
    # 初始 disabled；套用遊戲後 enabled
    game_dir, www = _mk_mv_game(tmp_path)
    exe = game_dir / "Game.exe"
    exe.write_text("", encoding="utf-8")
    win = app_module.MainWindow()
    assert win.launch_btn.isEnabled() is False
    win._apply_game(str(exe))
    assert win.launch_btn.isEnabled() is True
