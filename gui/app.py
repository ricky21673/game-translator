# 最小 PySide6 GUI：選遊戲 exe → 自動判型 → 顯示 → 依「是否支援」鎖/解鎖「開始」
# → 按開始執行整合流程：
#   - RPG Maker（mv/mz）：讀地圖 → 起 server → 部署 adapter → 開遊戲，翻譯在遊戲執行時
#     由 server 即時處理。
#   - TyranoScript（tyrano）：部署「就是」批次預翻（解包 app.asar → 翻完所有 .ks →
#     改名讓 Electron 吃解包後的 app/），較耗時但翻完直接啟動，執行時不需要 server。
#     因為耗時，部署階段在背景執行緒跑，避免卡住 GUI 事件迴圈；進度透過 Qt signal
#     回主執行緒更新畫面。
import glob
import json
import os
import shutil
import sys

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QVBoxLayout, QFileDialog, QCheckBox,
)

from core.detector import detect, Detection
from core.cache import DictCache
from core.paths import global_dict_path
from core.pipeline import Pipeline
from core.postprocess import make_traditional_converter
from core.server import TranslationServer
from core.translators.deepl import DeepLTranslator
from core.translators.null import NullTranslator
from core.translators.local import LocalTranslator
from launcher import deploy_mv_adapter, launch_game, restore_mv_adapter
from adapters.tyrano.deploy import deploy_tyrano, restore_tyrano

SUPPORTED = ("mv", "mz", "tyrano")  # 支援 MV、MZ 與 TyranoScript
DEFAULT_LOCAL_MODEL = "qwen2.5:14b"

# GUI 顯示字串 → choose_translator_mode 用的 engine 值
ENGINE_DISPLAY_TO_KEY = {
    "DeepL": "deepl",
    "本地 Ollama": "local",
}


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


