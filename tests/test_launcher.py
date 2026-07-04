import os
import pytest
from launcher import deploy_mv_adapter, restore_mv_adapter

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

def test_deploy_appends_to_nonempty_plugins_with_brackets(tmp_path):
    # 模擬真實 RPG Maker MV 的 plugins.js：非空陣列，且既有 entry 的字串參數內含 ] 字元，
    # 驗證定位邏輯不會被 entry 內部的 ] 誤導、我方 plugin 仍被正確插入為陣列最後一筆
    www = tmp_path / "www"; js = www / "js"; js.mkdir(parents=True)
    # 既有兩個 plugin，且參數字串內含 ] 字元（模擬真實 MV）
    js.joinpath("plugins.js").write_text(
        'var $plugins =\n[\n'
        '{"name":"Existing_A","status":true,"description":"用 [Tab] 切換","parameters":{"list":"[\\"a\\"]"}},\n'
        '{"name":"Existing_B","status":true,"description":"","parameters":{}}\n'
        '];\n', encoding="utf-8")
    www.joinpath("index.html").write_text(
        "<html><body><script type='text/javascript' src='js/plugins.js'></script></body></html>",
        encoding="utf-8")
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    from launcher import deploy_mv_adapter
    deploy_mv_adapter(str(www), 999, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))
    text = js.joinpath("plugins.js").read_text(encoding="utf-8")
    # 我方 plugin 必須被加入，且是陣列最後一個 entry（在 Existing_B 之後、] 之前）
    assert text.count("ZZ_Translator_Bridge") == 1
    assert text.index("Existing_B") < text.index("ZZ_Translator_Bridge")
    assert text.index("ZZ_Translator_Bridge") < text.rindex("]")
    # 既有 entry 未被破壞
    assert "Existing_A" in text and "Existing_B" in text
    # 結構仍以 ]; 收尾
    assert text.rstrip().endswith("];")

def test_deploy_raises_when_index_html_has_no_plugins_js_load_point(tmp_path):
    # index.html 內沒有 js/plugins.js 的 script tag（例如只有別的 script），
    # 找不到插入點時應明確 raise，而不是靜默 count=0、boot 沒被插入
    www = tmp_path / "www"; js = www / "js"; js.mkdir(parents=True)
    js.joinpath("plugins.js").write_text("var $plugins =\n[\n];\n", encoding="utf-8")
    www.joinpath("index.html").write_text(
        "<html><body><script type='text/javascript' src='js/other.js'></script></body></html>",
        encoding="utf-8")
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    with pytest.raises(RuntimeError):
        deploy_mv_adapter(str(www), 12345, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))


# ---------------------------------------------------------------------------
# 自動備份（.trbak）相關測試
# ---------------------------------------------------------------------------

def test_deploy_creates_trbak_backups_with_original_content(tmp_path):
    # 部署後應在 plugins.js/index.html 旁各自留下 .trbak，內容等於部署「前」的原始內容
    www = _mk_mv(tmp_path)
    plugins_path = os.path.join(www, "js", "plugins.js")
    index_path = os.path.join(www, "index.html")
    original_plugins = open(plugins_path, encoding="utf-8").read()
    original_index = open(index_path, encoding="utf-8").read()

    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 12345, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))

    plugins_trbak = plugins_path + ".trbak"
    index_trbak = index_path + ".trbak"
    assert os.path.isfile(plugins_trbak)
    assert os.path.isfile(index_trbak)
    assert open(plugins_trbak, encoding="utf-8").read() == original_plugins
    assert open(index_trbak, encoding="utf-8").read() == original_index


