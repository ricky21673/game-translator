"""
TyranoScript .ks 劇本檔的純文字抽取/回寫規則。

規則（已驗證命中 92%+，照此實作，勿臆測變更）：
- 逐行處理。行去頭尾空白後：
  - 空行、或開頭字元屬於 `[ # * ; @` -> 非文字行，原樣保留、不翻。
  - 開頭是 `//` -> 註解，不翻。
  - 不含日文假名/CJK（正則 `[぀-ヿ一-鿿]`）-> 不翻。
  - 其餘 = 可翻文字行。
- 「結尾等待標籤」= 行尾一串 `(\\[[^\\]]*\\])+\\s*$`（如 `[p]`、`[l][r]`）。
  翻譯時只把這串從尾端拆下、保留行內標籤（如句中的 `[n2]`）。
  送去翻的「核心」= 該行去掉結尾標籤後的內容。
  回寫 = 譯文 + 原本的結尾標籤（結尾標籤原封不動接回）。

資料陣列行（新增支援）：
- 有些遊戲文字（回想描述、選單/畫廊清單標題）以 JS 資料陣列形式存在 .ks，例如：
    `[11,"夢乃とふたりきりのときに…","上手くパイズリできるか…"]`
  = `[編號, "標題", "描述"]`。
- 判別式：行去頭尾空白後符合 `^\\s*\\[\\s*\\d`（`[` 後緊接數字）視為「資料陣列行」。
  這樣可與 tyrano 標籤行區隔——標籤行是 `[chara_part name="夢乃"]`（`[` 後接字母/標籤名），
  其引號內是角色識別字，翻了會壞遊戲，故標籤行維持「跳過、不碰」的既有行為。
- 抽取：對資料陣列行找出所有雙引號字串 `"([^"]*)"`，只把「內容含日文假名/CJK」的加入可翻清單。
- 回寫：只替換引號內的內容（mapping 有對應、非空、≠原文者），保留 `[編號,...]` 與引號結構與其餘部分。
- 限制：用簡單的 `"[^"]*"` 比對，不處理字串內含 `\\"` 跳脫引號的極端情況（實機罕見）。
"""
import re

# 非文字行判定：空行或開頭字元屬於 [ # * ; @
_NON_TEXT_PREFIXES = ("[", "#", "*", ";", "@")
# 含日文假名/CJK 字元才視為可翻文字
_JP_CJK_RE = re.compile(r"[぀-ヿ一-鿿]")
# 結尾等待標籤：一串連續的 [xxx] 直到行尾（可含尾隨空白）
_TRAILING_TAGS_RE = re.compile(r"((?:\[[^\]]*\])+)\s*$")
# 資料陣列行判別：行首（可含前導空白）為 `[` 後緊接數字，如 `[11,"...","..."]`
_DATA_ARRAY_RE = re.compile(r"^\s*\[\s*\d")
# 雙引號字串（簡單版，不處理 \" 跳脫）
_QUOTED_STR_RE = re.compile(r'"([^"]*)"')
# 標籤屬性白名單：只翻屬「玩家可見顯示文字」的屬性。刻意排除 name（識別字）、
# exp（JS 運算式）、jname/initial（存疑）、storage/target/graphic/cond/role… 等結構屬性。
_TEXT_ATTRS = {"text", "hint", "label", "label_ok", "label_cancel"}
# 標籤屬性比對：屬性名（字母/底線）= 雙引號值。簡單版，不處理值內 \" 跳脫。
_ATTR_RE = re.compile(r'([a-zA-Z_]+)="([^"]*)"')


def _is_translatable_line(stripped: str) -> bool:
    """
    判斷去頭尾空白後的行是否為可翻文字行。
    """
    if not stripped:
        return False
    if stripped[0] in _NON_TEXT_PREFIXES:
        return False
    if stripped.startswith("//"):
        return False
    if not _JP_CJK_RE.search(stripped):
        return False
    return True


def _is_data_array_line(stripped: str) -> bool:
    """
    判斷去頭尾空白後的行是否為「資料陣列行」。

    條件：行首 `[` 後緊接數字（`^\\s*\\[\\s*\\d`），例如 `[11,"標題","描述"]`。
    這可與 tyrano 標籤行（`[chara_part name="..."]`，`[` 後接字母）明確區隔。
    """
    return bool(_DATA_ARRAY_RE.match(stripped))


def _is_translatable_attr_value(attr: str, value: str) -> bool:
    """標籤屬性值是否為「該翻的日文顯示文字」：屬性在白名單、值非空、
    不以 & 開頭（變數運算式）、且含日文假名/CJK。"""
    return (attr.lower() in _TEXT_ATTRS and bool(value)
            and not value.startswith("&") and bool(_JP_CJK_RE.search(value)))


