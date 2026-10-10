# Hackathon day: agent guide

Bosch AI Innovation Challenge. Each day brings one challenge: debug it, fix it
and present it within 9 hours. The judging rubric decides the score.
The day's challenge, success criterion and pieces: @CHALLENGE.md

## Mission
- Fix what the success criterion and the top rubric criteria measure. Nothing else.
- Spot another problem? Tell the user in one line and suggest an
  `out-of-scope` issue. Do not fix it, even if it is quick.
- Work on a piece only if it is in CHALLENGE.md. Otherwise ask first.

## Planning
- The only planner is `/challenge-triage`, run in plan mode. Do not start
  superpowers brainstorming, writing-plans, executing-plans,
  subagent-driven-development or git worktrees; that ceremony doesn't fit
  a 9-hour day. From superpowers use only `systematic-debugging` (root
  causes) and `verification-before-completion` (before claiming it works).
- No branches: everyone works on `main`.

## Piece loop (one GitHub issue = one piece)
1. `git pull --rebase`, then `gh issue view <n>`.
2. Reproduce: run the piece's repro and watch it fail. No repro, no fix.
3. Find the root cause, then make the smallest fix that addresses it.
4. Add a regression test in `tests/` that fails without the fix.
5. Verify. Run one quick test directly; send the full suite, pipeline or
   evaluate run to the `test-runner` agent so long logs stay out of context.
6. `git commit -m "<what changed> (Fixes #<n>)"`, one piece per commit.
7. `git push`. The developer approves it, and the push closes the issue.
- After **2 failed fix attempts** on one piece, stop and say: "Stuck on #<n>.
  Switch to plan mode (Shift+Tab) or `/model opus` for this piece." Do not
  try a third time on your own.
- A piece running 50% over its estimate: say so and propose cutting it.

## Clock (start time is in CHALLENGE.md)
| Time | Phase |
|---|---|
| 0:00-0:45 | Triage in plan mode |
| 0:45-5:30 | Piece loop |
| 5:30 | **Feature freeze**: no new pieces |
| 5:30-7:00 | Polish: before/after evidence, then UI one feature at a time |
| 7:00 | **Code freeze**: `/submit-ready`; only fixes for a broken demo |
| 7:00-9:00 | SOLUTION.md, slides, rehearsal |

## How to work
- Think before coding: state assumptions; if the challenge is ambiguous, ask.
- Simplicity first: the least code that solves it, no speculative features.
- Surgical changes: touch only what the piece needs, no drive-by refactors.
- Goal-driven: name the check (test or metric) first; done means it passes.

## Stack
- Python with `uv`: `uv sync`, `uv run <cmd>`, `uv add <pkg>` (the developer
  approves new dependencies). Tests: `uv run pytest -q`.
- Run everything from the repo root. Streamlit reads `.streamlit/config.toml`
  from the working directory: `uv run streamlit run app.py`.
- Secrets live in `.env` (gitignored; you are denied reading it). List the
  variable names in `.env.example`.
- Every LLM call goes through `llm()` in `llm.py`, so the provider can be
  swapped in one place (for example, a model Bosch provides).

## Bosch angle
- Prefer the data, APIs and tools the organizers provide over outside ones.
- Bosch's AI code of ethics: people are the ultimate arbiter of AI-based
  decisions. Keep a human in control and show confidence or sources next to
  every AI output.

## Design rules (UI only after the fix works)
- `DESIGN.md` is the source of truth for every visual decision. Read it
  before UI work and use only its tokens: colors, type scale, spacing,
  radius, chart colors. Need a new value? Add the token to DESIGN.md first.
- Build one piece of UI at a time and finish it before the next. After each:
  `node scripts/check-tokens.mjs`, fix what it finds, then run the
  `design-reviewer` agent on http://localhost:8501 and apply its high and
  medium fixes.
- Never: gradients or gradient text, Inter/Roboto/Arial, emoji in headings,
  hype copy ("supercharge", "seamless"), lorem ipsum, fake numbers.
- Streamlit: theme tokens live in `.streamlit/config.toml` `[theme]` at the
  repo root. No hex values in `.py` files and no CSS through
  `st.markdown(..., unsafe_allow_html=True)`. Layout comes from `st.columns`,
  `st.container(border=True)`, `st.metric`, `st.tabs`. Charts use the
  theme's `chartCategoricalColors` (Plotly/Altair `theme="streamlit"`);
  don't pass colors by hand.
- If the challenge is a React/Next frontend instead: shadcn/ui restyled to
  the tokens, no raw Tailwind palette classes (`bg-blue-500`), no arbitrary
  values (`text-[13px]`), no cards inside cards.
