"""
TyranoScript（Electron）遊戲的 app.asar 解包工具。

asar 檔案格式（已實機查證，欄位如下，勿臆測）：
- header_size = struct.unpack('<I', d[4:8])[0]
- json_len = struct.unpack('<I', d[12:16])[0]
- header = json.loads(d[16:16+json_len].decode('utf-8'))
  （巢狀 {"files": {name: {...}}}，檔案節點有 "size" 與 "offset"(字串)，目錄節點有 "files"）
- 檔案內容基準 base = 8 + header_size
- 某檔內容 = d[base+int(offset) : base+int(offset)+size]
"""
import json
import os
import struct


def read_asar_header(path: str) -> tuple[dict, int, bytes]:
    """
    讀取 asar 檔案，解析出 header（巢狀檔案樹）、base（內容基準位移）與原始位元組。

    參數：
    - path: asar 檔案的路徑

    回傳：
    - (header, base, data)
    """
    with open(path, "rb") as f:
        data = f.read()

    header_size = struct.unpack("<I", data[4:8])[0]
    json_len = struct.unpack("<I", data[12:16])[0]
    header = json.loads(data[16:16 + json_len].decode("utf-8"))
    base = 8 + header_size
    return header, base, data


def iter_files(header: dict) -> list[tuple[str, int, str]]:
    """
    攤平 asar header 的巢狀檔案樹，回傳所有檔案節點。

    參數：
    - header: read_asar_header 回傳的巢狀 dict

    回傳：
    - [(rel_path, size, offset), ...]，rel_path 以 "/" 分隔（不含開頭斜線）
    """
    result: list[tuple[str, int, str]] = []

    def walk(node: dict, prefix: str) -> None:
        for name, sub in node.get("files", {}).items():
            rel_path = f"{prefix}/{name}" if prefix else name
            if "files" in sub:
                walk(sub, rel_path)
            else:
                result.append((rel_path, sub["size"], sub["offset"]))

    walk(header, "")
    return result


def extract_asar(asar_path: str, out_dir: str) -> int:
    """
    把 asar 內所有檔案解到 out_dir（依相對路徑自動建立子目錄）。

    參數：
    - asar_path: asar 檔案路徑
    - out_dir: 輸出目錄

    回傳：
    - 解出的檔案數
    """
    header, base, data = read_asar_header(asar_path)
    count = 0
    for rel_path, size, offset in iter_files(header):
        content = data[base + int(offset): base + int(offset) + size]
        out_path = os.path.join(out_dir, *rel_path.split("/"))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(content)
        count += 1
    return count
