"""Stage: moving shots. Turns each keyframe into a clip of the shot's duration.

Reads:  storyboard.json (shots[].motion), outputs/timeline.json, outputs/keyframes/
        optional outputs/wan/<shot>.mp4 (image-to-video clips made on Colab/Kaggle with Wan 2.2)
Writes: outputs/shots/<aspect>/<shot>_<hash>.mp4
Default engine: FFmpeg zoompan (Ken Burns), which needs no GPU. If a Wan clip exists for a
shot it is used instead, cropped to the aspect and trimmed or slowed to the shot duration.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from common import (OUT, cached, clean_stale, duration_of, ffmpeg, input_hash, load_storyboard, log_run,
                    require_tools, stage_dir, timeline_path)


def kenburns_filter(motion: dict, dur: float, fps: int, w: int, h: int) -> str:
    frames = max(1, int(round(dur * fps)))
    s = motion["strength"]
    kind = motion["type"]
    # Work on an oversized frame so the move stays sharp, then scale to target.
    big_w, big_h = w * 2, h * 2
    zin = f"1+{s}*on/{frames}"
    zout = f"1+{s}-{s}*on/{frames}"
    center_x, center_y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if kind == "push_in":
        z, x, y = zin, center_x, center_y
    elif kind == "pull_out":
        z, x, y = zout, center_x, center_y
    elif kind == "pan_right":
        z, x, y = f"1+{s}", f"(iw-iw/zoom)*on/{frames}", center_y
    elif kind == "pan_left":
        z, x, y = f"1+{s}", f"(iw-iw/zoom)*(1-on/{frames})", center_y
    else:
        z, x, y = "1", "0", "0"
    return (f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase,crop={big_w}:{big_h},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},"
            f"format=yuv420p")


def main() -> None:
    require_tools()
    sb = load_storyboard()
    tl = json.loads(timeline_path().read_text(encoding="utf-8"))
    dur_by_id = {s["id"]: s["duration"] for s in tl["shots"]}
    fps = sb["export"]["fps"]
    kdir = OUT / "keyframes"
    wan = OUT / "wan"
    for aspect, size in sb["export"]["targets"].items():
        w, h = size["width"], size["height"]
        out = stage_dir(f"shots/{aspect}")
        for shot in sb["shots"]:
            sid = shot["id"]
            kf = sorted(kdir.glob(f"{sid}_*.png"))
            if not kf:
                raise SystemExit(f"no keyframe for {sid}; run keyframes first")
            kf = kf[-1]
            wan_clip = wan / f"{sid}.mp4"
            src = wan_clip if wan_clip.exists() else kf
            engine = "wan2.2-import" if wan_clip.exists() else "ffmpeg-kenburns"
            dur = dur_by_id[sid]
            src_id = kf.name if engine == "ffmpeg-kenburns" else f"{wan_clip.name}:{wan_clip.stat().st_size}"
            hsh = input_hash(src_id, shot["motion"], dur, fps, w, h, engine)
            p = out / f"{sid}_{hsh}.mp4"
            if cached(p):
                log_run(stage="shots", shot=sid, aspect=aspect, cache_hit=True, file=p.name)
                continue
            t0 = time.time()
            if engine == "ffmpeg-kenburns":
                ffmpeg("-loop", "1", "-i", str(src), "-t", f"{dur}",
                       "-vf", kenburns_filter(shot["motion"], dur, fps, w, h),
                       "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(p))
            else:
                # Stretch a short Wan clip to the shot length rather than looping it.
                factor = max(1.0, dur / duration_of(src))
                ffmpeg("-i", str(src), "-t", f"{dur}",
                       "-vf", f"setpts={factor}*PTS,scale={w}:{h}:force_original_aspect_ratio=increase,"
                              f"crop={w}:{h},fps={fps},format=yuv420p",
                       "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(p))
            clean_stale(out, sid, p)
            log_run(stage="shots", shot=sid, aspect=aspect, model=engine, duration_s=dur,
                    latency_s=round(time.time() - t0, 2), gpu_minutes=0, cost_usd=0.0, ok=True,
                    cache_hit=False, file=p.name)
            print(f"  + {sid} {aspect} shot ({engine}) in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
