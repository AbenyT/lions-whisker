"""Summarise runs.jsonl: calls, failures, cache hits and latency per stage and model.

Usage: python pipeline/stats.py            (real runs only)
       python pipeline/stats.py --all      (include mock runs)
Prints a Markdown table you can paste into COSTS.md.
"""
import collections
import json
import sys
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs.jsonl"


def main() -> None:
    rows = [json.loads(l) for l in RUNS.read_text(encoding="utf-8").splitlines() if l.strip()]
    if "--all" not in sys.argv:
        rows = [r for r in rows if not r.get("mock")]
    agg = collections.defaultdict(lambda: {"ok": 0, "fail": 0, "hit": 0, "lat": []})
    for r in rows:
        a = agg[(r.get("stage"), r.get("model") or "-")]
        if r.get("cache_hit"):
            a["hit"] += 1
        elif r.get("ok") is False:
            a["fail"] += 1
        else:
            a["ok"] += 1
            a["lat"].append(float(r.get("latency_s") or 0))
    print(f"{len(rows)} log lines, {rows[0]['ts'] if rows else '-'} to {rows[-1]['ts'] if rows else '-'}\n")
    print("| Stage | Model | OK | Failed | Cache hits | Median s | Total s |")
    print("|---|---|---|---|---|---|---|")
    for (stage, model), a in sorted(agg.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))):
        lat = sorted(a["lat"])
        med = lat[len(lat) // 2] if lat else 0
        print(f"| {stage} | {model} | {a['ok']} | {a['fail']} | {a['hit']} | {med:.1f} | {sum(lat):.0f} |")
    errors = collections.Counter((r.get("stage"), str(r.get("error", ""))[:70]) for r in rows if r.get("ok") is False)
    if errors:
        print("\nMost common failures:")
        for (stage, err), n in errors.most_common(6):
            print(f"- {n} x {stage}: {err}")


if __name__ == "__main__":
    main()
