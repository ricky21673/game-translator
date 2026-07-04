# PySide6 GUI：選遊戲 exe → 自動判型 → 顯示 → 依「是否支援」鎖/解鎖「開始」
# → 按開始執行整合流程：
#   - RPG Maker（mv/mz）：讀地圖 → 起 server → 部署 adapter → 開遊戲，翻譯在遊戲執行時
#     由 server 即時處理。
#   - TyranoScript（tyrano）：部署「就是」批次預翻（解包 app.asar → 翻完所有 .ks →
#     改名讓 Electron 吃解包後的 app/），較耗時但翻完直接啟動，執行時不需要 server。
#     因為耗時，部署階段在背景執行緒跑，避免卡住 GUI 事件迴圈；進度透過 Qt signal
#     回主執行緒更新畫面。
#
# 版面採「分區＋依引擎條件顯示」設計（見各區塊註解）：
#   ① 遊戲：選擇主程式 + 偵測狀態
#   ② 翻譯引擎：下拉選擇離線字典／DeepL／本地 Ollama，只顯示該引擎需要的欄位
#   ③ 選項：繁體中文／全域字典／存繁體／翻完後自動啟動
#   之後接「開始」「還原遊戲」兩顆按鈕，最下方沿用既有翻譯監控面板。
import glob
import json
import os
import shutil
import sys

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QVBoxLayout, QHBoxLayout, QFileDialog, QCheckBox, QGroupBox,
)

from core.detector import detect, Detection
from core.cache import DictCache
from core.ollama_util import list_ollama_models
from core.paths import global_dict_path
from core.pipeline import Pipeline
from core.postprocess import make_traditional_converter
from core.server import TranslationServer
from core.translators.deepl import DeepLTranslator
from core.translators.null import NullTranslator
from core.translators.local import LocalTranslator
from gui.monitor import TranslationMonitor
from launcher import deploy_mv_adapter, launch_game, restore_mv_adapter
from adapters.tyrano.deploy import deploy_tyrano, restore_tyrano

SUPPORTED = ("mv", "mz", "tyrano")  # 支援 MV、MZ 與 TyranoScript
DEFAULT_LOCAL_MODEL = "qwen2.5:14b"

# GUI 顯示字串 → 內部引擎值（同時也是 choose_translator_mode 用的 engine 值）。
# 用 dict 保序（Python 3.7+ 保證插入順序），engine_box 依此順序加入選項。
ENGINE_DISPLAY_TO_KEY = {
    "離線字典": "offline",
    "DeepL": "deepl",
    "本地 Ollama": "local",
}
ENGINE_KEY_TO_DISPLAY = {v: k for k, v in ENGINE_DISPLAY_TO_KEY.items()}


