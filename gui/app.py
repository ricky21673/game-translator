# 最小 PySide6 GUI：選遊戲 exe → 自動判型 → 顯示 → 依「是否支援」鎖/解鎖「開始」
# → 按開始執行整合流程（讀地圖 → 起 server → 部署 adapter → 開遊戲）。
import glob
import json
import os
import shutil
import sys

from PySide6.QtWidgets import (
    QWidget, QPushButton, QLabel, QComboBox, QLineEdit,
    QVBoxLayout, QFileDialog,
)

from core.detector import detect, Detection
from core.cache import DictCache
from core.pipeline import Pipeline
from core.server import TranslationServer
from core.translators.deepl import DeepLTranslator
from core.translators.null import NullTranslator
from core.translators.local import LocalTranslator
from launcher import deploy_mv_adapter, launch_game, restore_mv_adapter

SUPPORTED = ("mv", "mz")  # 支援 MV 與 MZ
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


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Translator (P1)")
        self.exe_path: str | None = None
        self.detection: Detection | None = None
        self.server: TranslationServer | None = None
        self.dict_path: str | None = None  # 使用者選擇的既有字典 JSON（離線模式用）

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
        self.start_btn = QPushButton("開始")
        self.start_btn.setEnabled(False)
        self.restore_btn = QPushButton("還原遊戲（移除翻譯修改）")
        self.restore_btn.setEnabled(False)

        lay = QVBoxLayout(self)
        for w in (self.pick_btn, self.info, self.engine_box, self.key_edit,
                  self.model_edit, self.dict_btn, self.start_btn, self.restore_btn):
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
        # 整合流程：讀地圖 → 起 server → 部署 adapter → 開遊戲
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

            cache_path = os.path.join(d.game_dir, "translator_dict.json")
            # offline 或「deepl 但有帶種子字典」都要把使用者選的 JSON 複製成工作快取
            if self.dict_path:
                src = os.path.abspath(self.dict_path)
                dst = os.path.abspath(cache_path)
                # 來源與目的相同路徑時跳過複製，避免 shutil.copyfile 自我覆蓋出錯
                if src != dst:
                    shutil.copyfile(src, dst)
            cache = DictCache(cache_path)

            if mode == "offline":
                translator = NullTranslator()
            elif mode == "local":
                model = self.model_edit.text().strip() or DEFAULT_LOCAL_MODEL
                translator = LocalTranslator(model=model)
            else:
                translator = DeepLTranslator(key, free=True)
            pipe = Pipeline(cache, translator, target_lang="ZH", source_lang="JA")

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
            restore_mv_adapter(self.detection.web_dir)
            self.info.setText("已還原遊戲原始檔")
        except Exception as e:
            self.info.setText(f"還原失敗：{e}")
