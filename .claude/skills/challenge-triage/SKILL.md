---
name: challenge-triage
description: Turn a hackathon challenge statement and judging rubric into a time-boxed fix plan - reproduce or baseline the problem, break it into pieces, keep only the pieces that move the score, then write CHALLENGE.md and create the day's GitHub milestone and issues. Use at the start of each challenge day, when the user pastes a challenge statement or rubric, or says "triage", "kickoff", "break this down", "what should we fix", or runs /challenge-triage. Run it in plan mode.
---

# challenge-triage

Input from the user: $ARGUMENTS

You need the **challenge statement** and the **judging rubric**. Look in the
repo first (`CHALLENGE_STATEMENT*`, `RUBRIC*`, `README*`, anything the
organizers dropped in). If the rubric is missing, ask for it once; if there is
none, rank by the stated success criterion first and demo quality second.

The day is 9 hours. Fixing runs 0:45-5:30, so the in-scope estimates must sum
to **at most 3.5h** (the rest is a 25% buffer for surprises).

## Part 1 - in plan mode (read and run, change nothing)

1. **Goal and score.** In two lines: what is broken or asked, and the
   measurable success criterion (metric + target, or the rubric's top
   criterion). List the rubric criteria with their weights.
2. **Reproduce or baseline.** Find the command that measures the criterion
   (evaluate script, test suite, pipeline run) and run it. Record the exact
   command and the baseline number. If nothing runs, getting it to run is
   piece #1.
3. **Find the pieces.** Read the code along the path the criterion depends
   on. For every symptom, trace it to a root cause before calling it a piece
   (use `superpowers:systematic-debugging` if available). Two symptoms with one
   cause are one piece. For each piece note:
   evidence (file:line, a log line or a number), what it does to the
   criterion, an estimate in 30-minute steps, and the files it touches.
   Also note problems that do **not** affect the criterion (slow code,
   warnings, style); they are findings, not pieces.
4. **Select.** A piece is in scope only if it moves the success criterion or
   a top-weighted rubric criterion. Rank in-scope pieces by impact per hour
   and cut from the bottom until the estimates fit in 3.5h. Everything else
   goes to out of scope with a one-line reason. Do not keep a finding in
   scope because it is quick.
5. **Split by file.** Give each in-scope piece its file set. Pieces with
   disjoint files can run in parallel (one teammate each). Pieces sharing a
   file are sequenced: mark the later one "after #<earlier>".
6. **Present the plan** for approval: the pieces table (piece, evidence,
   impact, estimate, files, parallel group), the out-of-scope list, the
   estimate total, and the day's clock timeline (ask for the start time, or
   use now). Exit plan mode only when the user approves.

## Part 2 - after approval

7. **Write `CHALLENGE.md`** (replace the file; keep it under 60 lines,
   CLAUDE.md imports it into every session):

   ```markdown
   # Day <N>: <short name>
   **Goal:** <one line>
   **Success criterion:** <metric> <op> <target> - baseline <value>
   **Repro:** `<exact command>`
   **Rubric:** <criterion (weight)>, ...
   **Start:** <HH:MM> - feature freeze <+5:30>, code freeze <+7:00>, present <+9:00>

   ## Pieces (in scope, total <X>h)
   | Issue | Piece | Files | Est | Parallel |
   ## Out of scope
   - #<n> <finding> - <why it doesn't move the score>
   ```

8. **GitHub labels and milestone** (safe to re-run):

   ```bash
   gh label create "phase:fix"    --color 1D76DB --force
   gh label create "phase:polish" --color FBCA04 --force
   gh label create "phase:pitch"  --color 0E8A16 --force
   gh label create "out-of-scope" --color BFBFBF --force
   gh api repos/{owner}/{repo}/milestones -f title="Day <N>: <short name>"
   ```

   If the milestone already exists, reuse it.

9. **Issues**, all in the milestone (`--milestone "Day <N>: <short name>"`):
   - One per in-scope piece, label `phase:fix`, title = the piece. Body:
     Problem, Evidence, Repro, Acceptance (the test or metric that proves it
     fixed), Estimate, Files, Parallel group / "after #n".
   - One per out-of-scope finding, label `out-of-scope`. Body: the finding,
     why it was skipped, the suggested next step. These become the pitch's
     "what we'd do next" line.
   - `Polish` (label `phase:polish`) with a task list: before/after evidence
     captured; reference image chosen; `/design-from-ref`; each UI feature
     built and checked by `design-reviewer`; `node scripts/check-tokens.mjs`
     clean.
   - `Pitch` (label `phase:pitch`) with a task list: `/submit-ready` passed;
     SOLUTION.md written; offline fallback video recorded at code freeze;
     5-slide deck; human-oversight mode named; two rehearsals.

   Pass bodies with `--body-file -` and a heredoc so newlines survive.
10. Put the issue numbers into the CHALLENGE.md tables.
11. **Assignees.** List people with
    `gh api repos/{owner}/{repo}/assignees --jq '.[].login'`, ask who takes
    which parallel group, then `gh issue edit <n> --add-assignee <login>`.

## Report

Five lines at most: the criterion and baseline, the in-scope pieces with the
estimate total, the number of out-of-scope findings, the parallel groups, and
the next step ("each person: `gh issue view <n>`, then fix it").