def test_deploy_twice_keeps_original_trbak_content(tmp_path):
    # 重複部署兩次：.trbak 仍必須是「最初」的原始內容，不可被第二次已修改版覆蓋
    www = _mk_mv(tmp_path)
    plugins_path = os.path.join(www, "js", "plugins.js")
    index_path = os.path.join(www, "index.html")
    original_plugins = open(plugins_path, encoding="utf-8").read()
    original_index = open(index_path, encoding="utf-8").read()

    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    b = str(src / "ZZ_Translator_Bridge.js")
    deploy_mv_adapter(www, 1, maps=[], bridge_src=b)
    deploy_mv_adapter(www, 1, maps=[], bridge_src=b)

    plugins_trbak = plugins_path + ".trbak"
    index_trbak = index_path + ".trbak"
    assert open(plugins_trbak, encoding="utf-8").read() == original_plugins
    assert open(index_trbak, encoding="utf-8").read() == original_index


# ---------------------------------------------------------------------------
# restore_mv_adapter 還原相關測試
# ---------------------------------------------------------------------------

def test_restore_after_deploy_reverts_files_and_cleans_up(tmp_path):
    # deploy 後呼叫 restore：plugins.js/index.html 完全回到最初原始內容、
    # 我方新增的兩個檔（bridge、boot）被刪除、.trbak 也被清掉
    www = _mk_mv(tmp_path)
    plugins_path = os.path.join(www, "js", "plugins.js")
    index_path = os.path.join(www, "index.html")
    original_plugins = open(plugins_path, encoding="utf-8").read()
    original_index = open(index_path, encoding="utf-8").read()

    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 12345, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))

    restore_mv_adapter(www)

    assert open(plugins_path, encoding="utf-8").read() == original_plugins
    assert open(index_path, encoding="utf-8").read() == original_index
    assert not os.path.isfile(os.path.join(www, "js", "plugins", "ZZ_Translator_Bridge.js"))
    assert not os.path.isfile(os.path.join(www, "js", "translator_boot.js"))
    assert not os.path.isfile(plugins_path + ".trbak")
    assert not os.path.isfile(index_path + ".trbak")


def test_restore_without_prior_deploy_does_not_raise(tmp_path):
    # 從未部署過（無 .trbak）的 www 呼叫 restore 應優雅略過，不拋例外
    www = _mk_mv(tmp_path)
    restore_mv_adapter(www)  # 不應拋例外


# ---------------------------------------------------------------------------
# offline_dict（整份字典嵌入）相關測試
# ---------------------------------------------------------------------------

def test_deploy_with_offline_dict_writes_dict_data_file(tmp_path):
    # 傳入 offline_dict 時，應多寫 js/translator_dict_data.js，內容含該字典資料
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    offline_dict = {"はい": "是", "いいえ": "否"}
    deploy_mv_adapter(www, 1, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"),
                       offline_dict=offline_dict)
    dict_data_path = os.path.join(www, "js", "translator_dict_data.js")
    assert os.path.isfile(dict_data_path)
    content = open(dict_data_path, encoding="utf-8").read()
    assert "window.$translatorDict" in content
    assert "はい" in content and "是" in content
    assert "いいえ" in content and "否" in content


def test_deploy_with_offline_dict_orders_dict_data_before_plugins_js(tmp_path):
    # index.html 中 translator_dict_data.js 與 translator_boot.js 都須排在 plugins.js 之前
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 1, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"),
                       offline_dict={"はい": "是"})
    html = open(os.path.join(www, "index.html"), encoding="utf-8").read()
    assert html.index("translator_dict_data.js") < html.index("plugins.js")
    assert html.index("translator_boot.js") < html.index("plugins.js")


def test_deploy_without_offline_dict_does_not_write_dict_data_file(tmp_path):
    # 未傳 offline_dict（None，預設）時，不應產生 translator_dict_data.js，維持既有行為
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 1, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"))
    dict_data_path = os.path.join(www, "js", "translator_dict_data.js")
    assert not os.path.isfile(dict_data_path)
    html = open(os.path.join(www, "index.html"), encoding="utf-8").read()
    assert "translator_dict_data.js" not in html


