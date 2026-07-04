import os
from dataclasses import dataclass

from .asar import read_asar_header, iter_files


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
    """
    engine: str
    game_dir: str
    www_dir: str | None = None
    js_dir: str | None = None
    web_dir: str | None = None


def detect(exe_path: str) -> Detection:
    """
    根據可執行檔路徑偵測遊戲引擎。

    支援的引擎：
    - MV: 透過檢查 rpg_core.js 檔案（在 www/js 或根 js 目錄）
    - MZ: 透過檢查 rmmz_core.js 檔案（在 www/js 或根 js 目錄）
    - Unity: 透過檢查 UnityPlayer.dll 或 *_Data 目錄
    - TyranoScript（Electron 打包）: 透過 resources/app.asar 內是否含 .ks 檔或路徑含 "tyrano"
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
            return Detection("mz", game_dir, www, js_dir, os.path.dirname(js_dir))

    # Unity：UnityPlayer.dll 或任何 *_Data 目錄
    if os.path.isfile(os.path.join(game_dir, "UnityPlayer.dll")):
        return Detection("unity", game_dir)
    # 防禦：game_dir 不存在時跳過 listdir 掃描，避免 FileNotFoundError/PermissionError
    if os.path.isdir(game_dir):
        for name in os.listdir(game_dir):
            if name.endswith("_Data") and os.path.isdir(os.path.join(game_dir, name)):
                return Detection("unity", game_dir)

    # TyranoScript（Electron 打包）：resources/app.asar 內含 .ks 檔或路徑含 "tyrano"
    asar_path = os.path.join(game_dir, "resources", "app.asar")
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

    # TyranoScript（未打包，直接解壓）
    if os.path.isdir(os.path.join(game_dir, "data", "scenario")):
        return Detection("tyrano", game_dir)

    return Detection("unknown", game_dir)
