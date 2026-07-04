import os
from core.detector import detect

def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").close()

def test_detects_mv_with_www(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "www" / "js" / "rpg_core.js"))
    _touch(str(game / "Game.exe"))
    d = detect(str(game / "Game.exe"))
    assert d.engine == "mv"
    assert d.www_dir == str(game / "www")
    assert d.js_dir == str(game / "www" / "js")

def test_detects_mz_at_root(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "js" / "rmmz_core.js"))
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "mz"

def test_detects_unity(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "UnityPlayer.dll"))
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "unity"

def test_unknown(tmp_path):
    game = tmp_path / "game"
    _touch(str(game / "Game.exe"))
    assert detect(str(game / "Game.exe")).engine == "unknown"