def resource_path(rel_path: str) -> str:
    """
    解析隨程式一起打包的資源路徑，開發與打包後皆適用：
    - PyInstaller 打包後：資源解壓到 sys._MEIPASS，以它為基準。
    - 開發模式：gui/ 的上一層即專案根目錄。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel_path)


def can_start(detection: Detection | None, engine_supported=SUPPORTED) -> bool:
    """
    狀態機核心規則：沒選到遊戲或引擎不支援 → 不能翻（回傳 False）。
    - detection 為 None（尚未選擇遊戲）→ False
    - detection.engine 不在 engine_supported 名單內 → False
    - 其餘（目前僅 P1 支援的 mv）→ True
    """
    if detection is None:
        return False
    return detection.engine in engine_supported


def can_restore(detection: Detection | None, engine_supported=SUPPORTED) -> bool:
    """
    「還原遊戲」鈕是否可用的純函式判斷（沿用 can_start 的規則）：
    - 尚未選擇遊戲（detection 為 None）→ False
    - 引擎不在支援名單內（目前僅 P1 支援的 mv）→ False
    - 其餘 → True
    與 can_start 邏輯目前相同，獨立成另一個函式是為了讓「開始」與「還原」
    兩顆鈕的啟用條件可以各自演進而不互相牽動。
    """
    return can_start(detection, engine_supported)


def visible_fields(engine: str) -> set[str]:
    """
    純函式：依「翻譯引擎」下拉選擇，回傳這個引擎該顯示哪些欄位（GUI 依此 setVisible）。

    欄位鍵：
    - "dict"：選擇字典 JSON 按鈕（offline 必選；deepl/local 皆為可選種子/打底）
    - "key"：DeepL API Key 輸入框（僅 deepl 需要）
    - "model"：本地 Ollama 模型下拉 + 重新整理鈕（僅 local 需要）

    對應規則：
    - offline（離線字典）→ {"dict"}：只需字典 JSON，不需要 key 或 model。
    - deepl               → {"dict", "key"}：需要 key；字典 JSON 為可選種子快取。
    - local（本地 Ollama）→ {"dict", "model"}：需要模型；字典 JSON 為可選打底
      （不選則從 0 開始翻，選了就當種子快取）。
    - 其餘未知字串 → 空集合（保守起見全部隱藏，避免顯示不相關欄位）。
    """
    if engine == "offline":
        return {"dict"}
    if engine == "deepl":
        return {"dict", "key"}
    if engine == "local":
        return {"dict", "model"}
    return set()


def choose_translator_mode(engine: str, dict_path: str | None, key: str) -> str:
    """
    翻譯引擎模式的核心決策（純函式，不碰檔案/網路，方便單測）。

    engine 現在直接由「翻譯引擎」下拉決定（offline/deepl/local 三選一，
    不再有「deepl 但沒填 key 就當 offline」的隱含猜測），本函式只負責檢查
    「該引擎的必要欄位是否已填」：
    - engine == "offline" → 需要 dict_path，有填 → "offline"，沒填 → "none"
    - engine == "deepl"   → 需要 key，有填 → "deepl"，沒填 → "none"
    - engine == "local"   → 不需 key 也不需字典即可啟動 → 一律 "local"
    - 其餘未知 engine → "none"
    """
    if engine == "offline":
        return "offline" if dict_path else "none"
    if engine == "deepl":
        return "deepl" if key else "none"
    if engine == "local":
        return "local"
    return "none"


def should_pretranslate_mz(detection, mode: str) -> bool:
    """加密 MZ 且選了會翻譯的引擎（local/deepl）時，需先批次預翻建字典。"""
    return (getattr(detection, "encrypted", False)
            and detection.engine == "mz"
            and mode in ("local", "deepl"))


class TyranoDeployWorker(QObject):
    """
    背景執行緒工作者：在非主執行緒跑「耗時」的 Tyrano 批次預翻部署（deploy_tyrano），
    避免卡住 Qt 主事件迴圈（GUI 凍結）。

    設計：QObject + moveToThread（而非繼承 QThread），方便日後替換/測試——
    run() 本身是一般方法，可在測試中脫離真正的 QThread、直接同步呼叫驗證邏輯，
    也可以視需要塞進 QThreadPool。三個 signal 皆為 queued 連線送回主執行緒：
    - progress(done, total, phase)：轉呼 deploy_tyrano 的 progress 回呼
    - finished(stats)：deploy_tyrano 成功回傳的統計 dict
    - error(message)：deploy_tyrano 拋出例外時的錯誤訊息（字串化後的例外內容）
    """
    progress = Signal(int, int, str)
    segment_progress = Signal(int, int)
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, game_dir: str, pipeline: Pipeline):
        super().__init__()
        self.game_dir = game_dir
        self.pipeline = pipeline

    def run(self) -> None:
        try:
            stats = deploy_tyrano(
                self.game_dir, self.pipeline,
                progress=lambda done, total, phase: self.progress.emit(done, total, phase),
                segment_progress=lambda done, total: self.segment_progress.emit(done, total))
        except Exception as e:
            self.error.emit(str(e))
            return
        self.finished.emit(stats)


class EncryptedMzWorker(QObject):
    """
    背景執行緒工作者：加密 MZ 的批次預翻（pretranslate_encrypted_mz），比照
    TyranoDeployWorker 的設計（QObject + moveToThread，signal 送回主執行緒）。
    - segment_progress(done, total)：轉呼 pretranslate_encrypted_mz 的 progress_cb
    - finished(offline_dict)：預翻完成後的完整離線字典
    - error(message)：例外訊息（字串化）
    """
    finished = Signal(dict)          # 回傳完整 offline_dict
    error = Signal(str)
    segment_progress = Signal(int, int)

    def __init__(self, web_dir: str, pipeline):
        super().__init__()
        self.web_dir = web_dir
        self.pipeline = pipeline

    def run(self):
        try:
            from adapters.mz.pretranslate import pretranslate_encrypted_mz
            result = pretranslate_encrypted_mz(
                self.web_dir, self.pipeline,
                progress_cb=lambda done, total: self.segment_progress.emit(done, total))
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001 — 背景執行緒需吞例外轉成 error signal
            self.error.emit(str(e))


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translator")
        self.exe_path: str | None = None
        self.detection: Detection | None = None
        self.server: TranslationServer | None = None
        self.dict_path: str | None = None  # 使用者選擇的既有字典 JSON（離線/種子用）
        self._tyrano_thread: QThread | None = None  # Tyrano 部署背景執行緒（進行中才有值）
        self._tyrano_worker: TyranoDeployWorker | None = None

        lay = QVBoxLayout(self)

        # ① 遊戲區：選擇主程式 + 偵測狀態
        game_box = QGroupBox("① 遊戲")
        game_lay = QVBoxLayout(game_box)
        self.pick_btn = QPushButton("選擇遊戲主程式…")
        # 已選遊戲的持久顯示：選好後固定顯示是哪個遊戲，不會被之後的啟動/狀態訊息蓋掉
        self.game_label = QLabel("尚未選擇遊戲")
        self.info = QLabel("請先選擇遊戲主程式")
        game_lay.addWidget(self.pick_btn)
        game_lay.addWidget(self.game_label)
        game_lay.addWidget(self.info)
        lay.addWidget(game_box)

        # ② 翻譯引擎區：下拉決定 mode，切換時只顯示相關欄位（見 visible_fields）
        engine_box_group = QGroupBox("② 翻譯引擎")
        engine_lay = QVBoxLayout(engine_box_group)
        self.engine_box = QComboBox()
        for display in ENGINE_DISPLAY_TO_KEY:
            self.engine_box.addItem(display)
        engine_lay.addWidget(self.engine_box)

        self.dict_btn = QPushButton("選擇字典 JSON…")
        engine_lay.addWidget(self.dict_btn)
        # 顯示目前選了哪個字典檔（完整路徑），方便確認選對檔案
        self.dict_label = QLabel("未選擇字典")
        engine_lay.addWidget(self.dict_label)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("DeepL API Key")
        engine_lay.addWidget(self.key_edit)

        model_row = QHBoxLayout()
        self.model_box = QComboBox()
        self.model_box.setEditable(True)  # 抓不到 Ollama 清單時仍可手動輸入模型名
        self.model_box.addItem(DEFAULT_LOCAL_MODEL)
        self.model_refresh_btn = QPushButton("重新整理")
        model_row.addWidget(self.model_box)
        model_row.addWidget(self.model_refresh_btn)
        engine_lay.addLayout(model_row)
        # model_row 內的兩個 widget 一起隨「model」欄位群組顯示/隱藏
        self._model_row_widgets = (self.model_box, self.model_refresh_btn)

        lay.addWidget(engine_box_group)

        # ③ 選項區：繁體中文／全域字典／存繁體／翻完後自動啟動
        options_box = QGroupBox("③ 選項")
        options_lay = QVBoxLayout(options_box)
        # 「繁體中文（台灣用語）」勾選框：預設勾選（使用者要繁體）。翻譯來源
        # （現成字典、DeepL、本地 Ollama）多半輸出簡體，勾選後統一用 OpenCC
        # s2twp 過一次簡轉繁（含台灣慣用語）。
        self.traditional_checkbox = QCheckBox("繁體中文（台灣用語）")
        # 依使用者要求：預設關閉、且不顯示於 UI（物件保留供內部流程讀取為 False）
        self.traditional_checkbox.setChecked(False)
        # 「使用全域共用字典（跨遊戲加速）」勾選框：預設勾選。勾選時 Pipeline 會
        # 額外查詢/寫入 ~/.game_translator/global_dict.json，讓 A 遊戲翻過的常見句子
        # （UI、常見用語、重複術語）在 B 遊戲直接命中、免再翻，越用越快；
        # 沒勾選則完全不碰全域字典，行為與加這個功能之前一致。
        self.global_dict_checkbox = QCheckBox("使用全域共用字典（跨遊戲加速）")
        self.global_dict_checkbox.setChecked(True)
        # 「翻譯 JSON 存繁體（預設存簡體較通用）」勾選框：預設不勾（即存簡體）。
        # 只有在勾選「繁體中文（台灣用語）」（有 postprocess）時，這個選項才有作用；
        # 決定「引擎新翻的條目」寫進 translator_dict.json/global_dict.json 時，
        # 存的是簡體原文（未勾，通用、其他工具較好讀）還是已轉繁體（勾選）。
        # 對應 Pipeline 的 store_converted 參數。
        self.store_converted_checkbox = QCheckBox(
            "翻譯 JSON 存繁體（預設存簡體較通用）")
        self.store_converted_checkbox.setChecked(False)
        # 「翻完後自動啟動遊戲」勾選框：預設勾選。
        # - RPG Maker（mv/mz）：勾選→部署完立刻 launch_game；不勾→只部署 adapter，
        #   不啟動遊戲（適合想先手動檢查部署結果，或想用自己的啟動方式的使用者）。
        # - Tyrano：勾選→背景批次翻完後 launch_game；不勾→翻完不啟動
        #   （批次預翻本來就要等全部翻完才能玩，這裡讓使用者選擇翻完後要不要立刻玩）。
        self.auto_launch_checkbox = QCheckBox("翻完後自動啟動遊戲")
        self.auto_launch_checkbox.setChecked(True)
        # 依使用者要求：繁體（traditional）與存繁體（store_converted）兩個選項不顯示於 UI、
        # 預設關閉；物件保留、供內部流程讀取為 False。要恢復顯示，把它們加回這個 tuple 即可。
        for w in (self.global_dict_checkbox, self.auto_launch_checkbox):
            options_lay.addWidget(w)
        lay.addWidget(options_box)

        # 開始／還原按鈕
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("開始")
        self.start_btn.setEnabled(False)
        self.restore_btn = QPushButton("還原遊戲（移除翻譯修改）")
        self.restore_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.restore_btn)
        lay.addLayout(btn_row)

        # 翻譯監控面板：句級進度 + 速度 + ETA + GPU（每秒刷新）。放在版面最下方；
        # GPU timer 一建立就開始跑，會即時反映本機 GPU 狀態（沒 NVIDIA GPU 時顯示不可用）。
        self.monitor = TranslationMonitor()
        lay.addWidget(self.monitor)

        self.pick_btn.clicked.connect(self.on_pick)
        self.dict_btn.clicked.connect(self.on_pick_dict)
        self.model_refresh_btn.clicked.connect(self.on_refresh_models)
        self.engine_box.currentTextChanged.connect(self.on_engine_changed)
        self.start_btn.clicked.connect(self.on_start)
        self.restore_btn.clicked.connect(self.on_restore)

        # 依預設引擎套一次條件顯示（建構時就要正確，不必等使用者切換一次）
        self.on_engine_changed(self.engine_box.currentText())

    def _current_engine(self) -> str:
        return ENGINE_DISPLAY_TO_KEY.get(self.engine_box.currentText(), "offline")

    def on_engine_changed(self, _display_text: str) -> None:
        # 切換翻譯引擎下拉時，只顯示該引擎相關欄位（visible_fields 純函式決定集合）
        fields = visible_fields(self._current_engine())
        self.dict_btn.setVisible("dict" in fields)
        self.key_edit.setVisible("key" in fields)
        show_model = "model" in fields
        for w in self._model_row_widgets:
            w.setVisible(show_model)
        # 選到「本地 Ollama」時，順手嘗試自動抓一次已安裝模型清單，省得使用者
        # 每次都要手動按「重新整理」。抓不到（服務未啟動等）list_ollama_models
        # 會回空清單，維持目前下拉內容不變（含使用者已手動輸入的模型名）。
        if self._current_engine() == "local":
            self._refresh_models_silently()

    def _refresh_models_silently(self) -> None:
        # 靜默版：抓不到就什麼都不做（維持既有下拉內容），不更新狀態列文字。
        # 供 on_engine_changed 在切換到 local 時自動呼叫。
        names = list_ollama_models()
        self._populate_model_box(names)

    def _populate_model_box(self, names: list[str]) -> None:
        # 把抓到的模型名稱填入 model_box，同時保留目前使用者已輸入/選取的文字
        # （QComboBox.setEditable(True) 下 clear() 會清空當下文字，故先記住再還原）。
        if not names:
            return
        current = self.model_box.currentText()
        self.model_box.clear()
        self.model_box.addItems(names)
        if current and current not in names:
            self.model_box.addItem(current)
        idx = self.model_box.findText(current)
        if idx >= 0:
            self.model_box.setCurrentIndex(idx)

    def on_refresh_models(self) -> None:
        # 使用者按下「重新整理」：主動查詢一次，並在狀態列回報結果（含抓不到的情況）
        names = list_ollama_models()
        if not names:
            self.info.setText("未偵測到本機 Ollama 模型（請確認 Ollama 服務已啟動），可手動輸入模型名稱")
            return
        self._populate_model_box(names)
        self.info.setText(f"已偵測到 {len(names)} 個本機 Ollama 模型")

    def on_pick(self):
        # 開檔案選擇對話框，選取遊戲主程式（.exe）
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇遊戲主程式", "", "執行檔 (*.exe)")
        if not path:
            return
        self.exe_path = path
        self.detection = detect(path)
        label = {"mv": "RPG Maker MV", "mz": "RPG Maker MZ",
                 "unity": "Unity", "tyrano": "TyranoScript",
                 "unknown": "未知引擎"}.get(
                     self.detection.engine, f"未知引擎（{self.detection.engine}）")
        ok = can_start(self.detection)
        # 顯示遊戲名（用上層資料夾名，通常即遊戲名）＋ exe 檔名，方便確認選對遊戲
        game_name = os.path.basename(self.detection.game_dir)
        exe_name = os.path.basename(path)
        # 加密 MZ 額外標「（加密）」，讓使用者一眼看出走的是解密預翻路徑
        engine_extra = "（加密）" if getattr(self.detection, "encrypted", False) else ""
        # 已選遊戲寫進持久的 game_label（不會被之後的啟動/狀態訊息覆蓋）；info 只放就緒/狀態訊息
        self.game_label.setText(
            f"遊戲：{game_name}（{exe_name}）｜偵測到：{label}{engine_extra}")
        self.info.setText(
            "可以開始翻譯" if ok else "此引擎尚未支援（之後由 OCR／專屬 adapter 處理）")
        # 核心規則：沒選到遊戲或引擎不支援 → 鎖住「開始」與「還原」
        self.start_btn.setEnabled(ok)
        self.restore_btn.setEnabled(can_restore(self.detection))

    def on_pick_dict(self):
        # 開檔案選擇對話框，選取既有字典 JSON（離線必選；deepl/local 可選種子/打底）
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇字典 JSON", "", "JSON (*.json)")
        if not path:
            return
        self.dict_path = path
        self.dict_label.setText(path)

    def _build_pipeline(self, d: Detection, mode: str, key: str) -> Pipeline:
        """
        依 mode 建立 Pipeline（cache + translator），mv/mz 與 tyrano 共用這段決策：
        - cache 來自使用者選的字典 JSON（若有，複製成該遊戲專屬的工作快取）
        - translator 依 mode：offline → NullTranslator、local → LocalTranslator、
          其餘（deepl）→ DeepLTranslator
        - postprocess：若勾選「繁體中文（台灣用語）」，套用 OpenCC s2twp 簡轉繁；
          否則為 None（維持原文，行為不變）。Tyrano 走 translate_tree（用這個
          Pipeline）會自動吃到 postprocess，不需另外處理。
        - global_cache：若勾選「使用全域共用字典（跨遊戲加速）」，額外開啟
          ~/.game_translator/global_dict.json 這本跨遊戲共用字典傳給 Pipeline；
          沒勾選則傳 None，Pipeline 完全不碰全域字典（維持既有行為）。
        - store_converted：只在有勾選「繁體中文（台灣用語）」時才把
          「翻譯 JSON 存繁體」勾選框的值傳給 Pipeline；未勾繁體時 postprocess
          本身就是 None，store_converted 不生效（Pipeline 內部亦有此判斷），
          這裡直接傳勾選框的值即可，不需額外判斷。
        """
        cache_path = os.path.join(d.game_dir, "translator_dict.json")
        # offline（必選）或「deepl/local 但有帶種子字典」都要把使用者選的 JSON
        # 複製成工作快取
        if self.dict_path:
            src = os.path.abspath(self.dict_path)
            dst = os.path.abspath(cache_path)
            # 來源與目的相同路徑時跳過複製，避免 shutil.copyfile 自我覆蓋出錯
            if src != dst:
                shutil.copyfile(src, dst)
        cache = DictCache(cache_path)

        global_cache = (
            DictCache(global_dict_path())
            if self.global_dict_checkbox.isChecked() else None)

        if mode == "offline":
            translator = NullTranslator()
        elif mode == "local":
            model = self.model_box.currentText().strip() or DEFAULT_LOCAL_MODEL
            translator = LocalTranslator(model=model)
        else:
            translator = DeepLTranslator(key, free=True)

        postprocess = (
            make_traditional_converter()
            if self.traditional_checkbox.isChecked() else None)
        return Pipeline(cache, translator, target_lang="ZH", source_lang="JA",
                        postprocess=postprocess, global_cache=global_cache,
                        store_converted=self.store_converted_checkbox.isChecked())

    def on_start(self):
        # 核心規則守衛：沒選遊戲/不支援引擎 → 不能翻（邏輯層生效，不只靠 UI 的 setEnabled）
        if not can_start(self.detection):
            return
        # 引擎選擇決策：offline（離線字典）/ deepl（線上，可帶種子字典）/
        # local（本地 Ollama，線上路徑），直接由引擎下拉決定，不再靠「有沒有填 key」猜測
        key = self.key_edit.text().strip()
        engine = self._current_engine()
        mode = choose_translator_mode(engine, self.dict_path, key)
        if mode == "none":
            if engine == "offline":
                self.info.setText("請選擇字典 JSON（離線字典模式必選）")
            else:
                self.info.setText("請填 DeepL API Key")
            return

        if self.detection.engine == "tyrano":
            self._on_start_tyrano(mode, key)
            return
        self._on_start_rpgmaker(mode, key)

    def _on_start_rpgmaker(self, mode: str, key: str) -> None:
        # RPG Maker（mv/mz）整合流程：讀地圖 → 起 server → 部署 adapter → （視 auto_launch）開遊戲
        # 全程 try/except 容錯：任一步驟丟例外（如填錯 DeepL key、斷網）都要顯示錯誤訊息，
        # 不可讓例外逸出導致 Qt 事件迴圈崩潰或 UI 靜默卡住。
        try:
            d = self.detection
            maps = []
            for mp in sorted(glob.glob(os.path.join(d.web_dir, "data", "Map*.json"))):
                try:
                    with open(mp, encoding="utf-8") as f:
                        maps.append(json.load(f))
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[警告] 讀取地圖失敗 {mp}: {e}")

            pipe = self._build_pipeline(d, mode, key)

            # 加密 MZ 且引擎會翻譯（local/deepl）：離線字典要靠引擎預翻填出，
            # 改走背景批次預翻 worker → 監控面板 → 完成後離線嵌入 + 啟動，
            # 不再走下面的即時 server 路徑。
            if should_pretranslate_mz(d, mode):
                self._on_start_encrypted_mz(d, pipe)
                return

            cache = pipe.cache

            # 重複點開始不疊加多個 server：起新 server 前先關掉舊的
            if self.server:
                self.server.stop()
            self.server = TranslationServer(pipe, port=0)
            port = self.server.start()
            bridge = resource_path(os.path.join(
                "adapters", "mv", "ZZ_Translator_Bridge.js"))
            # 離線模式：把整份字典嵌入遊戲端（MTool 式），供底層畫字 hook 即時查表；
            # DeepL 與本地 Ollama 皆維持 None，走既有 server/collectStrings 線上路徑，
            # 逐句翻並快取到 translator_dict.json，不受影響。
            offline_dict = cache.as_dict() if mode == "offline" else None
            # 離線整字典嵌入是直接把字典嵌進遊戲 JS、執行期不經 Pipeline，
            # 所以若勾選繁體，要在傳給 deploy_mv_adapter 前，把 offline_dict
            # 的「每個值」也用同一個轉換器轉一次（鍵＝原文保持不動，只轉值＝譯文）。
            if offline_dict is not None and self.traditional_checkbox.isChecked():
                convert = make_traditional_converter()
                offline_dict = {k: convert(v) for k, v in offline_dict.items()}
            deploy_mv_adapter(d.web_dir, port, maps, bridge_src=os.path.abspath(bridge),
                              offline_dict=offline_dict)

            auto_launch = self.auto_launch_checkbox.isChecked()
            if auto_launch:
                launch_game(self.exe_path)
            if not auto_launch:
                self.info.setText("已部署，未啟動（你可自行開 Game.exe）")
            elif mode == "offline":
                self.info.setText("已啟動（離線字典模式），翻譯服務執行中…")
            elif mode == "local":
                self.info.setText(
                    "已啟動（本地 Ollama 模式），翻譯服務執行中…"
                    "（首次翻譯較慢，之後走快取）")
            else:
                self.info.setText("已啟動遊戲，翻譯服務執行中…")
        except Exception as e:
            self.info.setText(f"啟動失敗：{e}")

    def _on_start_tyrano(self, mode: str, key: str) -> None:
        # TyranoScript 流程：部署「就是」批次預翻，不需要 server，也不用讀地圖。
        # 因為要翻完全部 .ks 才能啟動遊戲，較耗時，故在背景執行緒跑，避免卡住 GUI；
        # progress 透過 Qt signal（queued 連線）回主執行緒更新 self.info。
        try:
            d = self.detection
            pipe = self._build_pipeline(d, mode, key)
        except Exception as e:
            self.info.setText(f"啟動失敗：{e}")
            return

        self.start_btn.setEnabled(False)
        self.info.setText("翻譯中（Tyrano）：準備中…")
        # 每次啟動一輪翻譯前重置監控面板的句級進度/速度/ETA（GPU timer 不受影響、持續刷新）
        self.monitor.reset()

        thread = QThread()
        worker = TyranoDeployWorker(d.game_dir, pipe)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_tyrano_progress)
        # 句級進度用 queued 連線（背景 worker → 主執行緒）餵進監控面板；
        # set_progress 只在主執行緒被呼叫，不需加鎖。
        worker.segment_progress.connect(self.monitor.set_progress)
        worker.finished.connect(self._on_tyrano_finished)
        worker.error.connect(self._on_tyrano_error)
        # 收尾：worker 跑完（成功或失敗）就請 thread 結束事件迴圈並釋放。
        # 注意：釋放 self._tyrano_thread/_tyrano_worker 的參照必須等到 thread.finished
        # （QThread 的事件迴圈真正退出後）才能做——若在 worker.finished/error 當下
        # （此時 thread 可能仍在退出過程中）就把 Python 對 thread 的最後參照清掉，
        # GC 會嘗試銷毀一個仍在運行中的 QThread，導致卡死（已實測重現此問題）。
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_tyrano_thread_finished)
        thread.finished.connect(thread.deleteLater)

        # 保留參考，避免執行緒/worker 被 Python GC 提前回收
        self._tyrano_thread = thread
        self._tyrano_worker = worker
        thread.start()

    def _on_tyrano_progress(self, done: int, total: int, phase: str) -> None:
        phase_label = {"collect": "收集文字", "translate": "翻譯中", "write": "寫回檔案"}.get(
            phase, phase)
        self.info.setText(f"翻譯中（Tyrano，{phase_label}）：{done}/{total}")

    def _on_tyrano_finished(self, stats: dict) -> None:
        # 只負責（視 auto_launch）啟動遊戲與更新訊息；執行緒參照的釋放交給
        # _on_tyrano_thread_finished。
        try:
            auto_launch = self.auto_launch_checkbox.isChecked()
            if auto_launch:
                launch_game(self.exe_path)
                self.info.setText(
                    "已完成翻譯並啟動（Tyrano）：翻了 %d/%d 段"
                    % (stats.get("translated", 0), stats.get("segments", 0)))
            else:
                self.info.setText(
                    "翻譯完成，未啟動（Tyrano）：翻了 %d/%d 段"
                    % (stats.get("translated", 0), stats.get("segments", 0)))
        except Exception as e:
            self.info.setText(f"Tyrano 部署失敗：{e}")

    def _on_tyrano_error(self, message: str) -> None:
        self.info.setText(f"Tyrano 部署失敗：{message}")

    def _on_tyrano_thread_finished(self) -> None:
        # QThread 的事件迴圈已真正結束，此時釋放參照才安全；同時恢復「開始」鈕可用。
        self.start_btn.setEnabled(can_start(self.detection))
        self._tyrano_thread = None
        self._tyrano_worker = None

    def _on_start_encrypted_mz(self, d, pipe):
        # 加密 MZ：背景預翻 → 完成後離線嵌入 + 啟動。比照 Tyrano 的執行緒收尾
        # （worker.finished/error → thread.quit → thread.finished → 才釋放參照，
        # 避免仍在運行中的 QThread 被 Python GC 提前回收導致卡死）。
        from core.translators.protect import ControlCodeTranslator
        pipe.translator = ControlCodeTranslator(pipe.translator)

        # 加密 MZ 走離線整字典嵌入，執行期不需 server；先關掉任何殘留的舊 server 避免洩漏 socket
        if self.server:
            self.server.stop()
            self.server = None

        self.start_btn.setEnabled(False)
        self.info.setText("翻譯中（加密 MZ）：解密與預翻…")
        self.monitor.reset()

        thread = QThread()
        worker = EncryptedMzWorker(d.web_dir, pipe)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.segment_progress.connect(self.monitor.set_progress)
        worker.finished.connect(lambda dic: self._on_encrypted_mz_finished(d, dic))
        worker.error.connect(self._on_tyrano_error)   # 復用既有錯誤顯示
        worker.finished.connect(thread.quit)
        worker.error.connect(thread.quit)
        thread.finished.connect(self._on_tyrano_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._tyrano_thread = thread
        self._tyrano_worker = worker
        thread.start()

    def _on_encrypted_mz_finished(self, d, offline_dict):
        try:
            if self.traditional_checkbox.isChecked():
                convert = make_traditional_converter()
                offline_dict = {k: convert(v) for k, v in offline_dict.items()}
            port = 0  # 離線整字典嵌入模式不需 server，port 不會被 bridge 使用
            bridge = resource_path(os.path.join("adapters", "mv", "ZZ_Translator_Bridge.js"))
            deploy_mv_adapter(d.web_dir, port, [], bridge_src=os.path.abspath(bridge),
                              offline_dict=offline_dict)
            if self.auto_launch_checkbox.isChecked():
                launch_game(self.exe_path)
                self.info.setText("已啟動（加密 MZ 離線字典模式）")
            else:
                self.info.setText("已部署（加密 MZ），未啟動")
        except Exception as e:
            self.info.setText(f"部署失敗：{e}")
        finally:
            self.start_btn.setEnabled(True)

    def on_restore(self):
        # 核心規則守衛：沒選遊戲/不支援引擎 → 不能還原（邏輯層生效，不只靠 UI 的 setEnabled）
        if not can_restore(self.detection):
            return
        # 全程 try/except 容錯：還原失敗要顯示錯誤訊息，不可讓例外逸出導致 Qt 事件迴圈崩潰
        try:
            # 還原前先停掉目前執行中的翻譯 server（若有），避免遊戲仍佔用/依賴中的服務衝突
            if self.server:
                self.server.stop()
                self.server = None
            if self.detection.engine == "tyrano":
                restore_tyrano(self.detection.game_dir)
            else:
                restore_mv_adapter(self.detection.web_dir)
            self.info.setText("已還原遊戲原始檔")
        except Exception as e:
            self.info.setText(f"還原失敗：{e}")
