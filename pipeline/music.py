"""Stage: music. Picks the score for the film.

Reads:  storyboard.json (music), outputs/timeline.json
        optional outputs/music/candidates/*.wav  (ACE-Step 1.5 candidates made on Colab,
        see notebooks/ace_step_colab.ipynb) and outputs/music/choice.txt (file name of the pick)
Writes: outputs/music/score_<hash>.wav  (exactly the film length, with fades)

If no ACE-Step candidate is present, the fallback engine composes a short original piece in
code: a krar-like plucked melody in the tizita pentatonic scale over a soft drone, using
Karplus-Strong synthesis. It needs no GPU and no network, so the film always has a score.
"""
from __future__ import annotations

import json
import time
import wave
from pathlib import Path

from common import (OUT, cached, clean_stale, ffmpeg, input_hash, load_storyboard, log_run, stage_dir,
                    timeline_path)

SR = 44100
# Tizita major, rooted on D: D E F# A B (degrees 0 2 4 7 9 semitones)
TIZITA = [0, 2, 4, 7, 9]
ROOT_HZ = 146.83  # D3


def pluck(freq: float, secs: float, rng, damp: float = 0.996):
    import numpy as np
    n = int(SR * secs)
    period = max(2, int(SR / freq))
    buf = rng.uniform(-1, 1, period)
    out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % period]
        buf[i % period] = damp * 0.5 * (buf[i % period] + buf[(i + 1) % period])
    return out


def compose(total: float, bpm: float, seed: int):
    """Return a float array: krar melody + bass pluck + drone, gently shaped over the film."""
    import numpy as np
    rng = np.random.default_rng(seed)
    beat = 60.0 / bpm
    n = int(SR * total)
    mix = np.zeros(n + SR * 3)
    # Melody: a phrase of 8 notes repeated with variation; stepwise motion is more likely.
    deg = 2
    t = 0.0
    while t < total:
        for k in range(8):
            step = rng.choice([-1, 0, 1, 1, 2, -2], p=[0.3, 0.1, 0.3, 0.1, 0.1, 0.1])
            deg = int(np.clip(deg + step, 0, 9))
            octave, idx = divmod(deg, 5)
            f = ROOT_HZ * 2 ** ((TIZITA[idx] + 12 * (octave + 1)) / 12)
            length = beat * (2 if k in (3, 7) else 1)
            s = int(SR * t)
            note = pluck(f, length + 1.2, rng) * 0.25
            mix[s:s + len(note)] += note[: len(mix) - s]
            t += length
            if t >= total:
                break
    # Bass on every second beat: root or fifth.
    t = 0.0
    i = 0
    while t < total:
        f = ROOT_HZ / 2 * (1.5 if i % 4 == 2 else 1.0)
        s = int(SR * t)
        note = pluck(f, 2.5, rng, damp=0.998) * 0.3
        mix[s:s + len(note)] += note[: len(mix) - s]
        t += beat * 2
        i += 1
    # Drone on root and fifth, slowly breathing.
    tt = np.arange(len(mix)) / SR
    drone = (np.sin(2 * np.pi * ROOT_HZ / 2 * tt) + 0.5 * np.sin(2 * np.pi * ROOT_HZ * 0.75 * tt))
    mix += 0.05 * drone * (0.6 + 0.4 * np.sin(2 * np.pi * tt / 11))
    mix = mix[:n]
    return mix / (np.max(np.abs(mix)) + 1e-9) * 0.8


def write_wav(x, path: Path) -> None:
    import numpy as np
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


def main() -> None:
    sb = load_storyboard()
    m = sb["music"]
    total = json.loads(timeline_path().read_text(encoding="utf-8"))["total"]
    out = stage_dir("music")
    cand_dir = out / "candidates"
    cands = sorted(cand_dir.glob("*.wav")) + sorted(cand_dir.glob("*.mp3")) if cand_dir.exists() else []
    choice_file = out / "choice.txt"
    source, engine = None, "procedural"
    if m["engine"] == "ace-step" and cands:
        pick = choice_file.read_text(encoding="utf-8").strip() if choice_file.exists() else cands[0].name
        source = cand_dir / pick
        if not source.exists():
            raise SystemExit(f"choice.txt names {pick}, which is not in {cand_dir}")
        engine = "ace-step-1.5-import"
    hsh = input_hash(engine, source.name if source else None, source.stat().st_size if source else None,
                     m["bpm"], round(total, 2), sb["style"]["seed"])
    p = out / f"score_{hsh}.wav"
    if cached(p):
        log_run(stage="music", shot="score", cache_hit=True, file=p.name)
        print("  = score cached")
        return
    t0 = time.time()
    if source is None:
        if m["engine"] == "ace-step":
            print("  ! no ACE-Step candidates in outputs/music/candidates/, using procedural fallback score")
        raw = out / f"_raw_{hsh}.wav"
        write_wav(compose(total, m["bpm"], sb["style"]["seed"]), raw)
        source = raw
    fade_out = 3.0
    ffmpeg("-i", str(source), "-t", f"{total}",
           "-af", f"aloop=loop=-1:size=2e9,atrim=0:{total},afade=t=in:d=2,afade=t=out:st={total - fade_out}:d={fade_out}",
           "-ar", str(SR), "-ac", "2", str(p))
    for tmp in out.glob("_raw_*.wav"):
        tmp.unlink()
    clean_stale(out, "score", p)
    log_run(stage="music", shot="score", model=engine, source=source.name, duration_s=total,
            latency_s=round(time.time() - t0, 2), gpu_minutes=0, cost_usd=0.0, ok=True, cache_hit=False,
            file=p.name)
    print(f"  + score ({engine}) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