def _split_trailing_tags(stripped: str) -> tuple[str, str]:
    """
    把行尾的等待標籤串從尾端拆下。

    回傳：
    - (核心文字, 結尾標籤字串)；若無結尾標籤，結尾標籤字串為空字串。
    """
    m = _TRAILING_TAGS_RE.search(stripped)
    if not m:
        return stripped, ""
    core = stripped[:m.start()]
    trailing = stripped[m.start():]
    return core, trailing


def extract_segments(ks_text: str) -> list[str]:
    """
    從 .ks 純文字中抽出所有可翻核心字串（已去除結尾等待標籤）。

    參數：
    - ks_text: .ks 檔案的純文字內容

    回傳：
    - 依出現順序排列的可翻核心字串清單（可能重複）
    """
    segments: list[str] = []
    for line in ks_text.splitlines():
        stripped = line.strip()
        # 先處理資料陣列行（行首 `[` 接數字）：抽出引號內含日文的字串
        # 注意：資料陣列行的 stripped[0] 為 `[`，會被 _is_translatable_line 當非文字行，
        # 因此必須在純文字行判定之前先攔截。
        if _is_data_array_line(stripped):
            for content in _QUOTED_STR_RE.findall(stripped):
                if _JP_CJK_RE.search(content):
                    segments.append(content)
            continue
        # 標籤行（以 [ 開頭、非資料陣列行）：抽白名單屬性中的日文顯示文字。
        # 純文字行不以 [ 開頭，故互斥；資料陣列行已於上方攔截。
        if stripped.startswith("["):
            for attr, value in _ATTR_RE.findall(stripped):
                if _is_translatable_attr_value(attr, value):
                    segments.append(value)
            continue
        if not _is_translatable_line(stripped):
            continue
        core, _trailing = _split_trailing_tags(stripped)
        segments.append(core)
    return segments


def apply_translations(ks_text: str, mapping: dict[str, str]) -> str:
    """
    依 mapping（核心字串 -> 譯文）把 .ks 純文字中的可翻文字行換成譯文。

    參數：
    - ks_text: 原始 .ks 檔案純文字內容
    - mapping: 核心字串 -> 譯文的對應表

    回傳：
    - 回寫後的完整 .ks 文字。非文字行、換行結構原樣保留；
      mapping 中沒有對應、譯文為空字串、或譯文等於原文時，該行原樣保留。
    """
    # 保留原始換行方式：以 splitlines(keepends=True) 逐行處理，避免末尾換行遺失
    lines = ks_text.splitlines(keepends=True)
    out_lines: list[str] = []
    for line in lines:
        # 拆出行尾換行符號（\n / \r\n），處理時只動文字本體
        newline = ""
        body = line
        for nl in ("\r\n", "\n", "\r"):
            if line.endswith(nl):
                newline = nl
                body = line[:-len(nl)]
                break

        stripped = body.strip()

        # 資料陣列行（行首 `[` 接數字）：只替換引號內容，保留 [編號,...] 與引號結構。
        # 同樣須在純文字行判定之前處理（其開頭為 `[`）。
        if _is_data_array_line(stripped):

            def _replace_quoted(m: "re.Match[str]") -> str:
                content = m.group(1)
                translation = mapping.get(content)
                # 沒對應、空譯文、或譯文等於原文 -> 引號內容原樣不動
                if not translation or translation == content:
                    return m.group(0)
                return f'"{translation}"'

            new_body = _QUOTED_STR_RE.sub(_replace_quoted, body)
            out_lines.append(f"{new_body}{newline}")
            continue

        # 標籤行：只替換白名單屬性的日文顯示文字，其餘屬性/結構原樣保留。
        if stripped.startswith("["):

            def _replace_attr(m: "re.Match[str]") -> str:
                attr, value = m.group(1), m.group(2)
                if _is_translatable_attr_value(attr, value):
                    translation = mapping.get(value)
                    if translation and translation != value:
                        return f'{attr}="{translation}"'
                return m.group(0)

            new_body = _ATTR_RE.sub(_replace_attr, body)
            out_lines.append(f"{new_body}{newline}")
            continue

        if not _is_translatable_line(stripped):
            out_lines.append(line)
            continue

        core, trailing = _split_trailing_tags(stripped)
        translation = mapping.get(core)
        if not translation or translation == core:
            out_lines.append(line)
            continue

        # 保留原本前導/後綴空白的位置：以 strip 前後差異還原縮排
        leading_ws = body[:len(body) - len(body.lstrip())]
        trailing_ws = body[len(body.rstrip()):]
        out_lines.append(f"{leading_ws}{translation}{trailing}{trailing_ws}{newline}")

    return "".join(out_lines)
