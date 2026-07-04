import os
from launcher import deploy_mv_adapter

def _mk_mv(tmp_path):
    # 建立一個簡易的 MV 遊戲資料夾結構（含 plugins.js 與 index.html）
    www = tmp_path / "www"
    js = www / "js"
    js.mkdir(parents=True)
    (js / "plugins.js").write_text("var $plugins =\n[\n];\n", encoding="utf-8")
    (www / "index.html").write_text(
        "<html><body>"
        "<script type='text/javascript' src='js/plugins.js'></script>"
        "</body></html>", encoding="utf-8")
    return str(www)

def test_deploy_copies_plugin_and_registers(tmp_path):
    # 測試 deploy_mv_adapter 能否複製 bridge、註冊到 plugins.js、寫 boot 檔、修改 index.html
    www = _mk_mv(tmp_path)
    # 準備來源 bridge
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 12345, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))
    # 檔案已複製
    assert os.path.isfile(os.path.join(www, "js", "plugins", "ZZ_Translator_Bridge.js"))
    # plugins.js 已註冊
    plugins = open(os.path.join(www, "js", "plugins.js"), encoding="utf-8").read()
    assert "ZZ_Translator_Bridge" in plugins
    # boot 檔含 port
    boot = open(os.path.join(www, "js", "translator_boot.js"), encoding="utf-8").read()
    assert "12345" in boot
    # index.html 於 plugins.js 前引入 boot
    html = open(os.path.join(www, "index.html"), encoding="utf-8").read()
    assert html.index("translator_boot.js") < html.index("plugins.js")

def test_deploy_is_reentrant(tmp_path):
    # 測試重複呼叫 deploy_mv_adapter 不會重複註冊 plugin
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    b = str(src / "ZZ_Translator_Bridge.js")
    deploy_mv_adapter(www, 1, maps=[], bridge_src=b)
    deploy_mv_adapter(www, 1, maps=[], bridge_src=b)
    plugins = open(os.path.join(www, "js", "plugins.js"), encoding="utf-8").read()
    assert plugins.count("ZZ_Translator_Bridge") == 1  # 不重複註冊
