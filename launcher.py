import json
import os
import re
import shutil
import subprocess

_PLUGIN_NAME = "ZZ_Translator_Bridge"
_TRBAK_SUFFIX = ".trbak"  # 自動備份檔副檔名（保存部署前的原始檔案內容）


def _backup_if_missing(path: str) -> None:
    """
    若 <path>.trbak 不存在，複製 path 成 .trbak（保住第一次部署前的原始版本）。
    若 .trbak 已存在則不覆蓋，避免把最初的原始備份洗掉。
    僅在 path 本身存在時才動作（找不到來源檔就略過，交由後續流程處理錯誤）。
    """
    trbak = path + _TRBAK_SUFFIX
    if os.path.isfile(trbak):
        return
    if os.path.isfile(path):
        shutil.copyfile(path, trbak)


def deploy_mv_adapter(www_dir: str, port: int, maps: list[dict],
                      bridge_src: str, offline_dict: dict | None = None) -> str:
    """
    部署 MV adapter 到遊戲資料夾。
    流程：複製 bridge → （離線模式）寫整份字典檔 → 寫 boot 檔 → 在 plugins.js 末端註冊
         → 修改 index.html 引入 dict_data／boot。
    可重入：重複呼叫不會重複註冊 plugin。

    offline_dict：離線字典模式用，傳入整份 {原文:譯文} dict 時，會多寫一個
    js/translator_dict_data.js 檔，內容為 window.$translatorDict = <該 dict>；
    傳 None（預設）則不寫此檔，維持既有 DeepL 線上模式行為不變。
    """
    js_dir = os.path.join(www_dir, "js")
    plugins_dir = os.path.join(js_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    # 1) 複製 bridge 到目標位置
    dst = os.path.join(plugins_dir, _PLUGIN_NAME + ".js")
    shutil.copyfile(bridge_src, dst)

    # 1.5) 離線整字典模式：寫整份字典檔，供 bridge 開機時直接讀取 window.$translatorDict
    dict_data_path = os.path.join(js_dir, "translator_dict_data.js")
    if offline_dict is not None:
        with open(dict_data_path, "w", encoding="utf-8") as f:
            f.write("window.$translatorDict = %s;\n"
                    % json.dumps(offline_dict, ensure_ascii=False))

    # 2) 寫 boot 檔（設定 port 與地圖資料）
    boot_path = os.path.join(js_dir, "translator_boot.js")
    with open(boot_path, "w", encoding="utf-8") as f:
        f.write("window.$TRANSLATOR_PORT = %d;\n" % port)
        f.write("window.$translatorMaps = %s;\n"
                % json.dumps(maps, ensure_ascii=False))

    # 3) 於 plugins.js 末端註冊該 plugin（可重入：檢查是否已註冊，不重複註冊）
    plugins_js = os.path.join(js_dir, "plugins.js")
    # 修改前先備份原始檔（僅第一次部署會真的複製，之後保留最初版本）
    _backup_if_missing(plugins_js)
    text = open(plugins_js, encoding="utf-8").read()
    if _PLUGIN_NAME not in text:
        # 構造新的 plugin entry（JSON 格式）
        entry = '{"name":"%s","status":true,"description":"","parameters":{}}' % _PLUGIN_NAME
        # 找到陣列末端的 ]，在其前插入新 entry
        idx = text.rstrip().rfind("]")
        head = text[:idx].rstrip()
        # 如果陣列不為空（head 不以 [ 結尾），加逗號與換行
        sep = "" if head.endswith("[") else ",\n"
        text = head + sep + entry + "\n" + text[idx:]
        with open(plugins_js, "w", encoding="utf-8") as f:
            f.write(text)

    # 4) 確保 index.html 於載入 plugins.js 前引入 dict_data（若有）與 boot
    #    兩個 <script> 各自獨立判斷、獨立注入，避免其中一個已存在時，
    #    連帶把另一個也可重入判斷（可重入：已存在的 script 不重複注入）。
    #    例如：使用者先前已部署過線上模式（boot 已存在），這次改用離線模式，
    #    此時應只補注入 dict_data，而不是因為 boot 已存在就整段跳過。
    index = os.path.join(www_dir, "index.html")
    # 修改前先備份原始檔（僅第一次部署會真的複製，之後保留最初版本）
    _backup_if_missing(index)
    html = open(index, encoding="utf-8").read()

    tag = ""
    if offline_dict is not None and "translator_dict_data.js" not in html:
        tag += '<script type="text/javascript" src="js/translator_dict_data.js"></script>\n'
    if "translator_boot.js" not in html:
        tag += '<script type="text/javascript" src="js/translator_boot.js"></script>\n'

    if tag:
        # 只有在「確實需要注入」時，才要求 plugins.js 載入點必須存在；
        # 若兩者皆已存在（tag 為空字串），即使找不到載入點也不應 raise。
        html, n = re.subn(r'(<script[^>]*src=["\']js/plugins\.js["\'][^>]*>)',
                          tag + r"\1", html, count=1)
        if n == 0:
            raise RuntimeError(
                "無法在 index.html 找到 js/plugins.js 的載入點，script 未能注入")
        with open(index, "w", encoding="utf-8") as f:
            f.write(html)
    return dst


def _restore_one_file(path: str, label: str) -> None:
    """
    還原單一檔案：若 <path>.trbak 存在 → 複製回 path，然後刪除該 .trbak；
    若不存在 → 印繁中警告並略過。全程容錯，不拋例外，讓呼叫端可以繼續處理下一步。
    """
    trbak = path + _TRBAK_SUFFIX
    if not os.path.isfile(trbak):
        print(f"[警告] 找不到 {label} 備份，略過")
        return
    try:
        shutil.copyfile(trbak, path)
        os.remove(trbak)
        print(f"已還原 {label}")
    except OSError as e:
        print(f"[警告] 還原 {label} 失敗：{e}")


def _remove_if_exists(path: str, label: str) -> None:
    """
    刪除我方新增的檔案（存在才刪）。容錯：刪除失敗只印警告，不中斷整體還原流程。
    """
    if not os.path.isfile(path):
        print(f"[提示] {label} 不存在，略過刪除")
        return
    try:
        os.remove(path)
        print(f"已刪除 {label}")
    except OSError as e:
        print(f"[警告] 刪除 {label} 失敗：{e}")


def restore_mv_adapter(www_dir: str) -> None:
    """
    還原 MV adapter：把 deploy_mv_adapter 對遊戲檔案的修改復原成部署前的原始狀態。

    流程（全程容錯，任一步驟失敗只印警告訊息，不會讓整個還原中止到一半而不提示）：
    1) plugins.js：若有 .trbak → 複製回去、刪除 .trbak；沒有則印警告略過。
    2) index.html：同上，用 index.html.trbak。
    3) 刪除我方新增的三個檔：js/plugins/ZZ_Translator_Bridge.js、
       js/translator_boot.js、js/translator_dict_data.js（離線字典模式才會產生）。
    """
    js_dir = os.path.join(www_dir, "js")

    plugins_js = os.path.join(js_dir, "plugins.js")
    _restore_one_file(plugins_js, "plugins.js")

    index = os.path.join(www_dir, "index.html")
    _restore_one_file(index, "index.html")

    bridge = os.path.join(js_dir, "plugins", _PLUGIN_NAME + ".js")
    _remove_if_exists(bridge, "ZZ_Translator_Bridge.js")

    boot = os.path.join(js_dir, "translator_boot.js")
    _remove_if_exists(boot, "translator_boot.js")

    dict_data = os.path.join(js_dir, "translator_dict_data.js")
    _remove_if_exists(dict_data, "translator_dict_data.js")


def launch_game(exe_path: str) -> subprocess.Popen:
    """
    直接以遊戲 exe 啟動（不經 inject.exe）。
    設置 cwd 為遊戲資料夾，以便遊戲能正確載入相對路徑的資源。
    """
    return subprocess.Popen([exe_path], cwd=os.path.dirname(os.path.abspath(exe_path)))
