# First live pair: blast-latency + catalog-kill (#20)

`uv run python bank.py run blast-latency+catalog-kill`, 2026-10-10 20:36:45 to 20:39:15 UTC (150 s).
Both faults under one kill switch (the stricter limits: errors 50 %, p95 2000 ms): +200 ms on everything
leaving the backend node, and one product-catalog pod killed in the middle of it.

| | Tier | Effects |
|---|---|---|
| blast-latency alone (`bank.json`) | medium | latency only (checkout p95 48 -> 3650 ms, frontend 33 -> 996 ms) |
| catalog-kill alone, after the #19 fix | low | none |
| **the pair** | **medium** | latency only (checkout p95 48 -> 1670 ms, frontend 34 -> 979 ms); no errors, 0/150 shop probes failed |

- The pair is no worse than the latency alone: the #19 fix (2 replicas + preStop) still holds when the
  network is slow. The killed pod was back in 2.4 s (krkn); damage gone within 3 min of the end.
- Both parts injected: `parts` in `summary.json` (both krkn exit 0, no tc errors).
- Nothing left behind: no krkn helper pods, no new `krknctl` containers (the two exited ones are from
  Day 1), no netem rules on chaos-worker (`tc qdisc show`: noqueue only).
- Not the pair's doing: grafana was OOMKilled at 20:35:43, a minute before the pair started, on the
  steady node. Like the ad service, it runs out of memory on its own.
