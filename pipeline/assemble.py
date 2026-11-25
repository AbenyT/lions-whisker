"""Stage: assembly. Builds the radio cut and the final film in both aspect ratios.

Reads:  storyboard.json, outputs/timeline.json, outputs/narration/, outputs/shots/<aspect>/,
        outputs/music/score_*.wav
Writes: outputs/radio_cut.mp4                       (python pipeline/assemble.py --radio)
        outputs/film_16x9.mp4, outputs/film_9x16.mp4 (default)
        outputs/subs/film.srt (English), outputs/subs/film_am.srt (Amharic), outputs/subs/*.ass

Audio: narration lines placed at their timeline positions; the score is lowered under the
voice with a sidechain compressor (ducking) and the mix is normalised to the target loudness.
Picture: shots concatenated in order, then the AI end card; Amharic and English subtitles burned in.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from common import (FONTS, OUT, ROOT, ffmpeg, input_hash, load_storyboard, log_run, require_tools,
                    stage_dir, timeline_path)


def ts_srt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def ts_ass(t: float) -> str:
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def write_subtitles(tl: dict, subs: Path) -> None:
    for lang, name in (("en", "film.srt"), ("am", "film_am.srt")):
        lines = []
        for i, s in enumerate(tl["shots"], 1):
            a, b = s["narration_start"], s["narration_start"] + s["narration_duration"] + 0.3
            lines += [str(i), f"{ts_srt(a)} --> {ts_srt(b)}", s[lang], ""]
        (subs / name).write_text("\n".join(lines), encoding="utf-8")


def write_ass(tl: dict, path: Path, w: int, h: int) -> None:
    vertical = h > w
    base = int(h * (0.030 if vertical else 0.042))
    margin_v = int(h * (0.20 if vertical else 0.06))   # keep clear of phone UI in 9:16
    side = int(w * 0.07)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AM,Noto Sans Ethiopic,{int(base * 1.05)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,{max(2, base // 14)},1,2,{side},{side},{margin_v},1
Style: EN,DejaVu Sans,{int(base * 0.85)},&H00E8F4FF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{max(2, base // 14)},1,2,{side},{side},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    for s in tl["shots"]:
        a, b = s["narration_start"], s["narration_start"] + s["narration_duration"] + 0.3
        # One block, Amharic above English, so wrapped lines can never overlap.
        en = "{\\fnDejaVu Sans\\b0\\fs" + str(int(base * 0.85)) + "\\c&H00E8F4FF&}" + s["en"]
        ev.append(f"Dialogue: 0,{ts_ass(a)},{ts_ass(b)},AM,,0,0,0,,{s['am']}\\N{en}")
    path.write_text(header + "\n".join(ev) + "\n", encoding="utf-8")


def end_card_image(sb: dict, w: int, h: int, path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (w, h), (18, 14, 10))
    d = ImageDraw.Draw(img)
    unit = min(w, h)
    am_big = ImageFont.truetype(str(FONTS / "NotoSansEthiopic-Bold.ttf"), int(unit * 0.075))
    am_small = ImageFont.truetype(str(FONTS / "NotoSansEthiopic-Regular.ttf"), int(unit * 0.035))
    en_mid = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), int(unit * 0.034))
    en_small = ImageFont.truetype(str(FONTS / "DejaVuSans.ttf"), int(unit * 0.024))
    ec = sb["end_card"]

    def centered(y, text, font, fill):
        tw = d.textbbox((0, 0), text, font=font)[2]
        d.text(((w - tw) / 2, y), text, font=font, fill=fill)

    def wrap(text, font, max_w):
        words, lines, cur = text.split(), [], ""
        for wd in words:
            test = (cur + " " + wd).strip()
            if d.textbbox((0, 0), test, font=font)[2] <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = wd
        return lines + [cur]

    y = h * 0.30
    centered(y, sb["title"]["am"], am_big, (232, 196, 120))
    y += unit * 0.11
    centered(y, sb["title"]["en"], en_mid, (240, 230, 210))
    y += unit * 0.08
    centered(y, ec["lines"]["am"].split("·")[-1].strip(), am_small, (200, 190, 170))
    y += unit * 0.10
    d.line([(w * 0.3, y), (w * 0.7, y)], fill=(120, 100, 70), width=2)
    y += unit * 0.04
    for line in wrap(ec["ai_notice"], en_small, w * 0.8):
        centered(y, line, en_small, (220, 220, 220))
        y += unit * 0.035
    img.save(path)


def build_audio_graph(tl: dict, first_input: int, music_input: int | None, duck_db: float, lufs: float):
    """Return (filter_complex, output_label). Narration inputs start at first_input."""
    parts, labels = [], []
    for i, s in enumerate(tl["shots"]):
        ms = int(s["narration_start"] * 1000)
        parts.append(f"[{first_input + i}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[n{i}]")
        labels.append(f"[n{i}]")
    total = tl["total"]
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,"
                 f"apad=whole_dur={total},atrim=0:{total}[voice]")
    if music_input is None:
        parts.append(f"[voice]loudnorm=I={lufs}:TP=-1.5:LRA=11[mix]")
        return ";".join(parts), "[mix]"
    ratio = max(2.0, min(20.0, abs(duck_db) / 1.5))
    parts.append("[voice]asplit=2[v1][sc]")
    parts.append(f"[{music_input}:a]aresample=44100,volume=-4dB[m]")
    parts.append(f"[m][sc]sidechaincompress=threshold=0.015:ratio={ratio}:attack=30:release=600:makeup=1[duck]")
    parts.append(f"[v1][duck]amix=inputs=2:normalize=0:duration=first,loudnorm=I={lufs}:TP=-1.5:LRA=11[mix]")
    return ";".join(parts), "[mix]"


def narration_files(tl: dict) -> list[Path]:
    return [OUT / "narration" / s["narration"] for s in tl["shots"]]


def latest(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def radio_cut(sb: dict, tl: dict) -> None:
    subs = stage_dir("subs")
    write_subtitles(tl, subs)
    w, h = 1280, 720
    write_ass(tl, subs / "radio.ass", w, h)
    music = latest(OUT / "music", "score_*.wav")
    nars = narration_files(tl)
    total = tl["total"]
    args = ["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=24:d={total}"]
    for n in nars:
        args += ["-i", str(n)]
    music_idx = None
    if music:
        args += ["-i", str(music)]
        music_idx = 1 + len(nars)
    graph, out_label = build_audio_graph(tl, 1, music_idx, sb["music"]["duck_db"], sb["export"]["loudness_lufs"])
    graph += f";[0:v]subtitles=outputs/subs/radio.ass:fontsdir=fonts[v]"
    t0 = time.time()
    out = OUT / "radio_cut.mp4"
    run_ffmpeg_in_root(args + ["-filter_complex", graph, "-map", "[v]", "-map", out_label,
                               "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-c:a", "aac", "-b:a", "160k",
                               "-t", f"{total}", "outputs/radio_cut.mp4"])
    log_run(stage="assemble", shot="radio_cut", model="ffmpeg", music=music.name if music else None,
            duration_s=total, latency_s=round(time.time() - t0, 2), cost_usd=0.0, ok=True, file=out.name)
    print(f"radio cut written: {out} ({total:.1f}s)")


def run_ffmpeg_in_root(args: list[str]) -> None:
    import os
    cwd = os.getcwd()
    os.chdir(ROOT)  # subtitle filter paths are relative to the repo root (avoids Windows drive-colon issues)
    try:
        ffmpeg(*args)
    finally:
        os.chdir(cwd)


def final(sb: dict, tl: dict) -> None:
    subs = stage_dir("subs")
    write_subtitles(tl, subs)
    music = latest(OUT / "music", "score_*.wav")
    if not music:
        sys.exit("no score found; run the music stage first")
    nars = narration_files(tl)
    fps = sb["export"]["fps"]
    for aspect, size in sb["export"]["targets"].items():
        w, h = size["width"], size["height"]
        sdir = OUT / "shots" / aspect
        clips = []
        for s in tl["shots"]:
            c = latest(sdir, f"{s['id']}_*.mp4")
            if not c:
                sys.exit(f"missing shot {s['id']} for {aspect}; run the shots stage")
            clips.append(c)
        card_png = subs / f"endcard_{aspect}.png"
        end_card_image(sb, w, h, card_png)
        card_mp4 = subs / f"endcard_{aspect}.mp4"
        ffmpeg("-loop", "1", "-i", str(card_png), "-t", str(sb["end_card"]["duration"]),
               "-vf", f"fade=t=in:d=0.8,format=yuv420p", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "20", str(card_mp4))
        concat = subs / f"concat_{aspect}.txt"
        concat.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in clips + [card_mp4]), encoding="utf-8")
        write_ass(tl, subs / f"film_{aspect}.ass", w, h)
        args = ["-f", "concat", "-safe", "0", "-i", str(concat)]
        for n in nars:
            args += ["-i", str(n)]
        args += ["-i", str(music)]
        graph, out_label = build_audio_graph(tl, 1, 1 + len(nars), sb["music"]["duck_db"], sb["export"]["loudness_lufs"])
        graph += f";[0:v]subtitles=outputs/subs/film_{aspect}.ass:fontsdir=fonts,format=yuv420p[v]"
        out = f"outputs/film_{aspect}.mp4"
        t0 = time.time()
        run_ffmpeg_in_root(args + ["-filter_complex", graph, "-map", "[v]", "-map", out_label,
                                   "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                                   "-movflags", "+faststart", "-t", f"{tl['total']}", out])
        log_run(stage="assemble", shot=f"film_{aspect}", model="ffmpeg", music=music.name,
                inputs_hash=input_hash([c.name for c in clips], music.name, [n.name for n in nars]),
                duration_s=tl["total"], latency_s=round(time.time() - t0, 2), cost_usd=0.0, ok=True, file=out)
        print(f"film written: {out} ({tl['total']:.1f}s)")


def main() -> None:
    require_tools()
    sb = load_storyboard()
    tl = json.loads(timeline_path().read_text(encoding="utf-8"))
    if "--radio" in sys.argv:
        radio_cut(sb, tl)
    else:
        final(sb, tl)


if __name__ == "__main__":
    main()
