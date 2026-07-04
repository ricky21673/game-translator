import json
import os
import struct

from core.asar import read_asar_header, iter_files, extract_asar


def _pack_asar(files: dict[str, bytes]) -> bytes:
    """
    測試專用工具函式：把 {rel_path: bytes} 打包成 asar 位元組。
    格式與 core.asar.read_asar_header 的解析方式對應（Chromium pickle 巢狀框架）：
    - offset 0-3: outer_size（後續內容長度）
    - offset 4-7: header_size（= 4 + payload_size）
    - offset 8-11: payload_size（= 4 + padded_json 長度）
    - offset 12-15: json_len（JSON 字串實際長度，不含 padding）
    - offset 16..16+json_len: header JSON（padding 至 4 的倍數）
    - base = 8 + header_size 之後接各檔案內容，依 offset 累加排列
    """
    offset = 0
    root: dict = {"files": {}}
    contents: list[bytes] = []
    # 依 rel_path 的 "/" 逐層建立巢狀目錄樹
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


def test_read_asar_header_parses_header_base_and_data(tmp_path):
    # 驗證 read_asar_header 能正確解析 header / base / data 三者
    files = {"a.txt": b"hello"}
    asar_bytes = _pack_asar(files)
    asar_path = tmp_path / "game.asar"
    asar_path.write_bytes(asar_bytes)

    header, base, data = read_asar_header(str(asar_path))

    assert "a.txt" in header["files"]
    assert header["files"]["a.txt"]["size"] == 5
    assert data == asar_bytes
    content = data[base + int(header["files"]["a.txt"]["offset"]): base + int(header["files"]["a.txt"]["offset"]) + 5]
    assert content == b"hello"


def test_iter_files_flattens_nested_tree(tmp_path):
    # 驗證 iter_files 能攤平多層目錄樹，且 rel_path 以 "/" 分隔
    files = {
        "root.txt": b"root",
        "data/scenario/first.ks": "第一話".encode("utf-8"),
        "data/scenario/sub/second.ks": "第二話".encode("utf-8"),
    }
    asar_bytes = _pack_asar(files)
    asar_path = tmp_path / "game.asar"
    asar_path.write_bytes(asar_bytes)

    header, _, _ = read_asar_header(str(asar_path))
    result = {rel: (size, offset) for rel, size, offset in iter_files(header)}

    assert set(result.keys()) == set(files.keys())
    for rel, content in files.items():
        size, _offset = result[rel]
        assert size == len(content)


def test_extract_asar_round_trip_multi_dir_and_utf8(tmp_path):
    # round-trip：打包 -> 寫成暫存 .asar -> extract_asar 解出 -> 內容與數量一致
    files = {
        "index.html": b"<html></html>",
        "data/scenario/first.ks": "（日本語テキスト）[p]".encode("utf-8"),
        "data/scenario/sub/second.ks": "#name あいう".encode("utf-8"),
        "data/image/logo.png": bytes([0x89, 0x50, 0x4e, 0x47, 0x00, 0x01, 0x02, 0x03]),
    }
    asar_bytes = _pack_asar(files)
    asar_path = tmp_path / "app.asar"
    asar_path.write_bytes(asar_bytes)
    out_dir = tmp_path / "extracted"

    count = extract_asar(str(asar_path), str(out_dir))

    assert count == len(files)
    for rel_path, expected in files.items():
        out_path = out_dir / rel_path.replace("/", os.sep)
        assert out_path.is_file()
        assert out_path.read_bytes() == expected
