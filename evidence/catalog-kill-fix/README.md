# catalog-kill: before and after the fix (#19)

**Fix:** product-catalog `replicas: 2` (`k8s/otel-values.yaml`) plus a 10 s `preStop` sleep
(`k8s/product-catalog-patch.yaml`, applied with `kubectl patch` because the chart has no lifecycle field).

| Run | Tier | Shop probes failed | Kill switch | Pod back (krkn) |
|---|---|---|---|---|
| before (`before-72e53b2.json`, 1 replica) | **high** | 3 / 26 | tripped | shop not healthy 120 s after |
| after run 1 (`after-run1/`) | **low** | 0 / 37 | no | 3.3 s |
| after run 2 (`after-run2/`) | **low** | 0 / 41 | no | 6.6 s |
| after run 3 (`after-run3/`) | **low** | 0 / 33 | no | 2.8 s |

Two tiers lower, three runs out of three.

## Why the fix (log check, times UTC, 2026-10-10)
- 17:27:28.6 krkn deletes the only catalog pod; the replacement logs "gRPC server started" at 17:27:32.5.
- The catalog served 22 calls in the next two minutes (normally ~900): its callers couldn't reach it.
- 17:29:43 the frontend logs 224 failures in one second: `14 UNAVAILABLE: No connection established.
  Last error: connect ETIMEDOUT 10.96.114.99:8080` (the product-catalog Service IP).
- The frontend's reconnect went to the dead pod's IP and the SYN was dropped. With no gRPC connect
  timeout, every catalog request waited for Linux's SYN retries (`tcp_syn_retries` = 6, about 127 s).
- Applying the patch reproduced it without krkn: the rollout replaced pods that had no `preStop` yet
  and the shop returned 504 for about 2 minutes (18:58 to 19:00:52).

## Caveats, stated plainly
- **Baseline slip.** The three after-runs started at 19:01, not 19:06 as intended (a wrong timestamp
  in the driver), so their recorded baseline (18:56-19:01) overlaps the rollout outage. Re-rated against
  a clean window (18:28-18:33, healthy, before the rollout): all three are still **low**, with **no
  effects at all**. The "ad p95" lines in the run 2 and 3 entries come from the dirty baseline.
- **The real fix is in the client.** The frontend should time out and retry instead of hanging on one
  connect. That needs a rebuilt frontend image. The replicas + `preStop` fix removes the trigger
  (routing to a dying pod) for planned deletes. A pod that dies without warning (OOM, node loss) can
  still strand the frontend.
- The pool's resilience score before and after is computed by `judge.py` (#18), not here.
