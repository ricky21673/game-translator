from core.translators.protect import ControlCodeTranslator, _mask, _restore


class _FakeInner:
    """把送進來的（已遮罩）文字原樣回傳，模擬「保留 placeholder」的理想模型。"""
    def __init__(self):
        self.seen = None

    def translate(self, texts, target_lang, source_lang=None):
        self.seen = list(texts)
        return list(texts)


def test_mask_restore_round_trip():
    s = "\\SE[0]\\W[1,0]\\FS[28]んっ…\\FS[24]んんっ…♥"
    masked, tokens = _mask(s)
    assert "\\FS" not in masked          # 控制碼已被遮罩
    assert "んっ" in masked              # 日文保留
    assert _restore(masked, tokens) == s


def test_wrapper_masks_before_inner_and_restores_after():
    inner = _FakeInner()
    w = ControlCodeTranslator(inner)
    out = w.translate(["\\FS[28]あ", "\\SE[0]い"], "ZH")
    # 送進 inner 的是遮罩後、不含反斜線控制碼的字串
    assert all("\\FS" not in t and "\\SE" not in t for t in inner.seen)
    # 還原後控制碼回來了
    assert out == ["\\FS[28]あ", "\\SE[0]い"]


def test_restore_is_best_effort_when_placeholder_dropped():
    # 模型把 placeholder 弄丟時，不應炸掉，回傳去掉該碼的結果
    masked, tokens = _mask("\\FS[28]あ")
    assert _restore("あ", tokens) == "あ"


def test_placeholder_not_confused_with_digits():
    # 控制碼旁邊的日文含一般數字「3」，還原時不可把它誤當 placeholder
    s = "\\FS[28]残り3個"
    masked, tokens = _mask(s)
    # 遮罩後仍看得到那個一般數字 3（它不是控制碼的一部分）
    assert "3" in masked
    # 還原必須完整還原原字串（若 placeholder 被寫成空字串，這裡會壞掉）
    assert _restore(masked, tokens) == s
