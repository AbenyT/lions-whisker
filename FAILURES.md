# Failures

What broke, what I tried, what fixed it. Newest at the bottom.

## F1. No Kaggle account, so no planned GPU for video and music
- **Blocker:** the suggested stack runs Wan 2.2 and ACE-Step on Kaggle, which needs a phone-verified account I did not have, and there were under 40 hours to the deadline.
- **Tried:** planning around Google Colab's free T4 instead (only needs a Google account).
- **Resolution:** made moving shots a Ken Burns move in FFmpeg by default (the brief allows it), with a hook to drop in Wan 2.2 clips (`outputs/wan/<shot>.mp4`) if GPU time appears. Music goes through ACE-Step on Colab, with a code-composed fallback so the film always builds.

## F2. No Ethiopic font, so Amharic would render as empty boxes
- **Blocker:** the build machine had no font covering Ethiopic script; subtitles and the end card need one. Downloading Noto Sans Ethiopic from GitHub was refused by the network allowlist.
- **Tried:** system packages (not available), then the `@fontsource/noto-sans-ethiopic` npm package, which ships WOFF files.
- **Resolution:** converted the WOFF to TTF with fontTools and bundled it in `fonts/` (SIL OFL licence in `fonts/licenses/`), so the repo renders Amharic on any machine. The Ethiopic font has no Latin letters, so DejaVu Sans is bundled for English.

## F3. Subtitles invisible in my first check
- **Symptom:** test frames at 12 s and 30 s showed no subtitles.
- **Cause:** not a bug: both frames fell in the 0.6 s lead-in before narration starts. libass also logged "Error opening memory font" because the licence `.txt` files sat in the fonts folder it scans.
- **Fix:** checked mid-sentence frames instead (subtitles present) and moved the licences to `fonts/licenses/`.

## F4. Amharic and English subtitles overlapped in 9:16
- **Symptom:** in the vertical cut, long lines wrapped to three lines; the English block (fixed margin) climbed into the Amharic block and appeared above it.
- **Cause:** two separate subtitle events with fixed vertical margins can't know how many lines the other wrapped to.
- **Fix:** one event per line with Amharic, a line break, then English in its own font. Wrapping now pushes the whole block up together. Verified on frames from both aspect ratios.

## F5. Narration crashed on Windows: FFmpeg missing
- **Symptom:** first real run generated shot 1's voice, then crashed with `FileNotFoundError: [WinError 2]` when measuring its length.
- **Cause:** FFmpeg (`ffprobe`) was not installed. `winget install Gyan.FFmpeg` then failed on the Microsoft Store source (timeout).
- **Fix:** `winget install Gyan.FFmpeg --source winget`, then a new terminal so PATH updated. The narration stage now checks for FFmpeg before calling any model, so it fails with a clear message instead of after a paid call.

## F6. Rate limits mixed two voices in one film
- **Symptom:** HTTP 429 on many requests. The fallback logic switched to `gemini-3.1-flash-tts-preview` for 7 of 11 lines, so the radio cut had two different TTS models.
- **Fix:** on 429 the pipeline now waits the server's `retryDelay` and retries the **same** model; it only changes model when a model is refused outright. A 20 s pause between calls keeps under the per-minute limit.

## F7. Daily quota exhausted: run stuck for a 19-hour wait
- **Symptom:** after testing, the server answered with a `retryDelay` of 68,587 s and the run sat waiting.
- **Cause:** the free daily TTS quota for `gemini-3.8-flash-tts` was used up by the earlier test runs.
- **Fix:** waits over 5 minutes are now treated as "quota exhausted for today": the stage moves to the next engine and regenerates **all** lines with it, so the voice stays consistent. Added a `reuse` mode that rebuilds the radio cut from lines already generated, with no API calls.

## F8. The voice read my English instruction aloud
- **Symptom:** the radio cut was 232 s (target 60 to 90). Lines of 7 to 9 Amharic words lasted 13 to 14 s. Listening showed English words spoken inside every line.
- **First guess, wrong:** long pauses. Measured with `silencedetect`: only about 10 s of silence in total, so trimming pauses would not fix it.
- **Cause:** the request sent an English style instruction ("Say in Amharic, warmly…") in the same text as the Amharic sentence, and the model spoke part of it.
- **Fix:** send only the Amharic sentence to the TTS model. All lines regenerated the next day after the quota reset.
- **Lesson:** listen to one generated line before generating all eleven.

## F9. Keys "not set" although they were in the file
- **Symptom:** the keyframe stage retried six times and crashed with "CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set".
- **Cause:** Windows Notepad saved the edited file as `.env.txt`, so `.env` still had empty values. Found by printing each key's length (never the value) from both files.
- **Fix:** the loader now reads `.env` then `.env.txt`, ignoring blank values, and the stage stops at once with one clear message if a key is missing, instead of retrying a configuration error. `.env.txt` is git-ignored too.
