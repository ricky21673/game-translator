import json
import os
import struct

from core.detector import detect

def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").close()


def _pack_asar(files: dict[str, bytes]) -> bytes:
    # 與 tests/test_asar.py 相同的最小 asar 打包工具，供 detector 的 tyrano 判定測試共用
    offset = 0
    root: dict = {"files": {}}
    contents: list[bytes] = []
    for rel_path, content in files.items():
        parts = rel_path.split("/")
        node = root
        for part in parts[:-1]:
            node = node["files"].setdefault(part, {"files": {}})
        node["files"][parts[-1]] = {"size": len(content), "offset": str(offset)}
        contents.append(content)
        offset += len(content)

    header_json = json.dumps(root).encode("utf-8")
    json_len = len(header_json)
    pad = (4 - (json_len % 4)) % 4
    padded_json = header_json + b"\x00" * pad
    payload_size = 4 + len(padded_json)
    header_size = 4 + payload_size
    outer_size = 4 + header_size

    buf = (
        struct.pack("<I", outer_size)
        + struct.pack("<I", header_size)
        + struct.pack("<I", payload_size)
        + struct.pack("<I", json_len)
        + padded_json
    )
    buf += b"".join(contents)
    return buf

def test_detects_mv_with_www(tmp_path):
    # 驗證有 www/js/rpg_core.js 時判定為 MV 且 www_dir 和 js_dir 正確
    game = tmp_path / "game"
    _touch(str(game / "www" / "js" / "rpg_core.js"))
    _touch(str(game / "Game.exe"))
    d = detect(str(game / "Game.exe"))
    assert d.engine == "mv"
    assert d.www_dir == str(game / "www")
    assert d.js_dir == str(game / "www" / "js")
    # web_dir 為含 index.html 與 js/ 的基準目錄，MV 時應等於 www_dir
    assert d.web_dir == str(game / "www")

def test_detects_mz_at_root(tmp_path):
    # 驗證有根目錄 js/rmmz_core.js 時判定為 MZ，且 web_dir 為遊戲根目錄（無 www）
    game = tmp_path / "game"
    _touch(str(game / "js" / "rmmz_core.js"))
    _touch(str(game / "Game.exe"))
    d = detect(str(game / "Game.exe"))
    assert d.engine == "mz"
    assert d.web_dir == str(game)

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


def test_detects_tyrano_via_electron_asar(tmp_path):
    # 驗證 resources/app.asar 內含 .ks 檔時判定為 tyrano（Electron 打包情境）
    game = tmp_path / "game"
    resources = game / "resources"
    os.makedirs(str(resources))
    files = {
        "data/scenario/first.ks": "第一話".encode("utf-8"),
        "index.html": b"<html></html>",
    }
    asar_bytes = _pack_asar(files)
    (resources / "app.asar").write_bytes(asar_bytes)
    _touch(str(game / "Game.exe"))

    d = detect(str(game / "Game.exe"))

    assert d.engine == "tyrano"
    assert d.game_dir == str(game)
    assert d.web_dir is None


def test_asar_without_ks_or_tyrano_not_detected_as_tyrano(tmp_path):
    # 驗證 app.asar 存在但內容與 .ks/tyrano 無關時，不誤判為 tyrano
    game = tmp_path / "game"
    resources = game / "resources"
    os.makedirs(str(resources))
    files = {"main.js": b"console.log('hi')"}
    asar_bytes = _pack_asar(files)
    (resources / "app.asar").write_bytes(asar_bytes)
    _touch(str(game / "Game.exe"))

    d = detect(str(game / "Game.exe"))

    assert d.engine == "unknown"


def test_corrupt_asar_does_not_crash_detect(tmp_path):
    # 驗證損毀/非法的 app.asar 讀取失敗時，不判為 tyrano 也不拋例外
    game = tmp_path / "game"
    resources = game / "resources"
    os.makedirs(str(resources))
    (resources / "app.asar").write_bytes(b"not a real asar file")
    _touch(str(game / "Game.exe"))

    d = detect(str(game / "Game.exe"))

    assert d.engine == "unknown"


def test_detects_tyrano_via_deployed_trbak_backup(tmp_path):
    # 驗證已被本工具部署過（app.asar 被改名為 app.asar.trbak）時判定為 tyrano
    game = tmp_path / "game"
    resources = game / "resources"
    os.makedirs(str(resources))
    # 部署後 app.asar 不存在，只留備份檔
    (resources / "app.asar.trbak").write_bytes(b"backup of original asar")
    _touch(str(game / "Game.exe"))

    d = detect(str(game / "Game.exe"))

    assert d.engine == "tyrano"
    assert d.game_dir == str(game)


def test_detects_tyrano_via_deployed_unpacked_app_dir(tmp_path):
    # 驗證已部署且解包成 resources/app/ 資料夾（內含 .ks，無 app.asar、無 .trbak）時判定為 tyrano
    game = tmp_path / "game"
    _touch(str(game / "resources" / "app" / "data" / "scenario" / "first.ks"))
    _touch(str(game / "Game.exe"))

    d = detect(str(game / "Game.exe"))

    assert d.engine == "tyrano"
    assert d.game_dir == str(game)


def test_empty_resources_dir_not_detected_as_tyrano(tmp_path):
    # 驗證只有空的 resources/ 資料夾、無任何 tyrano 跡象時，不誤判為 tyrano
    game = tmp_path / "game"
    os.makedirs(str(game / "resources"))
    _touch(str(game / "Game.exe"))

    d = detect(str(game / "Game.exe"))

    assert d.engine == "unknown"


import json as _json


def _make_mz(tmp_path, data_files):
    js = tmp_path / "js"
    js.mkdir()
    (js / "rmmz_core.js").write_text("// core", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()
    for name, content in data_files.items():
        (data / name).write_text(_json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return str(tmp_path / "Game.exe")


def test_detect_mz_plain_is_not_encrypted(tmp_path):
    from core.detector import detect
    exe = _make_mz(tmp_path, {"Map001.json": {"events": []}})
    d = detect(exe)
    assert d.engine == "mz"
    assert d.encrypted is False


def test_detect_mz_encrypted_flag(tmp_path):
    from core.detector import detect
    exe = _make_mz(tmp_path, {"Map001.json": {"uid": "x", "bid": "1.8.1", "data": "QUJD"}})
    d = detect(exe)
    assert d.engine == "mz"
    assert d.encrypted is True
