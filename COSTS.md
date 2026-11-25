# Costs and measurements

Everything ran on free tiers; actual spend is $0. The numbers below come from `runs.jsonl` (`latency_s`, `gpu_minutes`). Summarise them with:

```bash
python - <<'EOF'
import json, collections
rows=[json.loads(l) for l in open("runs.jsonl") if l.strip()]
agg=collections.defaultdict(lambda:[0,0.0,0])
for r in rows:
    if r.get("mock") or r.get("cache_hit"): continue
    a=agg[(r["stage"],r.get("model"))]; a[0]+=1; a[1]+=r.get("latency_s",0); a[2]+= (0 if r.get("ok",True) else 1)
for (s,m),(n,t,f) in sorted(agg.items()): print(f"{s:10} {str(m):45} calls={n:3} total={t:7.1f}s avg={t/max(n,1):5.1f}s failed={f}")
EOF
```

## Free limits found when I started

| Service | Limit stated | What I actually hit |
|---|---|---|
| Gemini API (TTS) | see AI Studio rate-limit page | Per-minute limit hit after 4 to 5 requests (HTTP 429); daily limit for gemini-3.8-flash-tts exhausted after about 24 requests (server asked to wait 19 h) |
| Cloudflare Workers AI | 10,000 neurons per day free | Not reached: 21 FLUX.2 klein images at 1024×1024 |
| Google Colab T4 | session limits vary | TODO |

## Per stage (real runs, 25 Nov 2026, from runs.jsonl)

| Stage | Model | Successful calls | Failed | Cache hits | Median latency | Total | GPU min | List-price equivalent |
|---|---|---|---|---|---|---|---|---|
| Narration | gemini-3.8-flash-tts | 15 | 9 (HTTP 429) | | 11.9 s | 221 s | 0 | TODO (Gemini TTS price × characters) |
| Narration | gemini-3.1-flash-tts-preview (rate-limit fallback) | 7 | 0 | | 24.3 s | 168 s | 0 | TODO |
| Reference sheets | FLUX.2 klein 4B | 4 | 3 (keys missing) | 8 | 13.5 s | 50 s | 0 | TODO (neurons × $0.011/1k beyond 10k/day free) |
| Keyframes | FLUX.2 klein 4B | 17 (11 + 5 + 1 redraws) | 0 | 16 | 16.6 s | 306 s | 0 | TODO |
| Shots | FFmpeg Ken Burns (local CPU) | 22 clips | 0 | | 3.5 s | 73 s | 0 | $0 |
| Music | procedural fallback (local CPU) | 3 | 0 | 1 | 17.7 s | 75 s | 0 | $0 |
| Assembly | FFmpeg (local CPU) | 4 | 0 | | 21.1 s | 97 s | 0 | $0 |

Actual spend: $0. Wasted calls: 22 narration calls produced lines that had to be discarded (FAILURES F8); 6 keyframes were redrawn after review (EXPERIMENTS E3).

## Offline baseline (mock run, local CPU, no model calls)

Measured on the build machine on 25 Nov 2026 with `make mock`: shots stage 45 s for 22 clips (about 2 s per clip), final assembly of both aspect ratios 58 s. Re-running after editing one shot: shots stage 4.2 s (2 clips). These are the floor for the CPU stages; model latency adds on top.

## Frontier comparison

TODO if the cohort opens a frontier lane (Nano Banana, Omni Flash, Lyria 3.5): same shot, same prompt, record cost and latency.