def test_deploy_adds_dict_data_when_boot_already_present_but_dict_missing(tmp_path):
    # 重現真實情境：使用者先前已部署過線上模式（index.html 已含 translator_boot.js，
    # 但尚未含 translator_dict_data.js），這次改用離線字典模式重新部署。
    # 預期：dict_data 的 <script> 必須被「補注入」，且排在 plugins.js 之前；
    # boot 已存在則不應被重複注入。
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    bridge_src = str(src / "ZZ_Translator_Bridge.js")

    # 先以線上模式（無 offline_dict）部署一次，讓 index.html 已含 translator_boot.js
    deploy_mv_adapter(www, 1, maps=[], bridge_src=bridge_src)
    index_path = os.path.join(www, "index.html")
    html_before = open(index_path, encoding="utf-8").read()
    assert "translator_boot.js" in html_before
    assert "translator_dict_data.js" not in html_before

    # 再以離線字典模式重新部署，模擬使用者切換到離線模式
    deploy_mv_adapter(www, 1, maps=[], bridge_src=bridge_src,
                       offline_dict={"はい": "是"})

    html_after = open(index_path, encoding="utf-8").read()
    # dict_data 應被新增，且排在 plugins.js 之前
    assert html_after.count("translator_dict_data.js") == 1
    assert html_after.index("translator_dict_data.js") < html_after.index("plugins.js")
    # boot 不應被重複注入
    assert html_after.count("translator_boot.js") == 1


# ---------------------------------------------------------------------------
# MZ 支援：index.html 只有 js/main.js（無 js/plugins.js）時的注入點
# ---------------------------------------------------------------------------

def _mk_mz(tmp_path):
    # 建立一個簡易的 MZ 遊戲資料夾結構（無 www，index.html 只有 js/main.js，無 js/plugins.js）
    game = tmp_path / "game"
    js = game / "js"
    js.mkdir(parents=True)
    (js / "plugins.js").write_text("var $plugins =\n[\n];\n", encoding="utf-8")
    (game / "index.html").write_text(
        "<html><body>"
        "<script type='text/javascript' src='js/main.js'></script>"
        "</body></html>", encoding="utf-8")
    return str(game)


def test_deploy_mz_style_index_html_injects_before_main_js(tmp_path):
    # MZ 式 index.html：只有 js/main.js 的 <script>，沒有 js/plugins.js 的 <script>
    # （plugins 由 main.js 內部載入）。deploy 後應在 main.js 之前注入 translator_boot.js，
    # 離線模式下也應注入 translator_dict_data.js，且同樣排在 main.js 之前。
    game = _mk_mz(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(game, 54321, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"),
                       offline_dict={"はい": "是"})

    # plugins.js 仍照既有邏輯註冊（MZ 的 plugins.js 格式與 MV 相同）
    plugins = open(os.path.join(game, "js", "plugins.js"), encoding="utf-8").read()
    assert "ZZ_Translator_Bridge" in plugins

    html = open(os.path.join(game, "index.html"), encoding="utf-8").read()
    assert "main.js" in html
    assert html.index("translator_dict_data.js") < html.index("main.js")
    assert html.index("translator_boot.js") < html.index("main.js")


def test_restore_after_offline_deploy_removes_dict_data_file(tmp_path):
    # 離線模式部署後呼叫 restore：translator_dict_data.js 檔案應被刪除
    www = _mk_mv(tmp_path)
    src = tmp_path / "src"; src.mkdir()
    (src / "ZZ_Translator_Bridge.js").write_text("// bridge", encoding="utf-8")
    deploy_mv_adapter(www, 1, maps=[], bridge_src=str(src / "ZZ_Translator_Bridge.js"),
                       offline_dict={"はい": "是"})
    dict_data_path = os.path.join(www, "js", "translator_dict_data.js")
    assert os.path.isfile(dict_data_path)

    restore_mv_adapter(www)

    assert not os.path.isfile(dict_data_path)
