# Two faults overlapped: why chaos.py has a run lock

2026-10-10, about 19:35 UTC. `bank.py run control-payment-failure control-ad-cpu` and a live agent session
ran at the same time: the agent's `payment-kill` (started 1791660938) landed inside `control-ad-cpu`'s
fault window (1791660984 to 1791661104).

- `control-ad-cpu` rated **high** (expected low) and failed as a control: its window caught payment-kill's
  damage (payment errors 61 %, checkout 52 %, payment pod replaced).
- `payment-kill` picked up the ad CPU hog as an effect.

Both entries were put back to their earlier ratings in `bank.json`; the summaries here are the spoiled runs.
Fix: a cross-process lock (`chaos.exclusive`) held from injection to the end of the rating window; a
second fault is refused with "another fault is running".
