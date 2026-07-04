import re

# 假名（U+3040–30FF）與常用漢字（U+4E00–9FFF）
_JP_RE = re.compile("[぀-ヿ一-鿿]")


def has_japanese(s) -> bool:
    return isinstance(s, str) and bool(_JP_RE.search(s))


def _extract_event_list(cmds, out):
    """處理單一事件指令陣列：連續 401 分組、405/102/402 個別處理。"""
    buf = []
    for cmd in cmds or []:
        code = cmd.get("code")
        params = cmd.get("parameters") or []
        if code == 401:
            buf.append(params[0] if params and isinstance(params[0], str) else "")
            continue
        if buf:
            out.append("\n".join(buf))
            buf = []
        if code == 405:
            if params and isinstance(params[0], str):
                out.append(params[0])
        elif code == 102 and params and isinstance(params[0], list):
            for choice in params[0]:
                if isinstance(choice, str):
                    out.append(choice)
        elif code == 402 and len(params) >= 2 and isinstance(params[1], str):
            out.append(params[1])
    if buf:
        out.append("\n".join(buf))


def _extract_events(events, out):
    for ev in events or []:
        if not ev:
            continue
        for pg in ev.get("pages") or []:
            _extract_event_list(pg.get("list"), out)


def _extract_map(obj, out):
    _extract_events(obj.get("events"), out)


def _extract_common_events(obj, out):
    for ce in obj or []:
        if ce:
            _extract_event_list(ce.get("list"), out)


def _extract_troops(obj, out):
    for tr in obj or []:
        if not tr:
            continue
        for pg in tr.get("pages") or []:
            _extract_event_list(pg.get("list"), out)


_DB_FIELDS = ("name", "nickname", "description", "profile",
              "message1", "message2", "message3", "message4")


def _extract_database(obj, out):
    for row in obj or []:
        if not isinstance(row, dict):
            continue
        for f in _DB_FIELDS:
            v = row.get(f)
            if isinstance(v, str):
                out.append(v)


def _extract_system(obj, out):
    out.append(obj.get("gameTitle", ""))
    terms = obj.get("terms") or {}
    for key in ("basic", "commands", "params"):
        for v in terms.get(key) or []:
            if isinstance(v, str):
                out.append(v)
    for v in (terms.get("messages") or {}).values():
        if isinstance(v, str):
            out.append(v)


def extract_strings(data_name: str, data_obj) -> list:
    """依 data 檔名分派抽取，回傳僅含日文的可翻字串（未去重，順序穩定）。"""
    out = []
    base = data_name.rsplit(".", 1)[0]
    if base.startswith("Map") and base != "MapInfos":
        _extract_map(data_obj, out)
    elif base == "CommonEvents":
        _extract_common_events(data_obj, out)
    elif base == "Troops":
        _extract_troops(data_obj, out)
    elif base == "System":
        _extract_system(data_obj, out)
    else:
        _extract_database(data_obj, out)
    return [s for s in out if has_japanese(s)]
