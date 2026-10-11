# How the scores work

Every number on the Agent page and in `report.md` comes from rules in [`judge.py`](../judge.py),
computed from what [`bank.py`](../bank.py) measured. The one exception is the model's own
estimate, and it's labelled that way.

| Number | Rates | Computed by |
|---|---|---|
| [Leverage](#leverage) | one finding: how weak this spot is | rules |
| [SLO points](#slo-points) | one fault: which promises to customers broke | rules |
| [Resilience score](#resilience-score) | the whole system, over the pool | rules (krkn's formula) |
| [Evidence check](#evidence-check) | one analyst note: how far to trust it | rules |
| [Model's own estimate](#models-own-estimate) | one model answer: how sure the model says it is | the model, unchecked |

## Leverage

**What:** how much damage per unit of push. It ranks the findings.

**Formula:**

```
leverage = impact ÷ strength
impact   = the measured tier:  high 3 · medium 2 · low 1
strength = how hard we pushed: mild 1 · targeted 2 · broad 3   (a pair: both faults added up)
```

Strength comes from the fault's own settings (`judge.strength`):
- **Broad:** a traffic flood, a CPU hog at 80 % or more, a memory hog at 50 % or more, 50 % packet loss or more, or 1 s of delay or more.
- **Mild:** the same node faults set lower.
- **Targeted:** one service killed, cut off or hijacked.

**Why:** a weakness is a big effect from a small push. Flooding the front door breaks any shop,
so it teaches little. 10 % packet loss breaking checkout is a real finding. Ranking by damage
alone would reward the strongest fault. krkn-ai's AI policy warns about exactly that:
"miscalculated fitness can drive the genetic algorithm toward excessively destructive or
ineffective scenarios".

**Example** (`bank.json`):

| Fault | Tier | Strength | Leverage |
|---|---|---|---|
| blast-loss: 10 % packet loss on the backend node | high | mild | 3 ÷ 1 = **3.0** |
| blast-latency: +200 ms on the backend node | medium | mild | 2 ÷ 1 = **2.0** |
| quote-garbage: the quote service answers nonsense | high | targeted | 3 ÷ 2 = **1.5** |
| cpu-starve: 100 % CPU on the backend node | medium | broad | 2 ÷ 3 = **0.67** |
| cart-wipe + traffic-spike | high | pair: 2 + 3 | 3 ÷ 5 = **0.6** |

The pair is as high as quote-garbage, but half of it is a traffic flood, so it ranks last.
At equal leverage, the bigger effect goes first, then a surprise (the planner predicted another
tier), then a new root cause before a repeat ("same cause as #N").

## SLO points

**What:** which promises to customers one fault broke, out of 15 points.

**Formula:** 7 SLOs. A fault keeps the points of every SLO no measured effect broke.

| SLO | Points | Broken by |
|---|---|---|
| customers get answers | 3, critical | errors or lost traffic at checkout or the frontend, or a customer page 10x slower or over 2 s |
| no data lost | 3, critical | carts emptied |
| the shop recovers | 3, critical | not healthy 120 s after the fault |
| the shop stays up | 3, critical | shop probes failing, or the kill switch tripped |
| other services answer | 1, warning | errors or lost traffic in an internal service |
| customers aren't 2x slower | 1, warning | a customer page 2x slower |
| nothing else restarts | 1, warning | another pod restarted or replaced |

**Why:**
- krkn's built-in score counts its own checks. It gave 100/100 to a fault that made the shop 66x slower ([decisions-and-lessons](decisions-and-lessons.md)), so ours counts what a customer feels.
- Critical 3 and warning 1 are krkn's own weights: an emptied cart matters more than a slow internal call.
- Slowness counts as broken answers past 10x or 2 s, because a shopper gives up long before the page fails.

**Example:**
- **quote-garbage, 11/15:** checkout errors went 0 % → 59 %, which breaks "customers get answers" (−3). Shipping errors went 0 % → 69 %, which breaks "other services answer" (−1).
- **blast-latency, 11/15:** checkout p95 went 48 → 1,880 ms. That is 2x slower (−1), and 39x is past the 10x line, so customers don't get answers either (−3).
- **cart-wipe, 12/15:** cart items went 1 → 0, which breaks "no data lost" (−3).

## Resilience score

**What:** how well the whole system held up across every fault in the pool, out of 100.

**Formula** (krkn's): `points kept ÷ points possible × 100`, summed over every fault run in
the session.

**Why:**
- It rates the system, not a fault, so it's never used to rank. Leverage does that.
- The pool is fixed when the session starts, so before and after a fix compare like with like.

**Example:**
- **Score:** a session over quote-garbage (11/15), blast-latency + catalog-db-cutoff (4/15) and cart-wipe + traffic-spike (5/15) keeps 20 of 45 points, a score of **44/100**.
- **The verified fix:** catalog-kill scored **4/15** before the fix (the shop wasn't healthy 120 s later). After 2 replicas and a preStop it scored **15/15**, 3 runs of 3 ([evidence](../evidence/catalog-kill-fix/README.md)). Any pool that includes it scores higher.

## Evidence check

**What:** how far one analyst note can be trusted. Rules work it out by comparing the note with
the measurement, not by asking the model.

**Formula:** start at 100, take off points for each check that fails, and stop at 0.

| Check | Fails when | Points |
|---|---|---|
| no claim contradicts the measurement | it says "no data loss", "no impact", "fully recovered", "SLOs held" or "stayed up" and the bank measured otherwise | −40 each |
| names what broke | it names no service that broke, and not the target | −30 |
| big enough sample | the deciding error ratio rests on fewer than 20 calls | −20 |
| cites evidence | it cites nothing (a citation counts only if that file exists) | −10 |

**Why:** a model's note reads just as fluently when it's wrong. These are the checks a reviewer
would make by hand:
- Does it contradict the numbers?
- Does it say what broke?
- Is the sample big enough?
- Does it cite anything?

The ✓/✗ list behind the "?" shows each check.

**Example:**
- **100 %:** the blast-latency + catalog-db-cutoff note contradicts nothing, names ad, checkout and product-catalog, and cites `bank.json` and the service facts.
- **80 %:** the blast-loss note is grounded, but checkout's error ratio rests on 9 calls (−20).
- **20 %:** the cart-wipe note says "no data loss, SLO preserved" while the bank measured cart items 1 → 0. That's two claims disproved (−40 −40).

## Model's own estimate

**What:** the confidence the model reports for its own answer, shown as a percentage. It appears
on the planner's queue, the analyst notes and the fix cards.

**Where it comes from:** each model replies in JSON with a `confidence` field between 0 and 1.
The prompt asks for "your own probability, 0 to 1, that you are right; judge it from the
evidence". Nothing checks it.

**Why we show it, and why it's labelled unchecked:**
- **Shown:** Bosch's AI code of ethics asks for a confidence next to every AI output.
- **Unchecked:** a model's self-reported number isn't calibrated. An earlier prompt's example said 0.6, and one model copied it into every note ("always 60 %"). The evidence check is the headline, and the model's estimate sits under it.

**Example:** the blast-latency + catalog-db-cutoff note reads "Evidence check 100 %" with
"Model's own estimate (unchecked) 85 %" under it. A fix card reads "model's own estimate 93 %
· from the fix catalog".

## Also on the results page

- **Root causes found:** distinct root-cause tags rated medium or high and found by a mild or targeted fault. Pairs and broad faults don't count, because brute force proves nothing.
- **Planner hit rate:** how often the planner's predicted tier matched the measured one. In replay it plans blind. In a live session it has seen earlier ratings, so a hit there is partly memory.
