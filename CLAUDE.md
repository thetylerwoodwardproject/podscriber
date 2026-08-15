# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Podscriber — a local-only podcast processing app. Upload an episode, get a transcript, AI-generated
titles/show notes/social posts/keywords/chapters, quotable soundbites, and vertical (9:16) audiogram
videos. FastAPI + Jinja2 (server-rendered, no JS build step) + SQLAlchemy/SQLite + vanilla JS/CSS.
There is no Node/npm in this project on purpose — all frontend interactivity is hand-written JS in
`app/static/js/`.

## Run / test

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
pytest tests/ -q
```

The venv's pip was bootstrapped manually via `get-pip.py` (this host is missing the `python3.12-venv`
apt package, so `python3 -m venv` alone can't run ensurepip). If `.venv` ever needs recreating:
`python3 -m venv --without-pip .venv && .venv/bin/python get-pip.py && .venv/bin/pip install -r requirements.txt`.

## Hard external dependencies

- **ffmpeg** must be installed on the host (`sudo apt install ffmpeg`) — audio clipping
  (`services/audio_clip.py`), waveform extraction (`services/waveform.py`), and video export
  (`services/video_export.py`) all shell out to it. The app logs a startup warning if it's missing.
- **Ollama** (optional, for free local text generation) must be running at `localhost:11434` with a
  model pulled (default `qwen3:4b-instruct`). Local Whisper (`faster-whisper`) needs no separate
  service — it downloads its model on first use. Ollama's local inference can saturate all CPU
  cores and make the website feel unresponsive while it's running — this is OS-level CPU
  contention between two separate processes, not an app bug. It's mitigated by a systemd override
  on `ollama.service` (`Nice=5`, `CPUWeight=50` — see README.md) that gives the site priority under
  contention; don't try to "fix" this in `app/services/llm/ollama_provider.py` or job-scheduling
  code.
- All provider selection (Claude vs. Ollama, local Whisper vs. OpenAI Whisper API, model names, API
  keys) is configured through the Settings UI and stored in the `settings` SQLite table — not env
  vars. Don't add env-var config for these; read/write via `app/services/settings_store.py`.

## Gotchas (found the hard way — see git history / build notes for the failure mode)

- **SQLite cross-session visibility in polling loops.** A long-lived SQLAlchemy session (e.g. an SSE
  generator polling a `Job` row written by a background thread's own session) will keep reading a
  stale snapshot forever unless you end its transaction between reads. Call `db.commit()` at the top
  of each poll iteration before querying — see `app/routers/processing.py` and `video_clip.py` for
  the pattern. Skipping this makes progress bars appear frozen.
- **ffmpeg `-loop 1` image inputs need an explicit `-t <duration>`.** `-shortest` alone is not
  reliable when a looped infinite-duration image input feeds a filter_complex (e.g. an overlay) —
  it can produce a runaway ffmpeg process that never terminates. Always pass `-t` with the known
  clip duration; see the comment in `app/services/video_export.py`.
- **JSON-typed SQLAlchemy columns must be reassigned, never mutated in place.** `GeneratedContent`
  columns (`titles`, `keywords`, `social_posts`) are plain JSON columns, not `MutableList`/
  `MutableDict`. Always build a new list/dict and assign it (`content.keywords = [...]`) — appending
  or indexing into the existing object silently won't persist. See `app/routers/results.py` for the
  correct pattern.
- **A plain (non-`data-ajax`) `<form method="post">` must never render a template or return HTML
  directly from its POST handler.** Doing so leaves the browser on a POST-originated URL, and
  refreshing it triggers a "Confirm Form Resubmission" prompt — the user must never be made to see
  that or lose the page. Every such POST handler must end with `RedirectResponse(url=..., status_code=303)`
  to a GET route (Post/Redirect/Get), e.g. `generator.py`'s `generate_script` →
  `/generator/{script.id}`, or `results.py`'s `delete_episode` → `/`. This applies under all
  circumstances, with no exceptions. The only forms allowed to return a rendered template/fragment
  or JSON straight from POST are ones marked `data-ajax` (handled via `fetch` by `app/static/js/app.js`,
  never a real page navigation) or ones with their own custom `fetch`-based JS handler that calls
  `e.preventDefault()` before submit (e.g. `analytics.js`'s `#stats-refresh-form`, `improvements.js`'s
  `#improvements-refresh-form`) — never a bare form left to submit as a normal navigation.

## Linting

```bash
ruff check .          # lint
ruff check . --fix    # auto-fix
```

`B008` (function-call-in-default-argument) is narrowed via `extend-immutable-calls` in
`pyproject.toml` rather than disabled outright — FastAPI's `Depends()`/`Query()`/etc. are meant to
be used as default-argument values, but the rule still catches genuine mutable-default mistakes.

## Workflow

Run `pytest tests/ -q` after making changes and confirm it passes before considering a task done.
This is also enforced by a `Stop` hook in `.claude/settings.json`, which blocks completion and
feeds the failure back if tests are red.
