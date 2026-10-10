---
name: submit-ready
description: Pre-submission gate for a hackathon challenge - proves the fix meets the success criterion, the repo runs from a fresh clone, no secrets leak, the UI matches DESIGN.md, and the writeup and fallback exist. Use at the 7:00 code freeze, before presenting or submitting, or when the user says "submit", "code freeze", "are we ready", "final check", or runs /submit-ready.
---

# submit-ready

Run every check and report a table: check, PASS/FAIL, one line of evidence.
It is code freeze: only fix what breaks the demo, and ask before changing
any code. Writing tests, SOLUTION.md and evidence files is fine.

Read `CHALLENGE.md` first for the success criterion, baseline, repro command
and milestone name.

1. **Criterion.** Run the repro (through the `test-runner` agent if the output
   is long). Compare with the target and the baseline. Write
   `evidence/results.md`: command, before, after, date.
2. **Regression tests.** `gh issue list --milestone "<milestone>" --label
   phase:fix --state all`. Every fixed piece needs a test that fails without
   its fix. Then `uv run pytest -q` must pass.
3. **UI smoke test.** If there is a Streamlit app, `tests/test_app.py` must
   exist and pass. Create it if missing:

   ```python
   from streamlit.testing.v1 import AppTest

   def test_app_runs():
       at = AppTest.from_file("app.py").run(timeout=60)
       assert not at.exception
   ```

4. **Design drift.** `node scripts/check-tokens.mjs` exits 0 (skip if the
   project has no UI).
5. **Secrets.**
   - `git ls-files .env` prints nothing.
   - `git grep -nE "sk-ant-[A-Za-z0-9_-]{10,}|AKIA[0-9A-Z]{16}|(api[_-]?key|secret|token)\s*=\s*['\"][^'\"]{8,}"`
     finds nothing outside `.env.example`.
   - `.env.example` lists every variable the app reads, with empty values.
6. **Fresh clone.** Everything is committed and pushed (`git status` clean,
   not ahead of origin). Then clone into a temp folder and run
   `uv sync` and the repro there. This is what judges will do.
7. **Run steps.** README states how to run the app and the repro, and those
   commands are the ones that just worked.
8. **Offline fallback.** Ask the user whether the demo video is recorded
   (Windows: Win+Alt+R with Xbox Game Bar, or OBS). If the app needs the
   network or an API key, the video is the fallback.
9. **Writeup.** `SOLUTION.md` with: root cause, the fix, evidence (numbers
   from step 1), impact for Bosch, next steps (from the `out-of-scope`
   issues). Draft it if missing.
10. **Responsible AI.** SOLUTION.md names the human-oversight mode from
    Bosch's AI code of ethics (people are the ultimate arbiter of AI-based
    decisions): human-in-command (AI only advises), human-in-the-loop (AI
    decides, a person can override), or human-on-the-loop (parameters set
    in advance, engineers keep reviewing).
11. **Issues.** In the milestone, only `out-of-scope` issues are still open
    and the Polish and Pitch task lists are ticked.

Finish with the blockers (FAIL rows) in order of demo risk, then the next
step: "make the 5-slide deck from SOLUTION.md with the pptx skill:
problem, root cause, fix + evidence, impact for Bosch, responsible AI and
next steps".
