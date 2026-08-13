# Podscriber

Local-only podcast processing app: upload an episode, get a transcript, AI-generated titles/show
notes/social posts/keywords/chapters, quotable soundbites, and vertical (9:16) audiogram videos.

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

## Notes

- All data (episodes, transcripts, generated content, exported videos) lives under `media/` and
  `podscriber.db` in this project directory. Nothing leaves your machine except calls you explicitly
  configure to Claude/OpenAI in Settings — local Whisper and Ollama are fully offline.
- API keys are stored unencrypted in `podscriber.db` (this is a single-user local tool — don't share
  that file).
- The Podcast Index and OP3 Settings fields are credential storage only, for parity with the original
  design — they aren't wired into any feature yet (no analytics dashboard).
