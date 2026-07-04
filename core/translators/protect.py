import re

from .base import Translator

# 比對 RPG Maker 控制碼：反斜線 + 字母，後面可帶 [ ... ]。例：\FS[28]、\SE[0]、\|、\.
_CONTROL_RE = re.compile(r"\\(?:[A-Za-z]+(?:\[[^\]]*\])?|[|.^!<>$])")

# placeholder 用私有區字元包住序號，模型幾乎不會動到它，也不含反斜線/日文。
_PH_L = ""
_PH_R = ""


def _mask(s: str):
    """把控制碼換成 placeholder，回傳 (masked, tokens)；tokens[i] 為第 i 個控制碼原字串。"""
    tokens = []

    def repl(m):
        tokens.append(m.group(0))
        return "%s%d%s" % (_PH_L, len(tokens) - 1, _PH_R)

    return _CONTROL_RE.sub(repl, s), tokens


def _restore(s: str, tokens) -> str:
    """把 placeholder 還原成控制碼；找不到的 placeholder（模型弄丟）就略過。"""
    def repl(m):
        idx = int(m.group(1))
        return tokens[idx] if 0 <= idx < len(tokens) else ""
    return re.sub(_PH_L + r"(\d+)" + _PH_R, repl, s)


class ControlCodeTranslator(Translator):
    """裝飾器：包住任一翻譯引擎，送翻前遮罩控制碼、翻完還原。keying 不受影響
    （Pipeline 仍以原字串為 key）。"""

    def __init__(self, inner: Translator):
        self.inner = inner

    def translate(self, texts, target_lang, source_lang=None):
        masked, token_lists = [], []
        for t in texts:
            m, toks = _mask(t)
            masked.append(m)
            token_lists.append(toks)
        out = self.inner.translate(masked, target_lang, source_lang)
        return [_restore(o, toks) for o, toks in zip(out, token_lists)]
