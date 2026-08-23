# Podscriber

Local-only podcast processing app: upload an episode, get a transcript, AI-generated titles/show
notes/social posts/keywords/chapters, quotable soundbites, and vertical (9:16) audiogram videos —
then publish or schedule any of it straight to your social accounts via Postiz.

## One-time setup

```bash
sudo apt install ffmpeg python3.12-venv   # required — audio clipping, waveform, and video export all use ffmpeg
cd ~/podscriber
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you want a fully local/offline setup:
- Install [Ollama](https://ollama.com) and pull a model, e.g. `ollama pull qwen3:4b-instruct`
- Local Whisper (`faster-whisper`) is used by default and downloads its model on first use — no extra
  setup needed beyond the pip install above.
- Ollama can saturate CPU during generation and make the website feel sluggish while it's running.
  To keep the site responsive, give Ollama a lower scheduling priority than usual:
  `sudo systemctl edit ollama`, add `Nice=5` and `CPUWeight=50` under `[Service]`, then
  `sudo systemctl daemon-reload && sudo systemctl restart ollama`.

If you'd rather use hosted APIs, get a Claude API key from console.anthropic.com and/or an OpenAI API
key, and enter them in Settings once the app is running.

## Run

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000, go to **Settings** first to choose/confirm your transcription and
text-generation providers, then **New Episode** to upload an audio file.

## Soundbites & vertical video

Processing an episode surfaces a handful of quotable **soundbites**. Each one can be turned into a
1080×1920 vertical video (background image, brand logo, animated waveform, AI-written caption and
YouTube title) from its **Edit video** page.

A soundbite isn't limited to a single video: once you've exported and (optionally) published one
version, **Duplicate to new video** on that page copies its background/waveform/caption settings
into a brand-new, unexported variant, so you can try a different look or write different copy
without losing or overwriting the one you already shipped. Once a soundbite has more than one
variant, the soundbites list shows a "Video 1 / Video 2 / …" picker next to **Edit** instead of a
single link.

## Analytics

The **Analytics** page pulls your show's real numbers once you've added credentials in Settings:

- **Directory metadata** (via [PodcastIndex.org](https://podcastindex.org)) — your feed's artwork,
  author, indexed episode count, categories, and Value4Value status. Requires a PodcastIndex API
  key/secret and your feed URL under Settings → PodcastIndex.
- **Episode details** (also via PodcastIndex) — a duration histogram and a per-episode table of
  publish date and duration, joined with OP3 download counts by title where available.
- **Download analytics** (via [OP3.dev](https://op3.dev), a free open-source download tracker) —
  30-day and weekly-average downloads, a weekly trend chart, and a top-episodes table. OP3 only
  has data for episodes whose enclosure URLs are routed through an OP3 redirect prefix, which is
  set up on your hosting platform, not in Podscriber — the page shows the exact prefix to add and
  explains there's no historical backfill. Requires an OP3 API key under Settings → OP3.

Each section fetches independently, so you can use PodcastIndex metadata without OP3, or vice
versa. Results are cached (24h for PodcastIndex, 6h for OP3) with a manual **Refresh** button to
force a refetch; if a refetch fails, the page falls back to showing the last good data marked
"Stale" rather than an error.

## Improvements

The **Improvements** page pulls your show's back catalog from its RSS feed (via PodcastIndex, same
credentials as Analytics) and lines each episode's original title/description up against an
AI-suggested, SEO-optimized replacement — a title, description, and target keywords.

- **Suggest improvements** generates a suggestion from the episode's existing title and
  description alone.
- **Suggest using transcript** downloads and transcribes the episode's audio first, then generates
  the suggestion from the full transcript for a more informed rewrite — slower, but worth it for
  older or thin show notes. Once used, the button becomes **Regenerate using transcript**.
- **Generate all missing suggestions** runs the fast (non-transcript) suggestion for every episode
  in the feed that doesn't have one yet, with a progress bar.

Every suggested title, description, and keyword list can be copied with one click to paste into
your hosting platform or feed editor — Podscriber doesn't publish these back to the feed itself.

## Social publishing (Postiz)

Podscriber can publish or schedule posts directly to your social accounts through
[Postiz](https://postiz.com) (hosted or self-hosted) — no copy/paste required. Add your Postiz
instance's **base URL** and **API key** under Settings → Postiz, then:

- From a soundbite's **Edit video** page, use **Publish to Postiz** to post that clip's vertical
  video (plus its caption and generated YouTube title) to one or more platforms, right away or on
  a schedule.
- From an episode's **Social Posts** tab, publish any of the AI-generated per-platform post
  variants the same way, optionally attaching the full-episode video, a soundbite clip's video, or
  an uploaded image/video.

Supported platforms: **TikTok, YouTube, X, Instagram, Bluesky, Threads, Facebook.** A few things
happen automatically so you don't have to think about platform quirks:

- **TikTok** posts go out as a direct, public post (not an unpublished inbox draft), with sensible
  defaults for duet/stitch/comments and content-disclosure fields.
- **YouTube** gets a title automatically — the clip's own generated title, or (for an episode post)
  the episode's selected title.
- **Instagram** accepts a video-only post — no image required — and Podscriber auto-detects
  whether you've connected a regular or a "standalone" Instagram integration in Postiz.
- **X** and **Bluesky** captions are automatically trimmed to fit each platform's character limit
  (dropping trailing hashtags first) if the generated text runs long.
- If a platform still rejects a post, the real reason Postiz gave (not just "failed") shows up
  next to that platform in the publish status, so it's easy to tell what's actually wrong.

## Notes

- All data (episodes, transcripts, generated content, exported videos) lives under `media/` and
  `podscriber.db` in this project directory. Nothing leaves your machine except calls you explicitly
  configure — to Claude/OpenAI in Settings, to PodcastIndex.org/OP3.dev if you set up Analytics or
  Improvements, and to your own Postiz instance if you publish a post — local Whisper and Ollama are
  fully offline.
- API keys (including your Postiz API key) are stored unencrypted in `podscriber.db` (this is a
  single-user local tool — don't share that file).
- The PodcastIndex and OP3 Settings fields power the **Analytics** and **Improvements** pages (see
  above) — both are optional and each page degrades to an empty state explaining what to add if
  either is left unconfigured.
