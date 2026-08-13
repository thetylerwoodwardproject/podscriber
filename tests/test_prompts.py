from app.services.llm import prompts


def test_titles_prompt_forbids_em_dash():
    system, _, _ = prompts.titles_prompt("transcript")
    assert "em dash" in system.lower()


def test_description_prompt_forbids_em_dash():
    system, _, _ = prompts.description_prompt("transcript")
    assert "em dash" in system.lower()


def test_social_posts_prompt_default_tone_is_casual():
    system, _, _ = prompts.social_posts_prompt("transcript", "desc")
    assert "casual" in system.lower()


def test_social_posts_prompt_formal_tone():
    system, _, _ = prompts.social_posts_prompt("t", "d", tone="formal")
    assert "formal" in system.lower()


def test_social_posts_prompt_custom_instructions_included_verbatim():
    system, _, _ = prompts.social_posts_prompt(
        "t", "d", custom_instructions="Always mention the guest's name."
    )
    assert "Always mention the guest's name." in system


def test_social_posts_prompt_no_custom_instructions_by_default():
    system, _, _ = prompts.social_posts_prompt("t", "d")
    assert "casual" in system.lower()


def test_titles_prompt_custom_instructions_included_verbatim():
    system, _, _ = prompts.titles_prompt("t", custom_instructions="Always mention the guest's name.")
    assert "Always mention the guest's name." in system


def test_description_prompt_custom_instructions_included_verbatim():
    system, _, _ = prompts.description_prompt("t", custom_instructions="Keep it under 100 words.")
    assert "Keep it under 100 words." in system


def test_soundbites_prompt_custom_instructions_included_verbatim():
    system, _, _ = prompts.soundbites_prompt("t", custom_instructions="Prefer funny moments.")
    assert "Prefer funny moments." in system


def test_chapters_prompt_custom_instructions_included_verbatim():
    system, _, _ = prompts.chapters_prompt("t", custom_instructions="Use short chapter titles.")
    assert "Use short chapter titles." in system


def test_seo_suggestion_prompt_custom_instructions_included_verbatim():
    system, _, _ = prompts.seo_suggestion_prompt("t", "d", custom_instructions="Never mention pricing.")
    assert "Never mention pricing." in system


def test_prompt_ignores_blank_custom_instructions():
    system, _, _ = prompts.titles_prompt("t", custom_instructions="   ")
    assert "custom instructions" not in system.lower()


def test_seo_suggestion_prompt_embeds_title_and_description():
    system, user, schema = prompts.seo_suggestion_prompt("Original Title", "Original description text.")
    assert "Original Title" in user
    assert "Original description text." in user
    assert schema["required"] == ["title", "description", "keywords"]
    assert schema["additionalProperties"] is False


def test_seo_suggestion_prompt_keeps_keywords_out_of_description():
    system, _, schema = prompts.seo_suggestion_prompt("t", "d")
    assert schema["properties"]["keywords"]["type"] == "array"
    assert "only" in system.lower()  # instructs keywords go in their own field, not prose
    assert "em dash" in system.lower()


def test_seo_suggestion_prompt_states_title_length_limit():
    system, _, schema = prompts.seo_suggestion_prompt("t", "d")
    assert "60 characters" in system
    assert schema["properties"]["title"]["maxLength"] == 60


def test_seo_suggestion_prompt_states_description_length_guidance():
    system, _, _ = prompts.seo_suggestion_prompt("t", "d")
    assert "50-150 words" in system
    assert "300 characters" in system


def test_seo_suggestion_prompt_favors_clarity_and_guest_names():
    system, _, _ = prompts.seo_suggestion_prompt("t", "d")
    assert "clarity over cleverness" in system.lower()
    assert "guest" in system.lower()
