"""One command: validate -> narration -> radio cut -> keyframes -> shots -> music -> final film.

Usage:
  python pipeline/run_all.py            # whole film
  python pipeline/run_all.py --radio    # stop after the radio cut (narration + music on black)
  PIPELINE_MOCK=1 python pipeline/run_all.py   # offline dry run with placeholder media
Every stage skips work whose inputs have not changed, so a re-run after editing one shot
regenerates only that shot.
"""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(script: str, *args: str) -> None:
    t0 = time.time()
    print(f"\n== {script} {' '.join(args)}")
    r = subprocess.run([sys.executable, str(HERE / script), *args])
    if r.returncode != 0:
        sys.exit(f"stage {script} failed (exit {r.returncode}); fix it and re-run, finished stages are cached")
    print(f"== {script} done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    run("validate.py")
    run("narration.py")
    run("music.py")
    run("assemble.py", "--radio")
    if "--radio" in sys.argv:
        sys.exit(0)
    run("keyframes.py")
    run("shots.py")
    run("assemble.py")
    print("\nDone: outputs/film_9x16.mp4 and outputs/film_16x9.mp4")
