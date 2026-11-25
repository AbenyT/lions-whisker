"""Shared helpers: storyboard loading and validation, caching, retries, run logging.

Every stage imports this module. The rules it enforces:
- storyboard.json is validated against schema/storyboard.schema.json before any work.
- Each output file name carries a hash of the inputs that produced it, so a re-run
  regenerates only what changed (cache hit = file already exists).
- Every model call (and every cache hit) is written as one JSON line to runs.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "outputs"
RUNS = ROOT / "runs.jsonl"
STORYBOARD = ROOT / "storyboard.json"
SCHEMA = ROOT / "schema" / "storyboard.schema.json"
FONTS = ROOT / "fonts"

# List-price equivalents used for COSTS.md. We pay nothing on the free tiers; these
# estimate what the same call would cost on a paid plan. Edit if prices change.
PRICE_USD = {
    "cloudflare_neuron": 0.011 / 1000,   # Workers AI, per neuron beyond the free 10k/day
    "gemini_tts_per_1k_chars": 0.0,      # set from the Gemini pricing page when you check it
    "gpu_t4_per_hour": 0.35,             # typical cloud T4 on-demand price
}


def load_env() -> None:
    """Load KEY=VALUE pairs into os.environ (no extra dependency).

    Reads .env, then .env.txt (Windows Notepad often saves .env as .env.txt). Empty values are
    ignored, so a filled-in value in either file wins over a blank line in the other.
    """
    for name in (".env", ".env.txt"):
        env = ROOT / name
        if not env.exists():
            continue
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip().strip('"').strip("'")
            if v and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v


def require_keys(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}. Open .env in Notepad, fill them in, save as '.env' "
                 f"(Save as type: All files), and run again.")


def mock_mode() -> bool:
    return os.environ.get("PIPELINE_MOCK", "0") == "1"


def load_storyboard(validate: bool = True) -> dict:
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    if validate:
        import jsonschema
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.validate(sb, schema)
        ids = [s["id"] for s in sb["shots"]]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate shot ids: {ids}")
        for s in sb["shots"]:
            for c in s["characters"]:
                if c not in sb["characters"]:
                    raise ValueError(f"{s['id']}: unknown character '{c}'")
    return sb


def input_hash(*parts) -> str:
    """Stable short hash of any JSON-serialisable inputs."""
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:10]


def log_run(**fields) -> None:
    fields.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    fields.setdefault("mock", mock_mode())
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fields, ensure_ascii=False) + "\n")


def with_retries(fn, *, attempts: int = 4, base_delay: float = 3.0, what: str = "call"):
    """Call fn(); on exception wait 3s, 6s, 12s ... and try again. Re-raise at the end."""
    last = None
    for i in range(attempts):
        try:
            return fn(), i + 1
        except Exception as e:  # noqa: BLE001 - we log and retry any provider error
            if type(e).__name__ == "RateLimited":
                raise  # the caller waits the server's retryDelay instead of our short backoff
            last = e
            msg = str(e)[:300]
            print(f"  ! {what} failed (attempt {i + 1}/{attempts}): {msg}", file=sys.stderr)
            if i < attempts - 1:
                time.sleep(base_delay * (2 ** i))
    raise last


def cached(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def clean_stale(folder: Path, prefix: str, keep: Path) -> None:
    """Remove older versions of the same shot so outputs/ only holds the current one."""
    for p in folder.glob(f"{prefix}_*"):
        if p != keep and p.suffix == keep.suffix:
            p.unlink()


def ffmpeg(*args: str) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")


def duration_of(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def require_tools() -> None:
    for t in ("ffmpeg", "ffprobe"):
        if not shutil.which(t):
            sys.exit(f"{t} not found on PATH. Install FFmpeg first (see README).")


def stage_dir(name: str) -> Path:
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def timeline_path() -> Path:
    return OUT / "timeline.json"
