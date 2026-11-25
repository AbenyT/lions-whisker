# Architecture

## One contract, six steps

`storyboard.json` is the only input. Every stage reads it, writes into `outputs/<stage>/`, and never edits it. The schema in `schema/storyboard.schema.json` is checked before every stage (`common.load_storyboard`), plus two checks JSON Schema cannot express: shot ids are unique, and every character a shot names is defined.

| Step | Script | Reads | Writes | Model |
|---|---|---|---|---|
| 0 Validate | `validate.py` | storyboard, schema | nothing | none |
| 1 Narration | `narration.py` | `shots[].narration.am`, `voice` | `narration/<shot>_<hash>.wav`, `timeline.json` | Gemini TTS |
| 2 Music | `music.py` | `music`, `timeline.json`, `music/candidates/` | `music/score_<hash>.wav` | ACE-Step 1.5 (Colab) or procedural fallback |
| 3 Radio cut | `assemble.py --radio` | timeline, narration, score | `radio_cut.mp4` | FFmpeg |
| 4 Keyframes | `keyframes.py` | `style`, `characters`, `shots[].image_prompt` | `refs/<char>_<hash>.png`, `keyframes/<shot>_<hash>.png` | FLUX.2 klein 4B (fallback FLUX.1 schnell) |
| 5 Shots | `shots.py` | keyframes, `motion`, timeline, optional `wan/<shot>.mp4` | `shots/<aspect>/<shot>_<hash>.mp4` | FFmpeg zoompan, or imported Wan 2.2 clip |
| 6 Assemble | `assemble.py` | all of the above | `film_9x16.mp4`, `film_16x9.mp4`, `subs/*.srt` | FFmpeg + libass |

`run_all.py` runs them in this order and stops at the first failing stage; because everything is cached, re-running after a fix resumes where it stopped.

## Why the voice sets the timing

Each shot lasts `max(min_duration, 0.6 s + narration length + 0.9 s)`. The narration stage writes those numbers to `timeline.json`, and both the shot clips and the subtitles read from it. That way a longer Amharic line automatically lengthens its shot, and subtitles always match the voice. The script warns if the total leaves the 60 to 90 second range.

## Caching

Every output's file name ends in a 10-character hash of the inputs that produced it (`common.input_hash`):

- narration: Amharic text, voice name, style prompt
- reference sheet: description, seed, model, size
- keyframe: full prompt (framing + image prompt + character descriptions + style block), seed, model, size, names of the reference images used
- shot clip: keyframe file name, motion, duration, fps, size, engine
- score: engine, chosen candidate, bpm, film length

If the file exists, the stage skips the call and writes a `cache_hit` line to `runs.jsonl`. When a shot changes, the new file replaces the old one (`clean_stale`), so `outputs/` holds only the current version. Because keyframe hashes include reference file names, changing a character description regenerates that character's sheet and every shot they appear in, and nothing else.

## Character consistency

Reference sheets are generated first, one per character, on a plain background with the shared style block and a fixed seed. Each keyframe request sends the sheets of the characters in that shot as `input_image_0..3` to FLUX.2 klein, which accepts reference images, along with the same style block and seed.

## Failure handling

- **Retries:** every provider call goes through `with_retries` (3 to 4 attempts, waiting 3, 6, 12 s).
- **Model fallback:** TTS tries the storyboard's model, then two older Gemini TTS ids, because model names change often. Keyframes fall back from klein to FLUX.1 schnell, which takes no references, if klein keeps failing. Every failed attempt is logged with its error.
- **Stage fallback:** if no ACE-Step candidate exists, the music stage composes a score in code (Karplus-Strong krar plucks in the tizita scale over a drone). If no Wan clip exists, shots use a Ken Burns move. The film always builds.
- **Secrets:** keys live only in `.env`, which is git-ignored; `.env.example` lists the names.

## Audio and subtitles

Narration lines are placed with `adelay` at their timeline positions and mixed. The score goes through `sidechaincompress` keyed on the voice, so it dips whenever someone speaks, and the mix is normalised to −16 LUFS with `loudnorm` (measured −16.5 LUFS on the mock build). Subtitles are written as ASS with Amharic (Noto Sans Ethiopic, bundled) above English (DejaVu Sans) in one block per line, so wrapped lines cannot overlap. In 9:16 they sit 20% above the bottom edge to stay clear of phone app buttons. Plain `.srt` files in each language are also written.

## Logging

`runs.jsonl` gets one JSON line per model call or cache hit: timestamp, stage, shot, model, seed, size, attempts, latency, cost, ok or error, file. `mock: true` marks dry-run lines so they are not mistaken for real measurements.
