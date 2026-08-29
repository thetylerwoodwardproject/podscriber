from app.services.video_editor_shared import loudnorm_filter, waveform_colorchannelmixer_expr


def test_waveform_colorchannelmixer_expr_recolors_pure_black():
    expr = waveform_colorchannelmixer_expr("#000000")
    assert "rr=0.000000" in expr
    assert "gr=0.000000" in expr
    assert "br=0.000000" in expr
    assert "aa=1" in expr


def test_waveform_colorchannelmixer_expr_recolors_accent_color():
    expr = waveform_colorchannelmixer_expr("#e2572c")
    assert "rr=0.886275" in expr
    assert "gr=0.341176" in expr
    assert "br=0.172549" in expr


def test_waveform_colorchannelmixer_expr_defaults_when_missing():
    assert waveform_colorchannelmixer_expr(None) == waveform_colorchannelmixer_expr("#e2572c")
    assert waveform_colorchannelmixer_expr("") == waveform_colorchannelmixer_expr("#e2572c")


def test_waveform_colorchannelmixer_expr_falls_back_on_bad_length():
    assert waveform_colorchannelmixer_expr("#abc") == waveform_colorchannelmixer_expr("#e2572c")


def test_waveform_colorchannelmixer_expr_ignores_alpha_suffix():
    assert waveform_colorchannelmixer_expr("#000000ff") == waveform_colorchannelmixer_expr("#000000")


def test_loudnorm_filter_includes_measured_stats():
    stats = {
        "input_i": "-23.5", "input_tp": "-2.3",
        "input_lra": "7.8", "input_thresh": "-33.6",
        "target_offset": "0.4",
    }
    expr = loudnorm_filter(stats)
    assert "I=-14.0" in expr
    assert "measured_I=-23.5" in expr
    assert "measured_TP=-2.3" in expr
    assert "measured_LRA=7.8" in expr
    assert "measured_thresh=-33.6" in expr
    assert "offset=0.4" in expr
