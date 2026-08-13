"""Prompt + JSON-schema definitions shared by both LLM providers.

Each function returns (system_prompt, user_prompt, json_schema) where json_schema
describes the exact JSON object the model must return. Claude enforces this via
output_config.format; Ollama is asked for the same shape via format="json" and a
schema description in the prompt, then parsed leniently.
"""

MAX_TRANSCRIPT_CHARS = 12000  # keep prompts small/cheap; enough context for a podcast episode


def _truncated(transcript_text: str) -> str:
    if len(transcript_text) <= MAX_TRANSCRIPT_CHARS:
        return transcript_text
    return transcript_text[:MAX_TRANSCRIPT_CHARS] + " …[transcript truncated]"


def _with_custom_instructions(system: str, custom_instructions: str) -> str:
    """Appends the user's global Settings-page instructions to a prompt's system message."""
    custom_instructions = custom_instructions.strip()
    if not custom_instructions:
        return system
    return system + f"\n\nAlso follow these custom instructions from the user: {custom_instructions}"


TONE_GUIDANCE = {
    "formal": "Write in a formal, professional tone — polished language, no slang or emoji.",
    "casual": "Write in a casual, conversational tone — contractions and everyday language are welcome.",
    "informative": (
        "Write in an informative, matter-of-fact tone — lead with the concrete takeaway or fact, minimal fluff."
    ),
    "enthusiastic": "Write in an enthusiastic, high-energy tone — upbeat language, exclamation points are welcome.",
    "humorous": "Write in a humorous, playful tone — light wit and fun phrasing, but stay tasteful.",
}

# (value, label) pairs for the tone <select> in the social posts regenerate UI.
SOCIAL_TONES = [
    ("formal", "Formal"),
    ("casual", "Casual"),
    ("informative", "Informative"),
    ("enthusiastic", "Enthusiastic"),
    ("humorous", "Humorous"),
]


def titles_prompt(transcript_text: str, custom_instructions: str = "") -> tuple[str, str, dict]:
    system = (
        "You write compelling podcast episode titles. Titles should be punchy, specific, "
        "and make a listener want to click — not generic or clickbait. Never use an em dash "
        "(—) or en dash (–) in a title."
    )
    system = _with_custom_instructions(system, custom_instructions)
    user = (
        f"Here is a podcast episode transcript:\n\n{_truncated(transcript_text)}\n\n"
        "Generate exactly 3 distinct title options for this episode. For each, also give "
        "a 0-100 'punchiness' score reflecting how compelling it is."
    )
    schema = {
        "type": "object",
        "properties": {
            "titles": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "score": {"type": "integer"},
                    },
                    "required": ["text", "score"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["titles"],
        "additionalProperties": False,
    }
    return system, user, schema


def description_prompt(transcript_text: str, custom_instructions: str = "") -> tuple[str, str, dict]:
    system = (
        "You write podcast show notes and suggest SEO-friendly keywords. Show notes should be "
        "2-3 short paragraphs: a hook, what's covered, and why it's worth listening to. Never "
        "use an em dash (—) or en dash (–) anywhere in the show notes."
    )
    system = _with_custom_instructions(system, custom_instructions)
    user = (
        f"Here is a podcast episode transcript:\n\n{_truncated(transcript_text)}\n\n"
        "Write show notes for this episode, and suggest 6-10 relevant keywords/tags."
    )
    schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["description", "keywords"],
        "additionalProperties": False,
    }
    return system, user, schema


def seo_suggestion_prompt(
    title: str, description: str, custom_instructions: str = "", transcript_text: str | None = None
) -> tuple[str, str, dict]:
    system = (
        "You are a podcast SEO strategist who rewrites episode titles and descriptions so they "
        "rank and convert in podcast app search and Google. Follow these rules strictly:\n"
        "1. Identify the 2-4 specific search terms a real listener would type to find this "
        "episode — concrete topics, named guests, companies, tools, or techniques actually "
        "mentioned in the original text. Never invent generic filler terms. Return these in the "
        "'keywords' field only — never write them into the title or description as a list or "
        "parenthetical.\n"
        "2. Title: a hard limit of 60 characters, about 6-10 words — podcast apps cut titles off "
        "on mobile past that length, and a truncated title defeats the whole point of rewriting "
        "it. Count the characters before finalizing; if it's over 60, cut words, don't abbreviate "
        "into gibberish. If the original text names a guest, feature their name in the title — "
        "people search for guests by name, and a 'core topic + guest name' title consistently "
        "outperforms a topic-only one. Lead with the single most important keyword, topic, or "
        "guest name in the first few words, since that's what's visible even in a truncated view. "
        "Prioritize clarity over cleverness: a plain title that says exactly what the episode is "
        "about beats a clever one that needs context to make sense. Be specific and concrete. "
        "Never use generic filler like 'Episode 12', 'A Conversation With...', or clickbait "
        "phrasing. No ALL CAPS, no emoji, no quotation marks, no em dash (—) or en dash (–).\n"
        "3. Description: 50-150 words total (roughly 2-3 sentences, up to about 300 characters). "
        "Most podcast apps only show that much before hiding the rest behind a 'read more' — "
        "directories like Apple Podcasts technically allow up to 4,000 characters, but nobody "
        "searches or scans past what's visible, so going long buys nothing for discoverability. "
        "The first sentence must stand alone and contain the primary keyword or topic, since it's "
        "the part guaranteed to be seen. Write naturally for a human while naturally including the "
        "target keywords — no keyword stuffing, no bullet lists, no markdown formatting, no "
        "hashtags, no emoji, no HTML tags, no em dash (—) or en dash (–), and no parenthetical "
        "listing the keywords or the original text — the description must read as pure prose.\n"
        "4. Stay strictly accurate to the original content — never invent facts, names, guests, "
        "or claims that aren't present in the original title/description"
        + (" or transcript" if transcript_text else "")
        + ".\n"
        "A generic rewrite that doesn't target real search terms from the content is a failure — "
        "the entire point is discoverability, not just prettier wording."
    )
    if transcript_text:
        system += (
            "\n\nA transcript excerpt of the actual episode audio is provided below the title/"
            "description — prefer it over the blurb as your source of concrete topics, guest "
            "names, and search terms, since the existing description may be vague or incomplete."
        )
    system = _with_custom_instructions(system, custom_instructions)
    user = f"Original title:\n{title}\n\nOriginal description:\n{description}\n\n"
    if transcript_text:
        user += f"Episode transcript (excerpt):\n{_truncated(transcript_text)}\n\n"
    user += "Rewrite both for search discoverability, following the rules above."
    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 60},
            "description": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "description", "keywords"],
        "additionalProperties": False,
    }
    return system, user, schema


