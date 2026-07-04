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
"""
import re

# 非文字行判定：空行或開頭字元屬於 [ # * ; @
_NON_TEXT_PREFIXES = ("[", "#", "*", ";", "@")
# 含日文假名/CJK 字元才視為可翻文字
_JP_CJK_RE = re.compile(r"[぀-ヿ一-鿿]")
# 結尾等待標籤：一串連續的 [xxx] 直到行尾（可含尾隨空白）
_TRAILING_TAGS_RE = re.compile(r"((?:\[[^\]]*\])+)\s*$")


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
