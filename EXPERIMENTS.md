# Experiments

Format: hypothesis → change → result → decision. Evidence is in `runs.jsonl` (filter by stage and shot) and in the files named. Target: about ten. E1, E2, E3 and E11 are done with real evidence; the rest are planned and their results must come from real runs.

## E1. One subtitle block vs two
- **Hypothesis:** separate Amharic and English subtitle events with fixed margins are enough.
- **Change:** rendered the mock film and pulled frames at 14 s (16:9) and 62 s (9:16).
- **Result:** fine in 16:9. In 9:16 the long shot 10 line wrapped to three lines and English overlapped Amharic (see FAILURES F4).
- **Decision:** one event per line, Amharic then English. Both aspect ratios checked again: no overlap.

## E2. Does editing one shot regenerate only that shot?
- **Hypothesis:** with input hashes in file names, changing shot 5's image prompt reruns only shot 5's keyframe and its two clips.
- **Change:** edited `s05.image_prompt` ("raising three fingers" to "holding up three fingers") and ran `run_all.py` in mock mode.
- **Result:** stage output showed exactly three new artefacts (`s05` keyframe, `s05` 16x9 clip, `s05` 9x16 clip); every other shot logged a cache hit. Shots stage took 4.2 s instead of 45 s.
- **Confirmed on the real run:** editing five prompts regenerated exactly those five keyframes with five model calls; the other six logged `cache_hit` (runs.jsonl, 25 Nov 17:20).
- **Decision:** keep. This is the live demo for the walkthrough video.

## E3. Two character references per shot vs one
- **Hypothesis:** sending the reference sheets of every character in a shot to FLUX.2 klein keeps faces and costume consistent.
- **Change:** first run (25 Nov, 17:13) sent both references for two-person shots (s02 husband+Almaz, s07 Almaz+lion, s09 Almaz+healer).
- **Result:** identities and costume stayed consistent across all 11 keyframes (Almaz's tilet border and braids, the healer's gabi and staff). But in 3 of 11 shots the model drew a character twice or dropped one: s02 two husbands, s07 two Almazes, s09 the healer missing and Almaz holding his staff. Two more had smaller faults (s05 a flame in the healer's hand, s06 Almaz too close to the lion).
- **Change 2:** rewrote those 5 prompts to state the exact number of people and where each stands. Re-run regenerated only those 5 (6 cache hits). s05, s06, s07, s09 fixed; s02 now had one husband but **two** Almazes.
- **Change 3:** for s02, sent only the husband's reference and described Almaz in words as a small figure in the doorway.
- **Decision:** count-explicit prompts for every multi-person shot; when duplication persists, send only the main character's reference. Evidence: `runs.jsonl` keyframes lines 17:13 to 17:23, keyframe hashes in `outputs/keyframes/`.

## E11. Why the first narration was 232 s long
- **Hypothesis 1:** long pauses inside each line. **Test:** `silencedetect` on all 11 lines: about 10 s of silence in 112 s of speech. **Rejected.**
- **Hypothesis 2:** the model reads extra words. **Test:** listened: English words from the style instruction were spoken inside every line. **Confirmed** (FAILURES F8).
- **Measured on the reused lines:** 112 s of speech; 106 s after trimming pauses; film 96.2 s at 1.3x tempo with tighter timing. None of these fits 60 to 90 s without regenerating.
- **Decision:** send only the Amharic text to TTS and regenerate all lines.

## E4. Gemini TTS voice for the grandmother narrator (planned)
- **Hypothesis:** a warmer, slower voice with the "grandmother by the fire" style prompt sounds more like home than the default.
- **Change:** shot 1 with 2 or 3 voices (e.g. Kore, Aoede, Sulafat); ask a native speaker to rank them.
- **Result:** TODO.

## E5. Amharic pronunciation check (planned)
- **Hypothesis:** Gemini TTS reads the Amharic correctly, but quotation marks «» and names may be mispronounced.
- **Change:** listen to all 11 lines with a native speaker, mark errors per line.
- **Result:** TODO, list mistakes and whether rewording or punctuation fixed them.

## E6. Score: three ACE-Step candidates (planned)
- **Hypothesis:** the tizita/krar prompt produces something recognisably Ethiopian at least once in three seeds.
- **Change:** seeds 11, 22, 33 on Colab, same prompt.
- **Result:** TODO, one line per candidate and why one was chosen.

## E7. ACE-Step vs the code-composed fallback score (planned)
- **Hypothesis:** listeners prefer the ACE-Step score, but the fallback is acceptable.
- **Change:** play the radio cut with each score to two people without saying which is which.
- **Result:** TODO.

## E8. Ducking depth (planned)
- **Hypothesis:** about −14 dB ducking keeps the narration clear on a phone speaker without the music disappearing.
- **Change:** `music.duck_db` at −8, −14, −20; play each on a phone.
- **Result:** TODO.

## E9. Style block: gouache vs photoreal (planned)
- **Hypothesis:** the painted style gives more consistent faces and fits a folktale better than a photoreal prompt.
- **Change:** shot 1 and shot 3 with the style block replaced by a photoreal one.
- **Result:** TODO.

## E10. Ken Burns strength (planned)
- **Hypothesis:** zoom strength 0.08 to 0.14 feels alive without looking mechanical; above 0.2 feels like a slideshow effect.
- **Change:** shot 8 at 0.06, 0.14 and 0.25.
- **Result:** TODO.
