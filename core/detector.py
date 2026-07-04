import json
import os
from dataclasses import dataclass

from .asar import read_asar_header, iter_files
from .mz_decrypt import is_encrypted_mz


@dataclass
class Detection:
    """
    遊戲引擎偵測結果。

    屬性：
    - engine: 偵測到的引擎名稱（'mv'|'mz'|'unity'|'tyrano'|'unknown'）
    - game_dir: 遊戲根目錄的絕對路徑
    - www_dir: MV 遊戲的 www 目錄路徑（若存在）
    - js_dir: 遊戲核心 js 檔所在目錄（若存在）
    - web_dir: 含 index.html 與 js/ 的目錄（MV/MZ 部署與注入流程共用的基準目錄）。
      MV 時等於 www_dir；MZ（無 www，根目錄即含 js/）時等於 game_dir。
      unity/tyrano/unknown 維持 None。
    - encrypted: MZ 遊戲是否為加密格式（預設 False，向後相容）。
    """
    engine: str
    game_dir: str
    www_dir: str | None = None
    js_dir: str | None = None
    web_dir: str | None = None
    encrypted: bool = False


def _mz_data_encrypted(web_dir: str) -> bool:
    """peek data/ 內第一個 *.json（跳過空/損毀檔），判斷是否為加密 MZ 格式。"""
    import glob
    for path in sorted(glob.glob(os.path.join(web_dir, "data", "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                obj = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        return is_encrypted_mz(obj)
    return False


def detect(exe_path: str) -> Detection:
    """
    根據可執行檔路徑偵測遊戲引擎。

    支援的引擎：
    - MV: 透過檢查 rpg_core.js 檔案（在 www/js 或根 js 目錄）
    - MZ: 透過檢查 rmmz_core.js 檔案（在 www/js 或根 js 目錄）
    - Unity: 透過檢查 UnityPlayer.dll 或 *_Data 目錄
    - TyranoScript（Electron 打包，未部署）: 透過 resources/app.asar 內是否含 .ks 檔或路徑含 "tyrano"
    - TyranoScript（Electron 打包，已被本工具部署過）: 透過 resources/app.asar.trbak 備份存在，
      或 resources/app/ 解包資料夾內找得到 .ks 檔
    - TyranoScript（未打包）: 透過檢查 data/scenario 目錄
    - 未知: 無法識別時回傳此項

    參數：
    - exe_path: 遊戲可執行檔的絕對路徑

    回傳：
    - Detection 物件，含引擎類型及相關目錄資訊
    """
    game_dir = os.path.dirname(os.path.abspath(exe_path))

    # MV/MZ 的 js 可能在 <dir>/www/js 或 <dir>/js
    # web_dir 為含 index.html 與 js/ 的基準目錄，即 js_dir 的上一層（os.path.dirname(js_dir)）。
    for base in (os.path.join(game_dir, "www"), game_dir):
        js_dir = os.path.join(base, "js")
        if os.path.isfile(os.path.join(js_dir, "rpg_core.js")):
            www = base if os.path.basename(base) == "www" else None
            return Detection("mv", game_dir, www, js_dir, os.path.dirname(js_dir))
        if os.path.isfile(os.path.join(js_dir, "rmmz_core.js")):
            www = base if os.path.basename(base) == "www" else None
            web_dir = os.path.dirname(js_dir)
            return Detection("mz", game_dir, www, js_dir, web_dir,
                             encrypted=_mz_data_encrypted(web_dir))

    # Unity：UnityPlayer.dll 或任何 *_Data 目錄
    if os.path.isfile(os.path.join(game_dir, "UnityPlayer.dll")):
        return Detection("unity", game_dir)
    # 防禦：game_dir 不存在時跳過 listdir 掃描，避免 FileNotFoundError/PermissionError
    if os.path.isdir(game_dir):
        for name in os.listdir(game_dir):
            if name.endswith("_Data") and os.path.isdir(os.path.join(game_dir, name)):
                return Detection("unity", game_dir)

    # TyranoScript（Electron 打包）：涵蓋「未部署」與「已被本工具部署過」兩種狀態。
    resources_dir = os.path.join(game_dir, "resources")

    # (1) 未部署：resources/app.asar 內含 .ks 檔或路徑含 "tyrano"
    asar_path = os.path.join(resources_dir, "app.asar")
    if os.path.isfile(asar_path):
        try:
            header, _base, _data = read_asar_header(asar_path)
            files = iter_files(header)
        except Exception:
            # 讀取失敗（非合法 asar 或格式不符）就不判為 tyrano，往下走
            files = None
        if files is not None:
            for rel_path, _size, _offset in files:
                lower = rel_path.lower()
                if lower.endswith(".ks") or "tyrano" in lower:
                    return Detection("tyrano", game_dir)

    # (2) 已被本工具部署過：部署時會把 app.asar 改名成 app.asar.trbak 並解包成 resources/app/。
    #     任一跡象成立即判 tyrano。全程容錯，失敗就不誤判、往下走原本流程。
    try:
        # (2a) 備份檔存在，代表這是我們處理過的 Tyrano
        if os.path.isfile(os.path.join(resources_dir, "app.asar.trbak")):
            return Detection("tyrano", game_dir)

        # (2b) 解包出的 resources/app/ 資料夾內找得到任一 .ks 檔（找到第一個即可，不必全掃）
        app_dir = os.path.join(resources_dir, "app")
        if os.path.isdir(app_dir):
            for _root, _dirs, filenames in os.walk(app_dir):
                if any(fn.lower().endswith(".ks") for fn in filenames):
                    return Detection("tyrano", game_dir)
    except Exception:
        # 檢查過程出錯就不誤判為 tyrano，往下走原本流程
        pass

    # TyranoScript（未打包，直接解壓）
    if os.path.isdir(os.path.join(game_dir, "data", "scenario")):
        return Detection("tyrano", game_dir)

    return Detection("unknown", game_dir)
