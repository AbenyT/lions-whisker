"""Stage: keyframes. Character reference sheets first, then one still per shot.

Reads:  storyboard.json (style, characters, shots[].image_prompt/framing/characters)
Writes: outputs/refs/<character>_<hash>.png, outputs/keyframes/<shot>_<hash>.png
Model:  Cloudflare Workers AI FLUX.2 [klein] (accepts reference images, which is how a
        character stays the same across shots). Falls back to FLUX.1 [schnell] (text only).
Cache key: everything that goes into the prompt + seed + model + the reference images' hashes.
"""
from __future__ import annotations

import base64
import io
import os
import sys
import time
from pathlib import Path

from common import (FONTS, cached, require_keys, clean_stale, input_hash, load_env, load_storyboard, log_run,
                    mock_mode, stage_dir, with_retries)

CF = "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
KLEIN = os.environ.get("KEYFRAME_MODEL", "@cf/black-forest-labs/flux-2-klein-4b")
SCHNELL = "@cf/black-forest-labs/flux-1-schnell"


def cf_headers() -> dict:
    tok = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not tok or not os.environ.get("CLOUDFLARE_ACCOUNT_ID"):
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN not set (put them in .env)")
    return {"Authorization": f"Bearer {tok}"}


def call_klein(prompt: str, seed: int, w: int, h: int, refs: list[Path]) -> bytes:
    import requests
    url = CF.format(acct=os.environ["CLOUDFLARE_ACCOUNT_ID"], model=KLEIN)
    data = {"prompt": prompt, "width": str(w), "height": str(h), "seed": str(seed)}
    files = {f"input_image_{i}": (p.name, p.read_bytes(), "image/png") for i, p in enumerate(refs[:4])}
    r = requests.post(url, headers=cf_headers(), data=data, files=files or {"_": ("", b"")}, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return base64.b64decode(r.json()["result"]["image"])


def call_schnell(prompt: str, seed: int) -> bytes:
    import requests
    url = CF.format(acct=os.environ["CLOUDFLARE_ACCOUNT_ID"], model=SCHNELL)
    r = requests.post(url, headers=cf_headers(), json={"prompt": prompt[:2000], "steps": 8, "seed": seed}, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return base64.b64decode(r.json()["result"]["image"])


def mock_image(label: str, seed: int, w: int, h: int) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    import random
    rnd = random.Random(seed)
    top = (rnd.randint(120, 200), rnd.randint(70, 120), rnd.randint(30, 60))
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(top[i] * (1 - k) + 25 * k) for i in range(3)))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except OSError:
        font = ImageFont.load_default()
    d.multiline_text((40, h // 2 - 60), "MOCK KEYFRAME\n" + label, fill="white", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def save_png(raw: bytes, path: Path, w: int, h: int) -> None:
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    if im.size != (w, h):
        im = im.resize((w, h))
    im.save(path, "PNG")


def generate(kind: str, sid: str, prompt: str, seed: int, w: int, h: int, refs: list[Path], path: Path) -> None:
    t0 = time.time()
    if mock_mode():
        raw, model, attempts = mock_image(sid, seed, w, h), "mock-image", 1
    else:
        try:
            raw, attempts = with_retries(lambda: call_klein(prompt, seed, w, h, refs), attempts=3, what=f"klein {sid}")
            model = KLEIN
        except Exception as e:  # noqa: BLE001
            log_run(stage=kind, shot=sid, model=KLEIN, ok=False, error=str(e)[:300])
            print(f"  ! klein failed for {sid}, falling back to schnell (no reference images)", file=sys.stderr)
            raw, attempts = with_retries(lambda: call_schnell(prompt, seed), attempts=3, what=f"schnell {sid}")
            model = SCHNELL
    save_png(raw, path, w, h)
    log_run(stage=kind, shot=sid, model=model, seed=seed, width=w, height=h, refs=[p.name for p in refs],
            prompt_chars=len(prompt), attempts=attempts, latency_s=round(time.time() - t0, 2),
            cost_usd=0.0, ok=True, cache_hit=False, file=path.name)
    print(f"  + {sid} {kind} with {model} in {time.time() - t0:.1f}s")


def main() -> None:
    load_env()
    if not mock_mode():
        require_keys("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")
    sb = load_storyboard()
    style = sb["style"]
    ks = sb["export"]["keyframe_size"]
    w, h = ks["width"], ks["height"]
    tag = "mock" if mock_mode() else KLEIN

    # 1. Reference sheets: one neutral portrait per character.
    refs_dir = stage_dir("refs")
    refs: dict[str, Path] = {}
    for name, ch in sb["characters"].items():
        prompt = (f"character reference sheet, full body and face, plain warm beige background, "
                  f"{ch['description']}. {style['block']}")
        hsh = input_hash(prompt, ch["seed"], tag, w, h)
        p = refs_dir / f"{name}_{hsh}.png"
        if cached(p):
            log_run(stage="refs", shot=name, cache_hit=True, file=p.name)
        else:
            generate("refs", name, prompt, ch["seed"], w, h, [], p)
            clean_stale(refs_dir, name, p)
        refs[name] = p

    # 2. Keyframes, conditioned on the references of the characters in the shot.
    kdir = stage_dir("keyframes")
    for shot in sb["shots"]:
        cast = "; ".join(sb["characters"][c]["description"] for c in shot["characters"])
        prompt = f"{shot['framing']}: {shot['image_prompt']}. " + (f"Characters: {cast}. " if cast else "") + style["block"]
        shot_refs = [refs[c] for c in shot["characters"]]
        hsh = input_hash(prompt, style["seed"], tag, w, h, [p.name for p in shot_refs])
        p = kdir / f"{shot['id']}_{hsh}.png"
        if cached(p):
            log_run(stage="keyframes", shot=shot["id"], cache_hit=True, file=p.name)
            print(f"  = {shot['id']} keyframe cached")
            continue
        generate("keyframes", shot["id"], prompt, style["seed"], w, h, shot_refs, p)
        clean_stale(kdir, shot["id"], p)


if __name__ == "__main__":
    main()
