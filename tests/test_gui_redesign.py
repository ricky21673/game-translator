# 測試 GUI 重排後的新行為：
# - 翻譯引擎下拉驅動的條件顯示（visible_fields 接線到實際 widget.isVisible()）
# - 「翻完後自動啟動遊戲」勾選框（auto_launch）對 mv/mz 與 tyrano 兩種流程的影響
# - model_box 下拉（自動抓 Ollama 已裝模型 + 手動重新整理）
# 需要建立真的 QWidget，故用 offscreen 平台以支援無頭環境（CI/終端機）執行。
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
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


def _run_event_loop_until(predicate, timeout_ms=5000):
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("等待背景執行緒逾時")
        QCoreApplication.processEvents()
        time.sleep(0.01)


# -- 條件顯示：引擎下拉切換時，widget.isVisible() 應與 visible_fields 一致 -----------


def test_default_engine_is_offline_and_shows_only_dict(monkeypatch):
    # 避免建構時（預設可能非 local）意外打真實網路；這裡預設引擎是「離線字典」，
    # 不會觸發 list_ollama_models，但仍保險 monkeypatch 掉。
    # 注意：頂層視窗在測試中未呼叫 show()，Qt 的 isVisible() 在此情況下對任何
    # 子 widget 一律回傳 False（考慮祖先鏈），故改用 isHidden() 驗證「我們有沒有
    # 主動呼叫 setVisible(False)」，這才是 visible_fields 接線邏輯本身要驗證的東西。
    monkeypatch.setattr(app_module, "list_ollama_models", lambda *a, **kw: [])
    win = app_module.MainWindow()
    assert win.engine_box.currentText() == "離線字典"
    assert win.dict_btn.isHidden() is False
    assert win.key_edit.isHidden() is True
    assert win.model_box.isHidden() is True
    assert win.model_refresh_btn.isHidden() is True


def test_switch_to_deepl_shows_dict_and_key_hides_model(monkeypatch):
    monkeypatch.setattr(app_module, "list_ollama_models", lambda *a, **kw: [])
    win = app_module.MainWindow()
    win.engine_box.setCurrentText("DeepL")
    assert win.dict_btn.isHidden() is False
    assert win.key_edit.isHidden() is False
    assert win.model_box.isHidden() is True
    assert win.model_refresh_btn.isHidden() is True


def test_switch_to_local_shows_dict_and_model_hides_key(monkeypatch):
    monkeypatch.setattr(app_module, "list_ollama_models", lambda *a, **kw: [])
    win = app_module.MainWindow()
    win.engine_box.setCurrentText("本地 Ollama")
    assert win.dict_btn.isHidden() is False
    assert win.model_box.isHidden() is False
    assert win.model_refresh_btn.isHidden() is False
    assert win.key_edit.isHidden() is True


def test_switching_to_local_auto_refreshes_model_list(monkeypatch):
    # 切到「本地 Ollama」應自動呼叫 list_ollama_models 填入下拉（需求 B）
    calls = {"n": 0}

    def fake_list(*a, **kw):
        calls["n"] += 1
        return ["qwen2.5:14b", "sakura-galtransl:latest"]

    monkeypatch.setattr(app_module, "list_ollama_models", fake_list)
    win = app_module.MainWindow()
    win.engine_box.setCurrentText("本地 Ollama")

    assert calls["n"] >= 1
    texts = [win.model_box.itemText(i) for i in range(win.model_box.count())]
    assert "qwen2.5:14b" in texts
    assert "sakura-galtransl:latest" in texts


def test_refresh_button_repopulates_model_box_and_reports_count(monkeypatch):
    monkeypatch.setattr(app_module, "list_ollama_models", lambda *a, **kw: [])
    win = app_module.MainWindow()
    win.engine_box.setCurrentText("本地 Ollama")

    monkeypatch.setattr(app_module, "list_ollama_models",
                        lambda *a, **kw: ["custom-model:latest"])
    win.on_refresh_models()

    texts = [win.model_box.itemText(i) for i in range(win.model_box.count())]
    assert "custom-model:latest" in texts
    assert "已偵測到 1 個本機 Ollama 模型" in win.info.text()


def test_refresh_button_empty_list_keeps_existing_and_reports_status(monkeypatch):
    monkeypatch.setattr(app_module, "list_ollama_models", lambda *a, **kw: [])
    win = app_module.MainWindow()
    win.engine_box.setCurrentText("本地 Ollama")
    before = [win.model_box.itemText(i) for i in range(win.model_box.count())]

    win.on_refresh_models()

    after = [win.model_box.itemText(i) for i in range(win.model_box.count())]
    assert after == before  # 抓不到清單時維持既有內容，不清空
    assert "未偵測到本機 Ollama 模型" in win.info.text()


