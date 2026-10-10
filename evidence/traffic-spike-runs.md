# traffic-spike, two local runs (Arch box, 2026-10-10)

Command: `uv run python chaos.py run traffic-spike`
krkn: `krknctl run http-load --rate 1000/1s --number-of-pods 2 --chaos-duration 120s`, kill switch limits `error_rate 0.3`, `p95_ms 250`, `max_s 240`.

## Run 1: stopped by a person (`touch runs/STOP`)
```json
{
  "id": "traffic-spike",
  "scenario": "http-load",
  "aborted": true,
  "abort_reason": "STOP file",
  "first_bad_probe_to_abort_s": null,
  "abort_to_stopped_s": 0.2,
  "duration_s": 3.2,
  "baseline_p95_ms": 14,
  "impact": { "probes": 4, "failed": 0, "p95_ms": 6, "max_ms": 6 },
  "recovery_s": 0.0,
  "krkn_exit": -9,
  "krkn_failed": false,
  "krkn": {}
}
```
Shows the manual stop path: krkn killed and cleaned up 0.2 s after the STOP file appeared. It was stopped 3.2 s in, before the load pods started, so it shows no impact on the shop.

## Run 2: stopped by the kill switch (p95 breach)
```json
{
  "id": "traffic-spike",
  "scenario": "http-load",
  "aborted": true,
  "abort_reason": "p95_ms: 2 probes slower than 454 ms in last 5s, limit 250 ms",
  "first_bad_probe_to_abort_s": 2.6,
  "abort_to_stopped_s": 0.7,
  "duration_s": 30.4,
  "baseline_p95_ms": 15,
  "impact": { "probes": 29, "failed": 0, "p95_ms": 454, "max_ms": 1971 },
  "recovery_s": 1.9,
  "krkn_exit": -9,
  "krkn_failed": false,
  "krkn": {}
}
```
Raw files for this run: `evidence/traffic-spike-run2/` (`summary.json`, `events.jsonl`).

## Against the success criterion (kill switch <= 5 s after breach, shop back to baseline <= 60 s)
| Measure | Limit | Run 2 |
|---|---|---|
| first slow probe to abort decision | <= 5 s | 2.6 s |
| abort decision to krkn killed and cleaned up | (part of the 5 s) | 0.7 s |
| shop back to baseline | <= 60 s | 1.9 s |
| leftover krkn pods/containers | none | not re-checked in this paste |
