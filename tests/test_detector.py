import os
from core.detector import detect

def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").close()

def test_detects_mv_with_www(tmp_path):
    # 驗證有 www/js/rpg_core.js 時判定為 MV 且 www_dir 和 js_dir 正確
    game = tmp_path / "game"
    _touch(str(game / "www" / "js" / "rpg_core.js"))
    _touch(str(game / "Game.exe"))
    d = detect(str(game / "Game.exe"))
    assert d.engine == "mv"
    assert d.www_dir == str(game / "www")
    assert d.js_dir == str(game / "www" / "js")

def test_detects_mz_at_root(tmp_path):
    # 驗證有根目錄 js/rmmz_core.js 時判定為 MZ
    game = tmp_path / "game"
    _touch(str(game / "js" / "rmmz_core.js"))
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "mz"

def test_detects_unity(tmp_path):
    # 驗證有 UnityPlayer.dll 時判定為 Unity
    game = tmp_path / "game"
    _touch(str(game / "UnityPlayer.dll"))
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "unity"

def test_unknown(tmp_path):
    # 驗證無引擎標誌時判定為 unknown
    game = tmp_path / "game"
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "unknown"
