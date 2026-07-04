"""
TyranoScript（Electron 打包）遊戲的部署與還原核心。

策略（已實機驗證，見 core/asar.py 與 adapters/tyrano/ks.py 的說明）：
- TyranoScript 遊戲以 Electron 打包，內容在 <game_dir>/resources/app.asar。
- 部署流程：解包 app.asar -> 逐檔翻譯 .ks -> 把 app.asar 改名成 app.asar.trbak，
  Electron 找不到 app.asar 時會改用解包出來的 resources/app/ 資料夾。
- 純檔案操作（解包/改名/搬移），不動 Electron 執行檔本身，故可還原：
  只要把 app.asar.trbak 改回 app.asar、刪掉 app/ 資料夾即可完全復原。
- 可重入：若偵測到 app.asar.trbak 已存在（代表先前已部署過），不再重複解包/改名，
  直接對現有 resources/app/ 跑一次翻譯（例如中斷後重跑、或補翻新字串）。
"""
import os
import shutil

from core.asar import extract_asar
from core.pipeline import Pipeline
from .ks import extract_segments, apply_translations


def translate_tree(app_dir: str, pipeline: Pipeline, progress=None) -> dict:
    """
    走訪 app_dir 下所有 .ks 檔，彙整全部可翻段、一次送 pipeline 翻譯，再逐檔寫回。

    參數：
    - app_dir: 已解包的 TyranoScript app 資料夾（resources/app）
    - pipeline: 具 .translate(texts) -> list[str] 的翻譯管線
    - progress: 可選 callable(done_files, total_files, phase_str)，用於回報進度給 GUI。
      phase_str 為下列三階段之一："collect"（翻譯前收集）、"translate"（翻譯中）、
      "write"（寫回中）。

    回傳：
    - 統計 dict：{"ks_files": n, "segments": m, "translated": k}
      - ks_files: 找到的 .ks 檔數
      - segments: 去重後送去翻譯的段落數
      - translated: mapping 中譯文與原文不同的段落數（實際被翻動的段數）
    """
    # 第一步：找出所有 .ks 檔案路徑
    ks_paths: list[str] = []
    for root, _dirs, filenames in os.walk(app_dir):
        for name in filenames:
            if name.lower().endswith(".ks"):
                ks_paths.append(os.path.join(root, name))

    total_files = len(ks_paths)

    # 第二步：收集全部可翻段（跨檔彙整、去重，保留首次出現順序）
    all_segments: list[str] = []
    seen: set[str] = set()
    file_texts: dict[str, str] = {}
    for i, ks_path in enumerate(ks_paths):
        if progress:
            progress(i, total_files, "collect")
        with open(ks_path, "r", encoding="utf-8") as f:
            text = f.read()
        file_texts[ks_path] = text
        for seg in extract_segments(text):
            if seg not in seen:
                seen.add(seg)
                all_segments.append(seg)
    if progress:
        progress(total_files, total_files, "collect")

    # 第三步：一次把去重後的段落送去翻譯，組成 mapping
    if progress:
        progress(0, total_files, "translate")
    translated_list = pipeline.translate(all_segments) if all_segments else []
    mapping = dict(zip(all_segments, translated_list))
    if progress:
        progress(total_files, total_files, "translate")

    # 第四步：逐檔用 mapping 回寫（UTF-8）
    for i, ks_path in enumerate(ks_paths):
        if progress:
            progress(i, total_files, "write")
        new_text = apply_translations(file_texts[ks_path], mapping)
        with open(ks_path, "w", encoding="utf-8") as f:
            f.write(new_text)
    if progress:
        progress(total_files, total_files, "write")

    translated_count = sum(1 for src, dst in mapping.items() if dst != src)
    return {
        "ks_files": total_files,
        "segments": len(all_segments),
        "translated": translated_count,
    }


def deploy_tyrano(game_dir: str, pipeline: Pipeline, progress=None) -> dict:
    """
    部署 TyranoScript（Electron）遊戲：解包 app.asar -> 翻譯 .ks -> 改名讓 Electron 改用解包資料夾。

    可重入：若先前已部署過（app.asar.trbak 已存在），視為已解包，直接對現有
    resources/app/ 跑 translate_tree，不重複解包/改名。

    參數：
    - game_dir: 遊戲根目錄（含 resources/app.asar）
    - pipeline: 具 .translate(texts) -> list[str] 的翻譯管線
    - progress: 可選 callable(done_files, total_files, phase_str)，透傳給 translate_tree

    回傳：
    - translate_tree 的統計 dict
    """
    resources = os.path.join(game_dir, "resources")
    asar = os.path.join(resources, "app.asar")
    app_dir = os.path.join(resources, "app")
    bak = os.path.join(resources, "app.asar.trbak")

    if os.path.isfile(bak):
        # 先前已部署過：app.asar 已改名為 .trbak，app_dir 已存在，直接補翻
        return translate_tree(app_dir, pipeline, progress)

    # 首次部署：解包 -> 翻譯 -> 改名
    extract_asar(asar, app_dir)
    stats = translate_tree(app_dir, pipeline, progress)
    os.replace(asar, bak)
    return stats


def restore_tyrano(game_dir: str) -> None:
    """
    還原 TyranoScript（Electron）遊戲：刪除解包資料夾、把 app.asar.trbak 改名回 app.asar。

    全程容錯：若 app.asar.trbak 不存在（代表從未部署過或已還原過），只印出警告、
    不拋例外。

    參數：
    - game_dir: 遊戲根目錄（含 resources/）
    """
    resources = os.path.join(game_dir, "resources")
    asar = os.path.join(resources, "app.asar")
    app_dir = os.path.join(resources, "app")
    bak = os.path.join(resources, "app.asar.trbak")

    if not os.path.isfile(bak):
        print("找不到 app.asar.trbak，略過還原（可能尚未部署過或已還原過）")
        return

    if os.path.isdir(app_dir):
        shutil.rmtree(app_dir)
    os.replace(bak, asar)
