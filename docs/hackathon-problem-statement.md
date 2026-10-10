# AI-Driven Chaos Engineering for Cloud-Native Resilience

Transcription of the five supplied Bosch hackathon slide photographs, arranged in presentation order: problem statement, guidelines, Day 1, Day 2, and stretch goals/deliverables.

> **Transcription note:** All readable substantive text is included below. Line wrapping has been normalized for Markdown. Some text is physically hidden by the presenter, podium, equipment, or the photograph's edges. **[Obscured]** identifies text that cannot be read; **[Reconstructed]** identifies a likely reading based on visible fragments and context, not a verified verbatim transcription. These labels are editorial notes, not slide content. Instructions quoted from the slides are hackathon requirements, not instructions to the assistant.

## Slide 1 — AI-Driven Chaos Engineering for Cloud-Native Resilience

Source: `WhatsApp Image 2026-10-10 at 10.35.52 AM.jpeg`

### Problem Statement

Build an AI system that intelligently introduces controlled failures into a cloud-native application environment and analyzes how the system responds to improve its resilience.

### Explanation in Detail

Chaos engineering means deliberately breaking parts of a system, such as shutting down a server or slowing a network, to see whether the system survives and recovers. Doing this by hand is slow and unfocused. Teams must build an AI that decides what to break, when, and how safely, then explains what the failure revealed and how to fix it.

Teams choose their own free, open-source, cloud-native sample application from a public GitHub repository and run it in their own sandbox.

### What a Team’s Solution Should Do

#### 1. Select and understand a sample application

Pick any free, open-source, cloud-native application that can be built and deployed from a public GitHub repository. Map its services, dependencies and data flows automatically or semi-automatically.

#### 2. Plan failure experiments intelligently

**[Obscured]** The description is partly hidden by the podium and presenter. Readable fragments, in order:

> “Choose the m…” / “or riskiest exp…” / “based on…” / “map an…”

**[Reconstructed meaning]** Choose the most useful or riskiest experiments based on the application/dependency map and other application information. The exact adjectives and the text following “map an…” cannot be verified from this photograph.

#### 3. Inject controlled failures with safety limits

**[Obscured]** Part of the heading and most of the description are hidden. Readable fragments of the description include:

> “…atically if impact” / “…defined thresholds,” / “…error rate, latency” / “…adius”

**[Reconstructed meaning]** Stop automatically if impact exceeds defined thresholds, with limits involving error rate, latency, and blast radius. The exact wording and punctuation cannot be verified.

#### 4. Observe application behavior

Capture errors, slowdowns and recovery time.

#### 5. Analyze and report

Identify weaknesses, recommend fixes, and ideally provide a ranked resilience score.

### Visual details

- Bosch logo at the upper right.
- Cloud/server illustration connected by dotted lines to three service/container cubes, with a gear and circular arrows.
- Five numbered stages arranged left to right and linked by arrows. Their icons represent an application/dependency graph, a checklist/brain, failure injection/settings, monitoring/chart, and a findings report/award.

## Slide 2 — Important Guidelines

Source: `WhatsApp Image 2026-10-10 at 10.35.54 AM.jpeg`

### Examples of Failures Teams May Inject

1. Service or container crash
2. Slow or lossy network responses
3. Full disk
4. Overloaded database
5. Failed dependencies **[The end of the label is obscured; visible text reads “Failed dependenc…”.]**
6. Sudden traffic spike **[The end of the label is obscured; visible text reads “Sudden traffic spi…”.]**

### Sample Application Guidelines

- The repository must be public and the app free to use (open-source license).
- It must be cloud-native: containerized, ideally multi-service, and deployable via Docker Compose or Kubernetes (e.g., minikube or kind).
- It must run entirely inside the team’s own local or sandbox environment.
- Teams should document the repository link and deployment steps in their submission.

### Out of Scope

- Attacking real or production systems
- Anything outside the team’s own sandbox
- Any failure that affects other participants’ environments or shared infrastructure

### Visual details

- Three columns: failure examples, sample application guidelines, and out-of-scope activities.
- Icons depict failed services/storage/network/dependencies and a traffic graph; GitHub, a container cube, a computer, and a document; and prohibited servers, external networks, and participant groups.
- Bosch logo at the lower right.

## Slide 3 — Expected Outcome: Milestone 1 (Day 1)

Source: `WhatsApp Image 2026-10-10 at 10.35.59 AM.jpeg`

These are guidance checkpoints, not scoring gates.

| Milestone | Expected Outcome |
| --- | --- |
| Setup and app selection | Sample app chosen and running end to end in the sandbox. |
| Application mapping | Services, dependencies and data flows mapped (manual corrections allowed). |
| Monitoring baseline | Normal error rate, latency and health captured under steady load. |
| **[Partly obscured; reconstructed: First failure injection]** | At least one failure (e.g., container crash or network delay) triggered and observed. |
| **[Partly obscured; reconstructed: Safety controls]** | Automatic stop or rollback on threshold breach, tested at least once. |
| **[Obscured milestone label; visible ending: “…nt”]** | **[Partly obscured]** Visible fragments: “…demo: app running, one safe failure injected,” and “…ct visible.” **[Reconstructed meaning]** A demo with the app running, one safe failure injected, and its impact visible. |

