# How to run a hackathon day with this kit

Built for the Bosch AI Innovation Challenge: two days, a new challenge each
day, 9 hours to debug it, fix it and present it. The kit helps you **fix what
the judges measure and nothing else**, on a clock, as a team.

| File | What it is |
|---|---|
| `CLAUDE.md` | Rules Claude follows every session (mission, piece loop, clock, design rules) |
| `CHALLENGE.md` | Today's blueprint, written by `/challenge-triage` |
| `.claude/skills/challenge-triage/` | 0:00 kickoff: rubric, reproduce, split into pieces, GitHub issues |
| `.claude/skills/submit-ready/` | 7:00 gate: metric, tests, fresh clone, secrets, writeup |
| `.claude/skills/design-from-ref/` | Pinterest image or URL to `DESIGN.md` and the Streamlit theme |
| `.claude/agents/design-reviewer.md` | Screenshots the app and returns a ranked fix list (Sonnet) |
| `.claude/agents/test-runner.md` | Runs tests and reports only failures and the metric (Haiku) |
| `DESIGN.md`, `scripts/check-tokens.mjs` | Design tokens and the drift check |
| `llm.py` | The one place every LLM call goes through |
| `.claude/settings.json`, `.mcp.json` | Models, permissions, plugins, Playwright |

---

## 1. One-time setup (each teammate, about 20 minutes)

1. **Install** Claude Code (VS Code extension or CLI), git, the GitHub CLI
   (`gh auth login`), Node 22+, and uv:
   - Windows: `winget install --id=astral-sh.uv -e`
   - macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Get access.** The repo owner runs, once per teammate:
   `gh api -X PUT repos/StrikerEureka34/Hackathon-toolkit/collaborators/<their-login> -f permission=push`
3. **Clone and install:**
   ```bash
   gh repo clone StrikerEureka34/Hackathon-toolkit
   cd Hackathon-toolkit
   uv sync
   uv run streamlit skills        # Streamlit's own agent skills
   cp .env.example .env           # then paste your ANTHROPIC_API_KEY into .env
   ```
4. **Open the folder in VS Code and start Claude.** Accept these prompts:
   - **Trust this folder.** Until you do, the allow rules and the plugin
     marketplaces in `.claude/settings.json` do nothing.
   - **Install plugins:** `document-skills` and `claude-api` (from
     anthropics/skills) and `superpowers`.
   - **Approve the `playwright` MCP server.**
5. **Check it worked:**
   - `/mcp` shows playwright connected.
   - `/agents` shows design-reviewer on sonnet and test-runner on haiku.
   - `/model` shows opusplan.
   - Typing `/` lists `challenge-triage`, `submit-ready` and `design-from-ref`.

**What Claude will ask you about:** file edits (press Shift+Tab to switch to
accept-edits for a session if you prefer), commits, pushes, creating or
closing issues, new dependencies, and any command beyond tests and read-only
git. These stay with the developer on purpose. Tests (`uv run pytest`),
`uv run streamlit run`, the token check and read-only git run without asking.

## 2. Before the event

- **Ask the organizers:**
  1. Are AI coding tools allowed?
  2. May Bosch data be sent to an external API?
  3. What does the venue network allow (proxy, blocked sites)?
  4. Do they provide a model or API? If so, change only `llm()` in `llm.py`.
- **Save 2-3 Pinterest references** into `refs/`: full-page dashboard
  screenshots, PNG or JPG.
- **Pick roles:** a triage driver (runs 0:00-0:45), fixers, and a pitch owner
  (starts SOLUTION.md at 5:30).
- **Run a mock day, timed.** One teammate seeds 2-4 bugs in a fresh repo
  made from the template, only some of which break the stated metric. The
  others follow section 3 blind. Afterwards, `/usage` shows what each agent
  cost. `bosch-mock-day` is the practice repo from the kit's own test run.

## 3. Event day

The clock starts when the challenge is released.

### 0:00 - Create the day repo (repo owner)
```bash
gh repo create bosch-day1 --template StrikerEureka34/Hackathon-toolkit --private --clone
cd bosch-day1
gh api -X PUT repos/StrikerEureka34/bosch-day1/collaborators/<login> -f permission=push   # per teammate
```
Copy the organizers' files into the repo root, then commit and push them.
Everyone else:
`gh repo clone StrikerEureka34/bosch-day1`, `cd bosch-day1`, `uv sync`,
`cp .env.example .env`. Then open the folder in VS Code and trust it.

**Get the judging rubric now.** It decides what counts as a fix.

### 0:05 - Triage (driver, plan mode)
Press Shift+Tab until the mode shows **plan**. Plan mode runs Opus 5.5 at
xhigh effort. Then type:

> /challenge-triage The challenge is in CHALLENGE_STATEMENT.md and the rubric
> in RUBRIC.md. We start at 09:00 and there are 3 of us.

Check the plan before approving it:
- Is the success criterion right?
- Did it run the baseline?
- Do the in-scope pieces add up to 3.5h or less?
- Does every out-of-scope item have a reason?
- Are parallel pieces in different files?