def social_posts_prompt(
    transcript_text: str, description: str, tone: str = "casual", custom_instructions: str = ""
) -> tuple[str, str, dict]:
    tone_line = TONE_GUIDANCE.get(tone, TONE_GUIDANCE["casual"])
    system = (
        "You write social media posts promoting a podcast episode, tailored to each platform's "
        "tone: X (formerly Twitter) is terse and punchy, Instagram is warmer with emoji, "
        "Threads is conversational and informal. " + tone_line
    )
    system = _with_custom_instructions(system, custom_instructions)
    user = (
        f"Episode transcript excerpt:\n\n{_truncated(transcript_text)}\n\n"
        f"Show notes:\n{description}\n\n"
        "Write exactly 4 distinct post variants for each of X, Instagram, and Threads promoting this episode."
    )
    schema = {
        "type": "object",
        "properties": {
            "x_posts": {"type": "array", "items": {"type": "string"}},
            "instagram_posts": {"type": "array", "items": {"type": "string"}},
            "threads_posts": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["x_posts", "instagram_posts", "threads_posts"],
        "additionalProperties": False,
    }
    return system, user, schema


def soundbites_prompt(transcript_text: str, custom_instructions: str = "") -> tuple[str, str, dict]:
    system = (
        "You find the most quotable, self-contained moments in a podcast transcript — lines that "
        "would work as standalone soundbites or short video clips. Quote the speaker's exact words."
    )
    system = _with_custom_instructions(system, custom_instructions)
    user = (
        f"Here is a podcast episode transcript:\n\n{_truncated(transcript_text)}\n\n"
        "Pick 3-5 quotable, self-contained moments. Vary their length with how compelling the "
        "passage is: anywhere from about 30 seconds to 2 minutes of spoken audio (roughly "
        "75-300 words at a natural speaking pace) — a single sharp line can stay short, but a "
        "compelling story or argument should run long enough to keep its full context. "
        "Quote them verbatim from the transcript, exactly as spoken, so they can be located exactly."
    )
    schema = {
        "type": "object",
        "properties": {
            "soundbites": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"quote": {"type": "string"}},
                    "required": ["quote"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["soundbites"],
        "additionalProperties": False,
    }
    return system, user, schema


def script_prompt(
    topic: str, research: str, style_excerpts: str, custom_instructions: str = ""
) -> tuple[str, str, dict]:
    system = (
        "You write full podcast episode scripts from scratch: a structural outline followed by a "
        "complete word-by-word script the host can read or closely follow while recording. The "
        "script should sound like natural spoken speech, not a written article — short sentences, "
        "verbal transitions, room for the host's own voice."
    )
    if style_excerpts.strip():
        system += (
            "\n\nExcerpts from this show's past episodes are provided below as a style reference — "
            "match their tone, pacing, and vocabulary so the new script sounds like the same show, "
            "not a generic one."
        )
    system = _with_custom_instructions(system, custom_instructions)
    user = f"Topic / idea for this episode:\n{topic}\n\n"
    if research.strip():
        user += f"Research notes to draw on:\n{research}\n\n"
    if style_excerpts.strip():
        user += f"Style reference — excerpts from past episodes of this show:\n{style_excerpts}\n\n"
    user += (
        "Write this episode. First produce an outline: 5-10 short beats in the order they'll be "
        "covered. Then write the full word-by-word script that follows that outline, ready to "
        "read aloud."
    )
    schema = {
        "type": "object",
        "properties": {
            "outline": {"type": "array", "items": {"type": "string"}},
            "script": {"type": "string"},
        },
        "required": ["outline", "script"],
        "additionalProperties": False,
    }
    return system, user, schema


def chapters_prompt(transcript_text: str, custom_instructions: str = "") -> tuple[str, str, dict]:
    system = (
        "You divide a podcast transcript into chapters — meaningful topic segments a listener could "
        "jump between. The first chapter must cover the very beginning of the episode."
    )
    system = _with_custom_instructions(system, custom_instructions)
    user = (
        f"Here is a podcast episode transcript:\n\n{_truncated(transcript_text)}\n\n"
        "Break this episode into 4-8 chapters, in chronological order. For each chapter give a short, "
        "specific title (not just 'Introduction' or 'Topic 1'), and a short verbatim quote (5-12 words) "
        "copied exactly from the transcript marking where that chapter begins, so it can be located exactly. "
        "The first chapter's start_quote must be copied from very near the start of the transcript."
    )
    schema = {
        "type": "object",
        "properties": {
            "chapters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "start_quote": {"type": "string"},
                    },
                    "required": ["title", "start_quote"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["chapters"],
        "additionalProperties": False,
    }
    return system, user, schema
