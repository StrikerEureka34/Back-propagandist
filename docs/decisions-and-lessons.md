# Decisions & Lessons

Newest entry on top. Plain language. Each claim points at a commit or a measured result.

## 2026-10-11: the agent runs safely, and the fix is proven

**What changed.** The AI agent now runs real experiments end to end, with a person approving every one.
The catalog fix is proven, two new faults found a serious checkout flaw, and several safety gaps
were closed. Commits: 2436357, 7733d05, 2b436eb, b62a25b, e77798f, 02dcb48.

**Decisions and why**

- **Prove the fix by re-running the same fault.** We gave the product catalog a second copy and a
  10-second goodbye before shutdown. Killing it went from "shop broken for 2 minutes" to "no visible
  effect", three times out of three (2436357).
- **Let the AI suggest the next test, but code decides.** After each run the analyst may propose one
  follow-up. Rules allow at most two per session, never a broad fault, never a repeat, and a person
  still approves it. A list of allowed faults stops it from inventing names (1697024).
- **Only pair faults when the pair should teach something.** Forcing a pair into every session was
  tried and dropped: two faults that just add up waste a run (4ab75c4).
- **Give the person control at every step.** An emergency stop ends the whole session; drag and
  drop changes the run order; one fault at a time on the machine (f9fc275, c53fc28, 0c9a479).

**Results**

- Customers can be charged and then have their order fail: checkout charges the card before it
  ships and has no refund. When shipping failed, 10 of 12 orders broke while all 14 charges went
  through (02dcb48).
- Six faults rate high, all found by targeted faults. Both known-answer controls passed the same day
  (2b436eb). Running two faults together works and cleans up after itself (7733d05).

**Lessons learned**

- **"Stopped" is not "gone".** The kill switch reported a stop, but a network delay stayed on the
  server for 8 minutes. Cleanup now removes it, and we check what the shop does, not the exit code
  (b62a25b).
- **A dirty "before" hides real damage.** A fault started three minutes after another was stopped
  looked harmless, because the "normal" window already held the earlier damage. Runs now wait for
  a quiet window first (e77798f).
- **Two faults at the same time spoil both results.** One overlap made a calibration check fail.
  Now only one fault can run at a time (0c9a479).
- **An AI asked to pick from a list must be shown the list.** Without it, every suggestion was a
  made-up name and nothing ran.

**Open decisions**

- One agent session still has to find three root causes on its own (the success criterion).
- The real fix for the checkout flaw (refund, or ship before charging) lives in the shop's code,
  which we don't change; it goes in the report as a recommendation.

## 2026-10-10 (evening into 2026-10-11): Day 2 fault bank

**What changed.** We built a "fault bank": a catalogue of 13 ways to break the shop, each one actually
run against it, measured, and rated high, medium or low by the damage customers would feel. We added
a second machine (node) to the test cluster so network faults have a network to slow down, and the
live dashboard now shows every service's health, not just one page.
Commits: 2caf468, f6603bb, 3449c40, 33e2c35, 84c5413, 72e53b2, 34d0f9f (the last one is not pushed yet).

**Decisions and why**

- **Break the shop from the outside, not with its built-in "failure switches".** The demo app ships
  with switches that make it fail on purpose. We tried them first, then dropped them from the bank:
  their outcome is written into the demo, so running them proves nothing a judge doesn't already know.
  Real trouble comes from outside: a machine dying, a slow network, a dependency answering nonsense.
  We kept two switches only as a calibration check. If "every payment fails" ever stops rating high,
  the measuring tool is broken, not the shop. Both checks passed on every run.
- **Rate faults by measured damage, never by guess.** Each fault is compared with a quiet period just
  before it: errors, slowness and lost traffic per service, lost shopping carts, restarted parts.
- **Add a second node, with a fixed layout.** Traffic between parts on the same machine never touches
  the network, so a "slow network" fault did nothing on one machine. Monitoring sits on the safe node,
  so a fault can never blind the kill switch. The rebuild cost about 30 minutes, mostly re-downloading
  software, and wiped the day's monitoring history (Day 1 evidence was already saved as files).
- **Allow one unsigned component, for one test only.** The tool's "dependency answers garbage" fault
  uses a component its makers never signed. We allowed it for that single test; everything else is
  still verified.

**Results (commit 72e53b2)**

- High: payment control, cart wipe (every cart lost), catalog killed, catalog loses its database,
  quote service answers garbage (over half of checkouts fail while the shop looks healthy), 10%
  packet loss on the backend node (checkouts fail and take 9.6 s).
- Medium: +200 ms network delay (checkout 76x slower), CPU starvation, recommendation unreachable
  (shop 66x slower, though nothing errors).
- Low: memory pressure, kafka killed, payment killed (back in under a second), ad CPU control.
- The chaos tool's own "resiliency score" gave 100/100 to a fault that made the shop 66x slower.
  Its score checks its own rules, not what a customer feels.

**Lessons learned / what to do differently**

- **A tool saying "pass" is not proof anything happened.** The chaos tool reported success for two
  network faults that never ran (it silently built broken commands), and our bank rated them
  "no effect". Now every result needs positive evidence of the fault, and we check its logs for
  the errors it hides.
- **Our own clean-up can cause the damage we measure.** Replacing a part after a network fault left
  the storefront talking to an address that no longer existed. Recommendations vanished for about
  15 minutes after a 2-minute fault. The underlying weakness is real (the storefront never checks
  that its connections are still alive), but we caused this instance. The clean-up now only replaces
  parts when a run was cut short.
- **Measure long enough to see the damage.** Monitoring data arrives once a minute. Windows shorter
  than about two and a half minutes read "no traffic" where there was plenty. Damage also often outlasts the
  fault: the catalog came back in seconds while the shop stayed broken for minutes.
- **One page is not the shop.** The original health check watched one product page and saw nothing
  during a payment outage, a garbage dependency, or lost carts. Per-service measurement caught all of them.
- **About an hour went on re-runs.** Most of that was bugs that would have produced wrong results
  with any fault source. Each fix now has an automatic test (42 pass), so these won't come back.

**Open decisions**

- Recovery time is still "not measured" for 8 of 13 faults: the next fault started 70 seconds later.
  New runs wait for damage to clear first. Re-run planned for Day 2 morning (about an hour).
- Fix candidate for "fix and re-run": make the storefront detect dead connections (a keep-alive
  check), then re-run catalog-kill and recommendation-cutoff to show the shop recovering in seconds.
- Still on the list: the AI search tool's own run (krkn-ai), and turning its best finds into bank entries.
- Commit 34d0f9f (recovery measurement) is held locally until the next push is approved.