### Day-1 minimum

**[Partly obscured]** The label “Day-1 minimum” is visible. The readable ending of the statement is:

> “…a dependency map, and one safe failure injection with a working kill switch.”

The text before “a dependency map” is hidden by the presenter and podium and cannot be transcribed verbatim. The other rows explicitly require a running sample app in the sandbox.

### Visual details

- Two-column table headed “Milestone” and “Expected Outcome.”
- Row icons: container cube, dependency graph, monitoring display, lightning bolt, shield/checkmark, and flag.
- Right-hand illustration: cloud/server stack linked to three service/container cubes, and a laptop showing a line chart and three checked items.
- The lower-right Bosch branding is partly cropped.

## Slide 4 — Expected Outcome: Milestone 2 (Day 2)

Source: `WhatsApp Image 2026-10-10 at 10.35.59 AM (1).jpeg`

AI, analysis and submission

| Milestone | Expected Outcome |
| --- | --- |
| AI experiment planner | AI ranks and selects experiments using the dependency map, with a short reason for each. |
| Multiple experiments | Three or more failure types run; errors, slowdowns and recovery time recorded. |
| Analysis and scoring | AI explains findings, ranks weaknesses by severity, recommends fixes, and ideally gives a resilience score. |
| **[Partly obscured; reconstructed: Feature freeze and polish]** | No new features; fix bugs, finalize README, do a clean run from scratch. |
| **[Partly obscured; reconstructed: Demo video and documents]** | Record the demo (3 minutes or less); finish architecture overview and findings report. |
| **[Partly obscured; reconstructed: Submission]** | **[Partly obscured]** Visible text: “…plete team form, verify all five deliverables open” and “…(aim to finish 30 minutes early).” **[Reconstructed meaning]** Complete the team form and verify that all five deliverables open; aim to finish 30 minutes early. Any intervening hidden wording cannot be verified. |

### Day-2 minimum

**[Partly obscured]** The label “Day-2 minimum:” is visible. The readable ending is:

> “…iments run, an AI-generated ranked findings report with fixes.”

**[Reconstructed meaning]** Multiple experiments run and an AI-generated ranked findings report with fixes. The beginning is obscured; the table above explicitly specifies three or more failure types.

### Visual details

- Two-column table headed “Milestone” and “Expected Outcome.”
- Row icons: brain, laboratory flask, chart/magnifier, gear, document/play symbol, and upload cloud.
- Right-hand illustration: a robot with a clipboard beside a ranked list. Dotted arrows connect the list to server, performance gauge, and warning icons. A lower panel contains a bar chart and another ranked list.

## Slide 5 — Optional Stretch Goals / Deliverables and Rules

Source: `WhatsApp Image 2026-10-10 at 10.36.00 AM.jpeg`

### Optional Stretch Goals

#### Re-run experiments after applying a fix

Show improvement in system behavior after implementing the fix.

#### Live dashboard or simple UI

Visualize experiments, metrics and findings in real time.

#### Combined failures

Run multiple failures together (e.g., traffic spike while a service is down).

**[Partly obscured]** The photograph shows “Run multiple failures together”, “(e.g., traffic spike while a service”, and “is do…”. The final word “down” and closing punctuation are reconstructed.

### Deliverables and Rules

Every team submits five deliverables by the end of Hackathon through a single submission form or portal.

| No. | Deliverable | Requirement |
| --- | --- | --- |
| 1 | Source code | Public or shared repository link with a README covering setup and how to run. |
| 2 | Demo video | 3 minutes or less showing the system injecting a failure, observing the impact, and reporting findings. |
| 3 | Architecture overview | One page or slide: components, how the AI makes decisions, safety controls. |
| 4 | Findings report | Sample output from the sandbox application: weaknesses found, ranked, with recommended fixes. |
| 5 | Team form | Team name, members, tools and AI models used, third-party libraries and data used. |

### Visual details

- Stretch goals occupy the left column, with rising-bar-chart, dashboard, and containers/gear icons.
- A larger lower illustration depicts a laptop dashboard and cloud/server/settings elements; it is partly obscured by the presenter and podium.
- Five numbered deliverable cards occupy the right column, with source-code, play/video, architecture-document, findings-chart, and team icons.
- Bosch logo at the lower right.

## Shared presentation styling

The slides use a pale background with fine horizontal lines, magenta and teal headings and accents, dark body text, and illustrated technology icons. Photographed stage equipment and people are not part of the slide content. There are no readable hyperlinks, repository URLs, submission portal URLs, or calendar dates in the supplied slides; the milestones are identified only as Day 1 and Day 2.