# -- offline 引擎必選字典 -----------------------------------------------------


def test_offline_engine_without_dict_shows_hint_and_does_not_start(tmp_path, monkeypatch):
    game_dir, www = _mk_mv_game(tmp_path)
    monkeypatch.setattr(app_module, "list_ollama_models", lambda *a, **kw: [])

    called = {"deploy": False}
    monkeypatch.setattr(app_module, "deploy_mv_adapter",
                        lambda *a, **kw: called.__setitem__("deploy", True) or "dummy")
    monkeypatch.setattr(app_module, "launch_game", lambda exe_path: None)

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = None  # 離線字典模式但沒選字典 → 必選未滿足

    win.on_start()

    assert called["deploy"] is False
    assert "請選擇字典 JSON" in win.info.text()


# -- auto_launch：RPG Maker（mv/mz）流程 --------------------------------------


def test_auto_launch_checked_by_default():
    win = app_module.MainWindow()
    assert win.auto_launch_checkbox.isChecked() is True


def test_rpgmaker_auto_launch_checked_calls_launch_game(tmp_path, monkeypatch):
    game_dir, www = _mk_mv_game(tmp_path)

    dict_path = tmp_path / "seed_dict.json"
    dict_path.write_text('{"はい": "是"}', encoding="utf-8")

    launched = {"called": False}
    monkeypatch.setattr(app_module, "deploy_mv_adapter", lambda *a, **kw: "dummy")
    monkeypatch.setattr(app_module, "launch_game",
                        lambda exe_path: launched.__setitem__("called", True))
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = str(dict_path)
    win.auto_launch_checkbox.setChecked(True)

    win.on_start()

    assert launched["called"] is True
    assert "已啟動" in win.info.text()
    if win.server:
        win.server.stop()


def test_rpgmaker_auto_launch_unchecked_does_not_call_launch_game(tmp_path, monkeypatch):
    game_dir, www = _mk_mv_game(tmp_path)

    dict_path = tmp_path / "seed_dict.json"
    dict_path.write_text('{"はい": "是"}', encoding="utf-8")

    launched = {"called": False}
    monkeypatch.setattr(app_module, "deploy_mv_adapter", lambda *a, **kw: "dummy")
    monkeypatch.setattr(app_module, "launch_game",
                        lambda exe_path: launched.__setitem__("called", True))
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("mv", str(game_dir), str(www), str(www / "js"), str(www))
    win.dict_path = str(dict_path)
    win.auto_launch_checkbox.setChecked(False)

    win.on_start()

    assert launched["called"] is False
    assert "已部署，未啟動" in win.info.text()
    if win.server:
        win.server.stop()


# -- auto_launch：Tyrano 流程（背景 QThread） ---------------------------------


def test_tyrano_auto_launch_unchecked_does_not_call_launch_game(tmp_path, monkeypatch):
    import json
    import struct

    def _pack_asar(files: dict[str, bytes]) -> bytes:
        offset = 0
        root: dict = {"files": {}}
        contents: list[bytes] = []
        for rel_path, content in files.items():
            parts = rel_path.split("/")
            node = root
            for part in parts[:-1]:
                node = node["files"].setdefault(part, {"files": {}})
            node["files"][parts[-1]] = {"size": len(content), "offset": str(offset)}
            contents.append(content)
            offset += len(content)
        header_json = json.dumps(root).encode("utf-8")
        json_len = len(header_json)
        pad = (4 - (json_len % 4)) % 4
        padded_json = header_json + b"\x00" * pad
        payload_size = 4 + len(padded_json)
        header_size = 4 + payload_size
        outer_size = 4 + header_size
        buf = (
            struct.pack("<I", outer_size)
            + struct.pack("<I", header_size)
            + struct.pack("<I", payload_size)
            + struct.pack("<I", json_len)
            + padded_json
        )
        buf += b"".join(contents)
        return buf

    game_dir = tmp_path / "game"
    resources = game_dir / "resources"
    resources.mkdir(parents=True)
    ks = "こんにちは、世界。[p]\n"
    (resources / "app.asar").write_bytes(_pack_asar({"data/scenario/first.ks": ks.encode("utf-8")}))

    launched = {"called": False}
    monkeypatch.setattr(app_module, "LocalTranslator",
                        lambda model: app_module.NullTranslator())
    monkeypatch.setattr(app_module, "launch_game",
                        lambda exe_path: launched.__setitem__("called", True))
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("tyrano", game_dir=str(game_dir))
    win.dict_path = None
    win.engine_box.setCurrentText("本地 Ollama")
    win.auto_launch_checkbox.setChecked(False)

    win.on_start()
    _run_event_loop_until(lambda: win._tyrano_thread is None)

    assert launched["called"] is False
    assert "翻譯完成，未啟動" in win.info.text()
