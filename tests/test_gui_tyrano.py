# 測試 GUI 的 TyranoScript 流程：on_start 分流到背景執行緒批次預翻部署、
# on_restore 呼叫 restore_tyrano。需要建立真的 QWidget 與跑 QThread，
# 故用 offscreen 平台以支援無頭環境（CI/終端機）執行。
import json
import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

import gui.app as app_module
from core.detector import Detection

# MainWindow 是 QWidget，建構前必須先有 QApplication 實例存在，否則會直接崩潰。
_qapp = QApplication.instance() or QApplication([])


def _pack_asar(files: dict[str, bytes]) -> bytes:
    # 與 tests/test_tyrano_deploy.py 相同的最小 asar 打包工具
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


def _mk_tyrano_game(tmp_path):
    # 建立最小可用的 Tyrano（Electron 打包）遊戲資料夾，含一個帶日文段的 .ks
    game_dir = tmp_path / "game"
    resources = game_dir / "resources"
    resources.mkdir(parents=True)
    ks = "こんにちは、世界。[p]\n"
    files = {"data/scenario/first.ks": ks.encode("utf-8")}
    (resources / "app.asar").write_bytes(_pack_asar(files))
    return game_dir


def _run_event_loop_until(predicate, timeout_ms=5000):
    # 在測試中跑 Qt 事件迴圈，直到 predicate() 為真或逾時，用於等待背景 QThread 完成。
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError("等待背景執行緒逾時")
        QCoreApplication.processEvents()
        time.sleep(0.01)


def test_tyrano_on_start_runs_deploy_in_background_and_launches(tmp_path, monkeypatch):
    # tyrano 流程：on_start 應在背景執行緒跑 deploy_tyrano，完成後呼叫 launch_game，
    # 不應建立 TranslationServer（tyrano 執行時不需要 server）。
    game_dir = _mk_tyrano_game(tmp_path)

    launched = {}

    def fake_launch(exe_path):
        launched["exe_path"] = exe_path
        return None

    # 用 NullTranslator 取代 LocalTranslator，避免測試依賴真的 Ollama 服務；
    # 只驗證 GUI 執行緒/流程串接，不驗證翻譯品質（翻譯邏輯已在 test_tyrano_deploy.py 驗證）。
    monkeypatch.setattr(app_module, "LocalTranslator",
                        lambda model: app_module.NullTranslator())
    monkeypatch.setattr(app_module, "launch_game", fake_launch)
    # 全域共用字典路徑導向 tmp_path，避免測試碰到使用者真實 home 目錄
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("tyrano", game_dir=str(game_dir))
    win.dict_path = None
    win.key_edit.setText("")
    win.engine_box.setCurrentText("本地 Ollama")  # 不需 key/dict 即可啟動的 local 模式

    win.on_start()

    # 部署期間應暫時鎖住開始鈕
    assert win.start_btn.isEnabled() is False

    _run_event_loop_until(lambda: win._tyrano_thread is None)

    assert launched["exe_path"] == win.exe_path
    assert win.server is None  # tyrano 流程不應起 TranslationServer
    assert "已完成翻譯並啟動（Tyrano）" in win.info.text()

    resources = os.path.join(str(game_dir), "resources")
    assert os.path.isfile(os.path.join(resources, "app.asar.trbak"))
    assert os.path.isdir(os.path.join(resources, "app"))
    # 開始鈕完成後應恢復可用
    assert win.start_btn.isEnabled() is True


def test_tyrano_on_start_reports_error_when_deploy_fails(tmp_path, monkeypatch):
    # deploy_tyrano 拋例外時，應顯示錯誤訊息、不呼叫 launch_game，且鈕要恢復可用
    game_dir = tmp_path / "game"
    game_dir.mkdir()  # 沒有 resources/app.asar，deploy_tyrano 應失敗

    launched = {"called": False}

    def fake_launch(exe_path):
        launched["called"] = True

    monkeypatch.setattr(app_module, "launch_game", fake_launch)

    monkeypatch.setattr(app_module, "LocalTranslator",
                        lambda model: app_module.NullTranslator())
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("tyrano", game_dir=str(game_dir))
    win.dict_path = None
    win.key_edit.setText("")
    win.engine_box.setCurrentText("本地 Ollama")

    win.on_start()
    _run_event_loop_until(lambda: win._tyrano_thread is None)

    assert launched["called"] is False
    assert "部署失敗" in win.info.text()
    assert win.start_btn.isEnabled() is True


