# The Lion's Whisker · የአንበሳው ጢም

A 75-second film of the Ethiopian folktale *The Lion's Whisker*, narrated in Amharic with Amharic and English subtitles and an original score, generated end to end by a code pipeline from one file: `storyboard.json`.

Outputs: `outputs/film_9x16.mp4` (phones) and `outputs/film_16x9.mp4` (YouTube), plus `outputs/radio_cut.mp4` (audio-only draft used for the first audience test).

## Run it

```bash
git clone <this repo> && cd lions-whisker
pip install -r requirements.txt          # Python 3.10+
cp .env.example .env                     # then paste your keys into .env
make film                                # or: python pipeline/run_all.py
```

Needs FFmpeg on your PATH (Windows: `winget install Gyan.FFmpeg`; Ubuntu: `sudo apt install ffmpeg`).

| Command | What it does |
|---|---|
| `make film` | Whole pipeline, both aspect ratios |
| `make radio` | Narration and score on a black screen, with subtitles (first user test) |
| `make mock` | Offline dry run with placeholder media; no keys needed. Use it to check your setup |
| `make validate` | Check `storyboard.json` against `schema/storyboard.schema.json` |
| `make narration` / `keyframes` / `shots` / `music` / `assemble` | One stage at a time |
| `python pipeline/stats.py` | Calls, failures, cache hits and latency per stage from `runs.jsonl` |

**Change one shot and regenerate only that shot:** edit that shot's `image_prompt` or `narration` in `storyboard.json`, then run `make film` again. Each output file name carries a hash of its inputs; unchanged shots are cache hits, and `runs.jsonl` shows exactly one new model call.

## Keys (all free, no payment card)

| Key | Where | Used for |
|---|---|---|
| `GEMINI_API_KEY` | aistudio.google.com/apikey | Amharic narration (Gemini TTS) |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | dash.cloudflare.com, "Workers AI" template token | Keyframes (FLUX.2 klein) |

The score is made on Colab with ACE-Step 1.5 (`notebooks/ace_step_colab.ipynb`); if no candidate is present the pipeline composes a fallback score in code, so the film always builds.

## How it works

```
storyboard.json ──validate──> narration (Gemini TTS) ──> timeline.json (shot lengths from voice)
                               music (ACE-Step import | procedural fallback)
                               radio cut (voice + score on black)       <- user test 1
                 keyframes: character reference sheets -> 11 keyframes (FLUX.2 klein, refs as input)
                 shots: Ken Burns move per keyframe (or Wan 2.2 clip if present in outputs/wan/)
                 assemble: concat + end card, ducked score, loudness -16 LUFS, AM+EN subtitles, 9:16 + 16:9
```

Details in [ARCHITECTURE.md](ARCHITECTURE.md). Audience and intent in [DESIGN.md](DESIGN.md). Measured time and cost in [COSTS.md](COSTS.md). Consent, licences and labelling in [ETHICS.md](ETHICS.md). Experiments and failures in [EXPERIMENTS.md](EXPERIMENTS.md) and [FAILURES.md](FAILURES.md).

## What it costs

Nothing on the free tiers. List-price equivalents and measured latency per stage are in [COSTS.md](COSTS.md).

## Repository

```
storyboard.json      the contract: shots, prompts, references, narration (am/en), music cues
schema/              JSON Schema, validated before every stage
pipeline/            one script per stage + common.py (cache, retries, logging) + run_all.py
runs.jsonl           one line per model call or cache hit
outputs/             generated media, kept for inspection
fonts/               Noto Sans Ethiopic + DejaVu Sans (licences in fonts/licenses/)
notebooks/           Colab notebook for ACE-Step score candidates
```
