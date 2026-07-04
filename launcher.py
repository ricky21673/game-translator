import json
import os
import re
import shutil
import subprocess

_PLUGIN_NAME = "ZZ_Translator_Bridge"


def deploy_mv_adapter(www_dir: str, port: int, maps: list[dict],
                      bridge_src: str) -> str:
    """
    部署 MV adapter 到遊戲資料夾。
    流程：複製 bridge → 寫 boot 檔 → 在 plugins.js 末端註冊 → 修改 index.html 引入 boot。
    可重入：重複呼叫不會重複註冊 plugin。
    """
    js_dir = os.path.join(www_dir, "js")
    plugins_dir = os.path.join(js_dir, "plugins")
    os.makedirs(plugins_dir, exist_ok=True)

    # 1) 複製 bridge 到目標位置
    dst = os.path.join(plugins_dir, _PLUGIN_NAME + ".js")
    shutil.copyfile(bridge_src, dst)

    # 2) 寫 boot 檔（設定 port 與地圖資料）
    boot_path = os.path.join(js_dir, "translator_boot.js")
    with open(boot_path, "w", encoding="utf-8") as f:
        f.write("window.$TRANSLATOR_PORT = %d;\n" % port)
        f.write("window.$translatorMaps = %s;\n"
                % json.dumps(maps, ensure_ascii=False))

    # 3) 於 plugins.js 末端註冊該 plugin（可重入：檢查是否已註冊，不重複註冊）
    plugins_js = os.path.join(js_dir, "plugins.js")
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

    # 4) 確保 index.html 於載入 plugins.js 前引入 boot（可重入：檢查是否已引入）
    index = os.path.join(www_dir, "index.html")
    html = open(index, encoding="utf-8").read()
    if "translator_boot.js" not in html:
        # 在 plugins.js 的 script tag 前插入 boot script
        tag = '<script type="text/javascript" src="js/translator_boot.js"></script>\n'
        html = re.sub(r'(<script[^>]*src=["\']js/plugins\.js["\'][^>]*>)',
                      tag + r"\1", html, count=1)
        with open(index, "w", encoding="utf-8") as f:
            f.write(html)
    return dst


def launch_game(exe_path: str) -> subprocess.Popen:
    """
    直接以遊戲 exe 啟動（不經 inject.exe）。
    設置 cwd 為遊戲資料夾，以便遊戲能正確載入相對路徑的資源。
    """
    return subprocess.Popen([exe_path], cwd=os.path.dirname(os.path.abspath(exe_path)))
