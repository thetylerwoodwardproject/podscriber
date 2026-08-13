from app.services.llm import base


def test_clamp_title_leaves_short_titles_unchanged():
    assert base._clamp_title("Short Title") == "Short Title"


def test_clamp_title_enforces_max_length():
    long_title = "This is a very long podcast episode title that definitely exceeds sixty characters in total length"
    result = base._clamp_title(long_title)
    assert len(result) <= 60


def test_clamp_title_cuts_at_word_boundary_not_mid_word():
    long_title = "This is a very long podcast episode title that definitely exceeds sixty characters in total length"
    result = base._clamp_title(long_title)
    assert long_title.startswith(result)
    assert len(long_title) == len(result) or long_title[len(result)] == " "


def test_clamp_title_no_word_boundary_falls_back_to_hard_cut():
    assert base._clamp_title("x" * 100) == "x" * 60


def test_seo_suggestion_clamps_title_on_construction():
    long_title = "This is a very long podcast episode title that definitely exceeds sixty characters in total length"
    suggestion = base.SeoSuggestion(title=long_title, description="unrelated description text")
    assert len(suggestion.title) <= 60
    assert suggestion.description == "unrelated description text"  # only the title is clamped


def test_seo_suggestion_leaves_compliant_title_untouched():
    suggestion = base.SeoSuggestion(title="A Short SEO Title", description="d")
    assert suggestion.title == "A Short SEO Title"