def choose_translator_mode(engine: str, dict_path: str | None, key: str) -> str:
    """
    翻譯引擎模式的核心決策（純函式，不碰檔案/網路，方便單測）：
    - engine == "local" → "local"（本地 Ollama，不需 key 也不需字典即可啟動，優先於其他判斷）
    - 其餘（engine 非 local）：
      - 有選字典 JSON 且沒填 key → "offline"（離線字典模式，NullTranslator）
      - 有填 key（不論是否也選了字典 JSON）→ "deepl"（DeepL，若同時選了字典 JSON 則帶種子快取）
      - 兩者都沒有 → "none"（不可啟動）
    """
    if engine == "local":
        return "local"
    has_dict = bool(dict_path)
    has_key = bool(key)
    if has_key:
        return "deepl"
    if has_dict:
        return "offline"
    return "none"


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
                progress=lambda done, total, phase: self.progress.emit(done, total, phase))
        except Exception as e:
            self.error.emit(str(e))
            return
        self.finished.emit(stats)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translator (P1)")
        self.exe_path: str | None = None
        self.detection: Detection | None = None
        self.server: TranslationServer | None = None
        self.dict_path: str | None = None  # 使用者選擇的既有字典 JSON（離線模式用）
        self._tyrano_thread: QThread | None = None  # Tyrano 部署背景執行緒（進行中才有值）
        self._tyrano_worker: TyranoDeployWorker | None = None

        self.pick_btn = QPushButton("選擇遊戲主程式…")
        self.info = QLabel("請先選擇遊戲主程式")
        self.engine_box = QComboBox()
        self.engine_box.addItem("DeepL")
        self.engine_box.addItem("本地 Ollama")
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("DeepL API Key")
        self.model_edit = QLineEdit()
        self.model_edit.setText(DEFAULT_LOCAL_MODEL)
        self.model_edit.setPlaceholderText("本地 Ollama 模型名稱")
        self.dict_btn = QPushButton("選擇既有字典 JSON（離線，可不填 key）")
        # 「繁體中文（台灣用語）」勾選框：預設勾選（使用者要繁體）。翻譯來源
        # （現成字典、DeepL、本地 Ollama）多半輸出簡體，勾選後統一用 OpenCC
        # s2twp 過一次簡轉繁（含台灣慣用語）。
        self.traditional_checkbox = QCheckBox("繁體中文（台灣用語）")
        self.traditional_checkbox.setChecked(True)
        # 「使用全域共用字典（跨遊戲加速）」勾選框：預設勾選。勾選時 Pipeline 會
        # 額外查詢/寫入 ~/.game_translator/global_dict.json，讓 A 遊戲翻過的常見句子
        # （UI、常見用語、重複術語）在 B 遊戲直接命中、免再翻，越用越快；
        # 沒勾選則完全不碰全域字典，行為與加這個功能之前一致。
        self.global_dict_checkbox = QCheckBox("使用全域共用字典（跨遊戲加速）")
        self.global_dict_checkbox.setChecked(True)
        self.start_btn = QPushButton("開始")
        self.start_btn.setEnabled(False)
        self.restore_btn = QPushButton("還原遊戲（移除翻譯修改）")
        self.restore_btn.setEnabled(False)

        lay = QVBoxLayout(self)
        for w in (self.pick_btn, self.info, self.engine_box, self.key_edit,
                  self.model_edit, self.dict_btn, self.traditional_checkbox,
                  self.global_dict_checkbox, self.start_btn, self.restore_btn):
            lay.addWidget(w)

        self.pick_btn.clicked.connect(self.on_pick)
        self.dict_btn.clicked.connect(self.on_pick_dict)
        self.start_btn.clicked.connect(self.on_start)
        self.restore_btn.clicked.connect(self.on_restore)

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
        self.info.setText(
            f"偵測到：{label}" + ("" if ok else "（P1 尚未支援，之後由 OCR/專屬 adapter 處理）"))
        # 核心規則：沒選到遊戲或引擎不支援 → 鎖住「開始」與「還原」
        self.start_btn.setEnabled(ok)
        self.restore_btn.setEnabled(can_restore(self.detection))

    def on_pick_dict(self):
        # 開檔案選擇對話框，選取既有字典 JSON（離線字典模式用）
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇既有字典 JSON", "", "JSON (*.json)")
        if not path:
            return
        self.dict_path = path

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
        """
        cache_path = os.path.join(d.game_dir, "translator_dict.json")
        # offline 或「deepl 但有帶種子字典」都要把使用者選的 JSON 複製成工作快取
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
            model = self.model_edit.text().strip() or DEFAULT_LOCAL_MODEL
            translator = LocalTranslator(model=model)
        else:
            translator = DeepLTranslator(key, free=True)

        postprocess = (
            make_traditional_converter()
            if self.traditional_checkbox.isChecked() else None)
        return Pipeline(cache, translator, target_lang="ZH", source_lang="JA",
                        postprocess=postprocess, global_cache=global_cache)

    def on_start(self):
        # 核心規則守衛：沒選遊戲/不支援引擎 → 不能翻（邏輯層生效，不只靠 UI 的 setEnabled）
        if not can_start(self.detection):
            return
        # 引擎選擇決策：local（本地 Ollama，線上路徑）/ offline（離線字典）/
        # deepl（線上，可帶種子字典）/ none（都沒填）
        key = self.key_edit.text().strip()
        engine = ENGINE_DISPLAY_TO_KEY.get(self.engine_box.currentText(), "deepl")
        mode = choose_translator_mode(engine, self.dict_path, key)
        if mode == "none":
            self.info.setText("請填 DeepL key 或選擇既有字典 JSON")
            return

        if self.detection.engine == "tyrano":
            self._on_start_tyrano(mode, key)
            return
        self._on_start_rpgmaker(mode, key)

    def _on_start_rpgmaker(self, mode: str, key: str) -> None:
        # RPG Maker（mv/mz）整合流程：讀地圖 → 起 server → 部署 adapter → 開遊戲
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
            launch_game(self.exe_path)
            if mode == "offline":
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

        thread = QThread()
        worker = TyranoDeployWorker(d.game_dir, pipe)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress.connect(self._on_tyrano_progress)
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
        # 只負責啟動遊戲與更新訊息；執行緒參照的釋放交給 _on_tyrano_thread_finished。
        try:
            launch_game(self.exe_path)
            self.info.setText(
                "已完成翻譯並啟動（Tyrano）：翻了 %d/%d 段"
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