def test_tyrano_pipeline_gets_postprocess_when_traditional_checked(tmp_path, monkeypatch):
    # tyrano 走 translate_tree（用 Pipeline），勾選繁體時 Pipeline 應帶 postprocess，
    # 讓每句譯文自動被簡轉繁（不需另外處理，交由 Pipeline.translate 內部套用）
    game_dir = _mk_tyrano_game(tmp_path)

    captured = {}

    class SpyPipeline(app_module.Pipeline):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured["postprocess"] = self.postprocess

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "Pipeline", SpyPipeline)
    monkeypatch.setattr(app_module, "LocalTranslator",
                        lambda model: app_module.NullTranslator())
    monkeypatch.setattr(app_module, "launch_game", fake_launch)
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("tyrano", game_dir=str(game_dir))
    win.dict_path = None
    win.key_edit.setText("")
    win.engine_box.setCurrentText("本地 Ollama")
    win.traditional_checkbox.setChecked(True)

    win.on_start()
    _run_event_loop_until(lambda: win._tyrano_thread is None)

    assert captured["postprocess"] is not None
    assert captured["postprocess"]("软件") == "軟體"


def test_tyrano_pipeline_no_postprocess_when_traditional_unchecked(tmp_path, monkeypatch):
    # 未勾選繁體時，Pipeline.postprocess 應維持 None（現況不變）
    game_dir = _mk_tyrano_game(tmp_path)

    captured = {}

    class SpyPipeline(app_module.Pipeline):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            captured["postprocess"] = self.postprocess

    def fake_launch(exe_path):
        return None

    monkeypatch.setattr(app_module, "Pipeline", SpyPipeline)
    monkeypatch.setattr(app_module, "LocalTranslator",
                        lambda model: app_module.NullTranslator())
    monkeypatch.setattr(app_module, "launch_game", fake_launch)
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("tyrano", game_dir=str(game_dir))
    win.dict_path = None
    win.key_edit.setText("")
    win.engine_box.setCurrentText("本地 Ollama")
    win.traditional_checkbox.setChecked(False)

    win.on_start()
    _run_event_loop_until(lambda: win._tyrano_thread is None)

    assert captured["postprocess"] is None


def test_tyrano_segment_progress_reaches_monitor(tmp_path, monkeypatch):
    # 句級進度接線：Tyrano 流程跑完後，monitor 應收過至少一次 set_progress，
    # 且最後一次的 done == total（翻譯全部完成）。用 SpyTranslator 讓段落算未命中、
    # 會實際「送引擎」翻，才會有非零 total。
    game_dir = _mk_tyrano_game(tmp_path)

    class SpyTranslator(app_module.NullTranslator):
        def translate(self, texts, target_lang, source_lang=None):
            return [t + "訳" for t in texts]

    monkeypatch.setattr(app_module, "LocalTranslator",
                        lambda model: SpyTranslator())
    monkeypatch.setattr(app_module, "launch_game", lambda exe_path: None)
    monkeypatch.setattr(app_module, "global_dict_path",
                        lambda: str(tmp_path / "global_dict.json"))

    win = app_module.MainWindow()
    win.exe_path = str(game_dir / "Game.exe")
    win.detection = Detection("tyrano", game_dir=str(game_dir))
    win.dict_path = None
    win.key_edit.setText("")
    win.engine_box.setCurrentText("本地 Ollama")

    # 攔截 monitor.set_progress 記錄所有進度事件（set_progress 在主執行緒被呼叫）
    events = []
    orig_set = win.monitor.set_progress
    def spy_set(done, total):
        events.append((done, total))
        return orig_set(done, total)
    win.monitor.set_progress = spy_set
    # 重新接線讓 spy 生效（reset 在 on_start 內做，connect 也在 on_start 內做，
    # 而 connect 綁的是 self.monitor.set_progress 這個 bound method 的當下參照，
    # 故必須在 on_start 之前替換）。
    win.on_start()
    _run_event_loop_until(lambda: win._tyrano_thread is None)

    assert len(events) >= 1
    # 這個最小遊戲只有一句日文段，未命中送引擎翻，total 應 >= 1
    last_done, last_total = events[-1]
    assert last_total >= 1
    assert last_done == last_total


def test_tyrano_on_restore_calls_restore_tyrano(tmp_path, monkeypatch):
    # tyrano 的還原應呼叫 restore_tyrano(game_dir)，而不是 restore_mv_adapter
    game_dir = _mk_tyrano_game(tmp_path)

    called = {}

    def fake_restore_tyrano(gd):
        called["game_dir"] = gd

    def fake_restore_mv(www_dir):
        called["mv_called"] = True

    monkeypatch.setattr(app_module, "restore_tyrano", fake_restore_tyrano)
    monkeypatch.setattr(app_module, "restore_mv_adapter", fake_restore_mv)

    win = app_module.MainWindow()
    win.detection = Detection("tyrano", game_dir=str(game_dir))

    win.on_restore()

    assert called.get("game_dir") == str(game_dir)
    assert "mv_called" not in called
    assert "已還原遊戲原始檔" in win.info.text()
