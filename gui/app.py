# 最小 PySide6 GUI：選遊戲 exe → 自動判型 → 顯示 → 依「是否支援」鎖/解鎖「開始」
# → 按開始執行整合流程（讀地圖 → 起 server → 部署 adapter → 開遊戲）。
import glob
import json
import os

from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QVBoxLayout, QFileDialog,
)

from core.detector import detect, Detection
from core.cache import DictCache
from core.pipeline import Pipeline
from core.server import TranslationServer
from core.translators.deepl import DeepLTranslator
from launcher import deploy_mv_adapter, launch_game

SUPPORTED = ("mv",)  # P1 只支援 MV


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


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translator (P1)")
        self.exe_path: str | None = None
        self.detection: Detection | None = None
        self.server: TranslationServer | None = None

        self.pick_btn = QPushButton("選擇遊戲主程式…")
        self.info = QLabel("請先選擇遊戲主程式")
        self.engine_box = QComboBox()
        self.engine_box.addItem("DeepL")
        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("DeepL API Key")
        self.start_btn = QPushButton("開始")
        self.start_btn.setEnabled(False)

        lay = QVBoxLayout(self)
        for w in (self.pick_btn, self.info, self.engine_box, self.key_edit, self.start_btn):
            lay.addWidget(w)

        self.pick_btn.clicked.connect(self.on_pick)
        self.start_btn.clicked.connect(self.on_start)

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
        # 核心規則：沒選到遊戲或引擎不支援 → 鎖住「開始」
        self.start_btn.setEnabled(ok)

    def on_start(self):
        # 核心規則守衛：沒選遊戲/不支援引擎 → 不能翻（邏輯層生效，不只靠 UI 的 setEnabled）
        if not can_start(self.detection):
            return
        # 整合流程：讀地圖 → 起 server → 部署 adapter → 開遊戲
        # 全程 try/except 容錯：任一步驟丟例外（如填錯 DeepL key、斷網）都要顯示錯誤訊息，
        # 不可讓例外逸出導致 Qt 事件迴圈崩潰或 UI 靜默卡住。
        try:
            d = self.detection
            maps = []
            for mp in sorted(glob.glob(os.path.join(d.www_dir, "data", "Map*.json"))):
                try:
                    maps.append(json.load(open(mp, encoding="utf-8")))
                except (json.JSONDecodeError, OSError) as e:
                    print(f"[警告] 讀取地圖失敗 {mp}: {e}")
            key = self.key_edit.text().strip()
            cache = DictCache(os.path.join(d.game_dir, "translator_dict.json"))
            pipe = Pipeline(cache, DeepLTranslator(key, free=True),
                            target_lang="ZH", source_lang="JA")
            # 重複點開始不疊加多個 server：起新 server 前先關掉舊的
            if self.server:
                self.server.stop()
            self.server = TranslationServer(pipe, port=0)
            port = self.server.start()
            bridge = os.path.join(os.path.dirname(__file__), "..",
                                  "adapters", "mv", "ZZ_Translator_Bridge.js")
            deploy_mv_adapter(d.www_dir, port, maps, bridge_src=os.path.abspath(bridge))
            launch_game(self.exe_path)
            self.info.setText("已啟動遊戲，翻譯服務執行中…")
        except Exception as e:
            self.info.setText(f"啟動失敗：{e}")
