"""Stage: narration. One Amharic voice line per shot with Gemini TTS.

Reads:  storyboard.json (voice, shots[].narration.am)
Writes: outputs/narration/<shot>_<hash>.wav, outputs/timeline.json
Cache key: narration text + voice model + voice name + style prompt.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import wave
from pathlib import Path

from common import (cached, clean_stale, duration_of, ffmpeg, input_hash, load_env, load_storyboard,
                    log_run, mock_mode, require_tools, stage_dir, timeline_path, with_retries)

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
# Tried in order if the storyboard's model is refused (models are renamed often).
FALLBACK_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]
SAMPLE_RATE = 24000
LEAD_IN, TAIL = 0.4, 0.6   # seconds of air before and after each line inside its shot


def tts_call(model: str, voice: str, style: str, text: str) -> bytes:
    import requests
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set (put it in .env)")
    body = {
        # Only the Amharic sentence is sent. Earlier runs prefixed an English style instruction and the
        # model sometimes read it aloud inside the narration (FAILURES F8), so style is now left to the voice.
        "contents": [{"role": "user", "parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    r = requests.post(API.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=120)
    if r.status_code == 429:
        raise RateLimited(retry_delay(r))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
    return base64.b64decode(part["data"])


class RateLimited(Exception):
    def __init__(self, wait: float):
        super().__init__(f"HTTP 429 rate limited, server asks to wait {wait:.0f}s")
        self.wait = wait


def retry_delay(r) -> float:
    """Google puts the wait in error.details[].retryDelay, e.g. "37s". Default 60s."""
    try:
        for d in r.json()["error"].get("details", []):
            if "retryDelay" in d:
                return float(str(d["retryDelay"]).rstrip("s")) + 2
    except Exception:  # noqa: BLE001
        pass
    return 60.0


def write_wav(pcm: bytes, path: Path) -> None:
    raw = path.with_name("_raw_" + path.name)
    with wave.open(str(raw), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    # Trim silence at the start and end, and shorten any pause inside the line to 0.5 s,
    # so shot timing follows the words rather than the model's pauses.
    ffmpeg("-i", str(raw), "-af",
           "silenceremove=start_periods=1:start_threshold=-45dB,"
           "silenceremove=stop_periods=-1:stop_duration=0.5:stop_threshold=-45dB,"
           "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
           str(path))
    raw.unlink()


def mock_line(text: str, path: Path) -> None:
    secs = max(2.0, len(text) * 0.09)
    ffmpeg("-f", "lavfi", "-i", f"sine=frequency=220:duration={secs}", "-af", "volume=0.05",
           "-ar", str(SAMPLE_RATE), "-ac", "1", str(path))


PAUSE_BETWEEN_CALLS = 20.0  # seconds; the free tier allows only a few TTS requests per minute


class QuotaExhausted(Exception):
    """The engine cannot serve today (daily quota) or refuses the model; try the next engine."""


ENGINE_WAIT_LIMIT = 300  # seconds; a longer retryDelay means the daily quota is gone


def gemini_line(model, v, text, shot_id) -> bytes:
    for i in range(4):
        try:
            pcm, _ = with_retries(lambda: tts_call(model, v["voice_name"], v["style_prompt"], text),
                                  attempts=2, what=f"TTS {model}")
            return pcm
        except RateLimited as e:
            log_run(stage="narration", shot=shot_id, model=model, ok=False, error=str(e))
            if e.wait > ENGINE_WAIT_LIMIT:
                raise QuotaExhausted(f"{model}: daily quota used up (server asks {e.wait / 3600:.1f} h)")
            print(f"  ~ {shot_id}: rate limited, waiting {e.wait:.0f}s (same model, keeps one voice)")
            time.sleep(e.wait)
        except RuntimeError as e:
            raise QuotaExhausted(f"{model}: {str(e)[:200]}")
    raise QuotaExhausted(f"{model}: still rate limited")


def edge_line(voice: str, rate: str, text: str, path: Path) -> None:
    """Microsoft Edge read-aloud voices (free, no key). Amharic: am-ET-MekdesNeural, am-ET-AmehaNeural."""
    import asyncio
    import edge_tts
    mp3 = path.with_name("_edge_" + path.stem + ".mp3")
    asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(mp3)))
    ffmpeg("-i", str(mp3), "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "s16le", str(mp3) + ".pcm")
    pcm = Path(str(mp3) + ".pcm").read_bytes()
    Path(str(mp3) + ".pcm").unlink()
    mp3.unlink()
    write_wav(pcm, path)


def engines(v: dict) -> list[dict]:
    forced = os.environ.get("NARRATION_ENGINE")
    gem = [{"engine": "gemini", "model": m} for m in [v["model"]] + [m for m in FALLBACK_MODELS if m != v["model"]]]
    edge = [{"engine": "edge", "model": v.get("edge_voice", "am-ET-MekdesNeural"), "rate": v.get("edge_rate", "-5%")}]
    if forced == "edge":
        return edge
    if forced == "gemini":
        return gem
    return gem + edge


def render_all(sb, v, eng, out) -> list[Path]:
    """Make every line with ONE engine so the film has one voice. Raises QuotaExhausted to move on."""
    paths = []
    for shot in sb["shots"]:
        text = shot["narration"][sb["language"]["narration"]]
        tag = "mock" if mock_mode() else f"{eng['engine']}:{eng['model']}:{eng.get('rate', '')}"
        h = input_hash(text, v["voice_name"], "text-only", tag)
        path = out / f"{shot['id']}_{h}.wav"
        if cached(path):
            log_run(stage="narration", shot=shot["id"], model=eng["model"], cache_hit=True, file=path.name)
            print(f"  = {shot['id']} narration cached")
        else:
            t0 = time.time()
            if mock_mode():
                mock_line(text, path)
            elif eng["engine"] == "gemini":
                write_wav(gemini_line(eng["model"], v, text, shot["id"]), path)
                time.sleep(PAUSE_BETWEEN_CALLS)
            else:
                try:
                    with_retries(lambda: edge_line(eng["model"], eng["rate"], text, path), attempts=3,
                                 what=f"edge {eng['model']}")
                except Exception as e:  # noqa: BLE001
                    raise QuotaExhausted(f"edge: {str(e)[:200]}")
            clean_stale(out, shot["id"], path)
            log_run(stage="narration", shot=shot["id"], engine=eng["engine"], model=eng["model"],
                    voice=v["voice_name"] if eng["engine"] == "gemini" else eng["model"], chars=len(text),
                    latency_s=round(time.time() - t0, 2), cost_usd=0.0, ok=True, cache_hit=False, file=path.name)
            print(f"  + {shot['id']} narration with {eng['model']} in {time.time() - t0:.1f}s")
        paths.append(path)
    return paths


TIGHTEN = ("silenceremove=start_periods=1:start_threshold=-45dB,"
           "silenceremove=stop_periods=-1:stop_duration=0.4:stop_threshold=-45dB,"
           "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse")


def reuse_existing(sb, out):
    """NARRATION_ENGINE=reuse: keep the lines already generated (no API calls), trim pauses and
    optionally speed them up (NARRATION_TEMPO, e.g. 1.3). Sources are read from timeline.json."""
    tl = json.loads(timeline_path().read_text(encoding="utf-8"))
    tempo = float(os.environ.get("NARRATION_TEMPO", "1.0"))
    by_id = {r["id"]: r for r in tl["shots"]}
    pairs = []
    for shot in sb["shots"]:
        src = out / by_id[shot["id"]].get("source", by_id[shot["id"]]["narration"])
        if not src.exists():
            sys.exit(f"reuse: {src.name} not found; run narration normally first")
        h = input_hash("reuse", src.name, tempo)
        path = out / f"{shot['id']}_r{h}.wav"
        if not cached(path):
            ffmpeg("-i", str(src), "-af", TIGHTEN + (f",atempo={tempo}" if tempo != 1.0 else ""), str(path))
            log_run(stage="narration", shot=shot["id"], model="reuse", source=src.name, tempo=tempo,
                    cache_hit=False, ok=True, file=path.name)
            print(f"  + {shot['id']} reused {src.name} at {tempo}x")
        for old in out.glob(f"{shot['id']}_r*.wav"):
            if old != path:
                old.unlink()
        pairs.append((path, src.name))
    return pairs


def main() -> None:
    require_tools()
    load_env()
    sb = load_storyboard()
    v = sb["voice"]
    out = stage_dir("narration")
    paths, used, sources = None, None, None
    if os.environ.get("NARRATION_ENGINE") == "reuse":
        pairs = reuse_existing(sb, out)
        paths, sources = [p for p, _ in pairs], [n for _, n in pairs]
        used = {"engine": "reuse", "model": "previous Gemini lines", "tempo": os.environ.get("NARRATION_TEMPO", "1.0")}
    for eng in ([] if paths else [{"engine": "mock", "model": "mock-tts"}] if mock_mode() else engines(v)):
        print(f"  trying {eng['engine']} / {eng['model']} for all lines")
        try:
            paths = render_all(sb, v, eng, out)
            used = eng
            break
        except QuotaExhausted as e:
            log_run(stage="narration", shot="all", model=eng["model"], ok=False, error=str(e))
            print(f"  ! {e}\n  -> switching engine and regenerating ALL lines so the voice stays consistent")
    if not paths:
        sys.exit("No narration engine available today. Try again after the quota resets, or set NARRATION_ENGINE=edge.")
    if sources is None:
        sources = [p.name for p in paths]
    timeline, t = [], 0.0
    for shot, path, source in zip(sb["shots"], paths, sources):
        nd = duration_of(path)
        dur = round(max(shot["min_duration"], LEAD_IN + nd + TAIL), 2)
        timeline.append({"id": shot["id"], "start": round(t, 2), "duration": dur, "narration": path.name,
                         "source": source,
                         "narration_start": round(t + LEAD_IN, 2), "narration_duration": round(nd, 2),
                         "am": shot["narration"]["am"], "en": shot["narration"]["en"]})
        t += dur
    total = t + sb["end_card"]["duration"]
    timeline_path().write_text(json.dumps({"shots": timeline, "end_card_start": round(t, 2), "total": round(total, 2),
                                           "narration_engine": used}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"narration done with {used['engine']} / {used['model']}: film length will be {total:.1f}s")
    for row in timeline:
        if row["narration_duration"] > 12:
            print(f"  WARNING: {row['id']} narration is {row['narration_duration']}s; listen to outputs/narration/{row['narration']}")
    if not 60 <= total <= 90:
        print(f"  WARNING: {total:.1f}s is outside the 60-90s target.")


if __name__ == "__main__":
    main()
