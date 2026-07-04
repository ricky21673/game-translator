import json
import os
import struct

from adapters.tyrano.deploy import deploy_tyrano, restore_tyrano, translate_tree


def _pack_asar(files: dict[str, bytes]) -> bytes:
    # 與 tests/test_asar.py 相同的最小 asar 打包工具，供部署/還原測試共用
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


class StubPipeline:
    """
    測試專用假 pipeline：具 .translate(texts) 方法，依 mapping 查表，查不到則原樣回傳。
    """
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.calls: list[list[str]] = []

    def translate(self, texts: list[str], progress_cb=None) -> list[str]:
        # 需與真正的 Pipeline.translate 同介面（含句級進度回呼 progress_cb），
        # 這樣 translate_tree 透傳 segment_progress 時不會爆 TypeError。
        self.calls.append(list(texts))
        if progress_cb is not None:
            progress_cb(0, len(texts))
            progress_cb(len(texts), len(texts))
        return [self.mapping.get(t, t) for t in texts]


def _make_fake_game(tmp_path):
    """
    造一個含 resources/app.asar 的假遊戲夾，內含兩個 .ks 檔（帶日文段 + 標籤 + [p]）。
    """
    game_dir = tmp_path / "game"
    resources = game_dir / "resources"
    os.makedirs(str(resources))

    ks1 = "こんにちは、世界。[p]\n#name あいう\n"
    ks2 = "[chara_part name=\"alice\"]\nさようなら[l][r]\n"
    files = {
        "data/scenario/first.ks": ks1.encode("utf-8"),
        "data/scenario/second.ks": ks2.encode("utf-8"),
        "index.html": b"<html></html>",
    }
    asar_bytes = _pack_asar(files)
    (resources / "app.asar").write_bytes(asar_bytes)
    return str(game_dir)


def test_deploy_tyrano_extracts_translates_and_renames_asar(tmp_path):
    game_dir = _make_fake_game(tmp_path)
    mapping = {"こんにちは、世界。": "Hello, world."}
    pipeline = StubPipeline(mapping)

    stats = deploy_tyrano(game_dir, pipeline)

    resources = os.path.join(game_dir, "resources")
    app_dir = os.path.join(resources, "app")
    asar = os.path.join(resources, "app.asar")
    bak = os.path.join(resources, "app.asar.trbak")

    # resources/app/ 已解包出現
    assert os.path.isdir(app_dir)
    # 對應 .ks 內該段已翻譯
    first_ks = os.path.join(app_dir, "data", "scenario", "first.ks")
    with open(first_ks, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Hello, world.[p]" in content
    # app.asar 已被改名成 app.asar.trbak，原 asar 不在
    assert not os.path.isfile(asar)
    assert os.path.isfile(bak)

    # 統計數字合理：2 個 .ks 檔、"さようなら" 沒被翻到所以 translated 只算已翻的那段
    assert stats["ks_files"] == 2
    assert stats["segments"] >= 1
    assert stats["translated"] == 1


def test_deploy_tyrano_is_reentrant(tmp_path):
    # 已部署過（bak 已存在）時再呼叫一次，不應重複解包/改名，只重跑 translate_tree
    game_dir = _make_fake_game(tmp_path)
    pipeline1 = StubPipeline({"こんにちは、世界。": "Hello, world."})
    deploy_tyrano(game_dir, pipeline1)

    resources = os.path.join(game_dir, "resources")
    asar = os.path.join(resources, "app.asar")
    bak = os.path.join(resources, "app.asar.trbak")
    assert not os.path.isfile(asar)
    assert os.path.isfile(bak)

    # 第二次部署：補翻 "さようなら"
    pipeline2 = StubPipeline({"さようなら": "Goodbye"})
    stats2 = deploy_tyrano(game_dir, pipeline2)

    second_ks = os.path.join(resources, "app", "data", "scenario", "second.ks")
    with open(second_ks, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Goodbye[l][r]" in content
    # 仍然只有一份 bak，沒有被二次改名或產生其他 asar 檔
    assert not os.path.isfile(asar)
    assert os.path.isfile(bak)
    assert stats2["ks_files"] == 2


def test_restore_tyrano_renames_back_and_removes_app_dir(tmp_path):
    game_dir = _make_fake_game(tmp_path)
    pipeline = StubPipeline({"こんにちは、世界。": "Hello, world."})
    deploy_tyrano(game_dir, pipeline)

    resources = os.path.join(game_dir, "resources")
    app_dir = os.path.join(resources, "app")
    asar = os.path.join(resources, "app.asar")
    bak = os.path.join(resources, "app.asar.trbak")

    restore_tyrano(game_dir)

    # app.asar 回來、resources/app/ 被刪、.trbak 不在
    assert os.path.isfile(asar)
    assert not os.path.isdir(app_dir)
    assert not os.path.isfile(bak)


def test_restore_tyrano_without_prior_deploy_is_noop(tmp_path):
    # 從未部署過（無 bak）時呼叫 restore，應容錯不拋例外
    game_dir = _make_fake_game(tmp_path)
    restore_tyrano(game_dir)  # 不應拋例外

    resources = os.path.join(game_dir, "resources")
    asar = os.path.join(resources, "app.asar")
    assert os.path.isfile(asar)


def test_translate_tree_reports_progress_phases(tmp_path):
    # 驗證 progress callback 在 collect/translate/write 三階段都會被呼叫
    game_dir = _make_fake_game(tmp_path)
    resources = os.path.join(game_dir, "resources")
    app_dir = os.path.join(resources, "app")
    from core.asar import extract_asar
    extract_asar(os.path.join(resources, "app.asar"), app_dir)

    phases_seen: set[str] = set()

    def progress(done, total, phase):
        phases_seen.add(phase)

    pipeline = StubPipeline({"こんにちは、世界。": "Hello, world."})
    translate_tree(app_dir, pipeline, progress)

    assert {"collect", "translate", "write"} <= phases_seen