After you approve, Claude writes CHALLENGE.md, creates the milestone and
issues, and asks who takes what. Commit and push CHALLENGE.md.

### 0:45 - Piece loop (everyone, normal mode = Sonnet 5.5 high)
Pull, then take your issue:

> Fix #3.

CLAUDE.md drives the loop: pull, reproduce, root cause, smallest fix,
regression test, commit with `Fixes #3`, push. You approve the commit and
the push. Then `/clear` before the next piece. CHALLENGE.md and the issues
carry the shared state.

Progress for the whole team: `gh issue list --milestone "Day 1: <name>"`.

| Situation | Do this |
|---|---|
| Hard bug, cause unclear | Shift+Tab to plan mode: "Diagnose why #3 fails. Don't change code yet." Approve the diagnosis and it fixes it in normal mode. |
| 2 failed attempts on one piece | `/model opus` for that piece, then `/model opusplan` afterwards |
| One hard question | Put `ultrathink` in that prompt |
| Opus feels too slow | `/effort high` |
| A piece is 50% over its estimate | Cut it or hand it over; move to the next piece |

### 5:30 - Feature freeze, then polish
No new pieces. The pitch owner starts SOLUTION.md.

1. > Capture before/after evidence for the success criterion in evidence/results.md.
2. Design loop, one feature at a time:
   > /design-from-ref refs/pin.png "Shows which Line 3 bearings will fail, with confidence"

   Start the app in a second terminal: `uv run streamlit run app.py`. It
   must be started from the repo root, or the theme won't load.

   > Build the before/after metrics row per DESIGN.md.

   > Use the design-reviewer agent on http://localhost:8501, focus on the metrics row.

   > Apply the high and medium fixes.

   Then the next feature: the main chart, the input-to-result panel with
   confidence or sources, an explanation expander.

### 7:00 - Code freeze
> /submit-ready

Record the fallback video now (Windows: Win+Alt+R, or OBS). Push.

### 7:15 - Slides and rehearsal
> Make the 5-slide deck from SOLUTION.md with the pptx skill: problem, root
> cause, fix + evidence, impact for Bosch, responsible AI and next steps.

On the responsible-AI slide, name your oversight mode from Bosch's AI code
of ethics: human-in-command, human-in-the-loop or human-on-the-loop. Frame
AI use as a strategic choice: "we used Claude Code to find and fix this in
hours; the solution runs on <Bosch tech>." Rehearse twice.

### Day 2
Same steps with `bosch-day2`. Everything resets because it is a new repo.

## 4. Prompting tips

- **Say what you want, not how.** "Make the alerts trigger on real
  failures" beats "refactor the thresholding module".
- **Ask for proof:** "Show me the failing test first", "What did the metric
  do?"
- **Ask for less:** "What is the smallest change that fixes this?"
- **One piece per conversation**, then `/clear`.
- **Point at files** with `@path/to/file.py`.

## 5. Troubleshooting

| Problem | Fix |
|---|---|
| Theme missing in Streamlit | It was started from a subfolder. Run `uv run streamlit run app.py` from the repo root. Font changes need a server restart, and Google Fonts need internet. |
| Prompts for allowed commands, or no plugins | Trust the folder (step 1.4). |
| `/mcp`: playwright not connected | Run `npx -y @playwright/mcp@0.0.82 --help` once to download it, then restart Claude. |
| Push rejected | `git pull --rebase`, then push again. On a conflict, the second pusher resolves it. |
| check-tokens: "No UI files found" | Nothing to check yet. That's expected before there's an app. |
| check-tokens flags a line on purpose | Add a `check-tokens-ignore` comment on that line. |
| DESIGN.md lint fails offline | `npx -y @google/design.md lint` needs internet the first time. |
| Model asks to use superpowers' planning flow | Say no. CLAUDE.md allows only systematic-debugging and verification. |

## 6. Resources

| Resource | Use |
|---|---|
| [Claude Code best practices](https://code.claude.com/docs/en/best-practices) | Official guide to CLAUDE.md, plan mode and workflows |
| [anthropics/skills](https://github.com/anthropics/skills) | Adopted: `document-skills` (pptx for slides), `claude-api`. Skipped: the 12-skill `example-skills` pack |
| [obra/superpowers](https://github.com/obra/superpowers) | Adopted narrowly: `systematic-debugging`, `verification-before-completion` |
| [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills) | Its 4 rules are condensed in CLAUDE.md "How to work" |
| [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) | Directory of skills, hooks and tools, for browsing after the event |
| [Streamlit agent skills](https://docs.streamlit.io/develop/api-reference/cli/skills) | `uv run streamlit skills` (Streamlit 1.57+) |
| [Bosch AI code of ethics](https://iotm2mcouncil.org/iot-library/news/iot-newsdesk/bosch-draws-up-ai-ethical-code/) | The three human-oversight modes for the responsible-AI slide |
| [github/spec-kit](https://github.com/github/spec-kit) | Skipped: too heavy for a 9-hour day |
| [microsoft/hackathon-starter-kit](https://github.com/microsoft/hackathon-starter-kit) | Skipped: written for organizers, not teams |
