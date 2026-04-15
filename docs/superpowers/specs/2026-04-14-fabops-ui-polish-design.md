# FabOps Copilot UI Polish, Design Spec

**Date:** 2026-04-14
**Status:** Approved, ready for implementation plan
**Scope:** Frontend only. No backend, Lambda, or API changes.

---

## 1. Goal

Transform the deployed frontend from a spartan Bootstrap-style page into a portfolio-grade interface that:

1. **(Primary)** Reads as a serious tool a JOLT / Applied Materials hiring manager would respect on first open.
2. **(Primary)** Surfaces the agent's reasoning during execution so the interesting part of the system is visible, not hidden behind a spinner.
3. **(Secondary)** Stays understandable to a non-technical reviewer in under ten seconds without reading any docs.

A planner should be able to scan the post-run page and answer "what's the driver, when's the stockout, what do I do, what's the evidence" in one second per question. A recruiter who lands cold should hit one button and see a real run.

---

## 2. Out of Scope

Cut for YAGNI or because the cost beats the value:

- **Recent queries history** in localStorage. Low value for a single-visit recruiter audience.
- **Real SVG flowchart** of the 9-node graph. The numbered list with side-comments tells the same story for ten percent of the work.
- **Streaming SSE per-node updates** from the backend. The animated execution panel is purely client-side, tuned to observed warm latency. Honest because the post-run audit trail uses the real `audit` payload.
- **Mobile responsive layout.** Desktop-first. Mobile breakpoints are a future task.
- **Theme toggle** (light mode). Direction A is dark only.
- **Backend, Lambda, or API contract changes.** The frontend consumes the same JSON shape that's already in production.

---

## 3. Visual Direction

**Direction A, "Fab Control Room."** Dark canvas, restrained accents, single surface for every card.

### 3.1 Color tokens

| Token              | Hex       | Use                                                         |
|--------------------|-----------|-------------------------------------------------------------|
| `--bg-base`        | `#0a0e14` | Page background                                             |
| `--bg-grid`        | `#161c28` | Radial-dot pattern over the page bg                         |
| `--surface`        | `#11161f` | Every card. The only card surface in the app                |
| `--border`         | `#1c2433` | Card borders, hairline separators                           |
| `--fg-primary`     | `#e6edf3` | Headlines, primary text                                     |
| `--fg-secondary`   | `#a8c0d6` | Body text inside cards                                      |
| `--fg-muted`       | `#7d8590` | Section labels, mono subtext                                |
| `--fg-faint`       | `#525d6b` | Hints, placeholders, ▼ chevrons                             |
| `--accent-orange`  | `#fb923c` | Driver: POLICY DRIFT. Eyebrow `// FABOPS COPILOT`. Date highlights inside the diagnosis sentence. **Reserved.** |
| `--accent-green`   | `#3ddc97` | Status only: runtime LED, ✓ glyphs, "VERIFIED", Run button, NONE driver chip. **Reserved.** |
| `--accent-red`     | `#f87171` | Driver chip: SUPPLY RISK                                    |
| `--accent-purple`  | `#a78bfa` | Driver chip: DEMAND SHIFT                                   |
| `--accent-orange-bg` | `#1f140a` | POLICY DRIFT chip background                              |
| `--accent-red-bg`  | `#1f0a0a` | SUPPLY RISK chip background                                 |
| `--accent-purple-bg` | `#13091f` | DEMAND SHIFT chip background                              |
| `--accent-green-bg` | `#0a1f15` | NONE chip background, REAL provenance card background      |

**Discipline rule:** orange is reserved for the policy driver, green is reserved for status. Anything else that "needs an accent" gets a mono uppercase label and a hairline border, not color.

### 3.2 Typography

| Family         | Source                                               | Use                                          |
|----------------|------------------------------------------------------|----------------------------------------------|
| **Inter**      | Google Fonts, weights 400 / 500 / 600                | Headlines, body text, button labels          |
| **JetBrains Mono** | Google Fonts, weights 400 / 600                  | Labels, chips, the eyebrow, all numeric data, audit trail, the in-textarea query echo |

System fallbacks: `-apple-system, BlinkMacSystemFont, sans-serif` for Inter, `ui-monospace, SFMono-Regular, Menlo, monospace` for JetBrains Mono.

### 3.3 Layout primitives

- **Page background:** `var(--bg-base)` with a radial-dot grid: `radial-gradient(circle at 1px 1px, var(--bg-grid) 1px, transparent 0)` at `18px 18px`.
- **Content max-width:** `880px`, centered, `0 36px` horizontal padding.
- **Card:** `background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 24px;`
- **Section spacing:** 16px between cards vertically.
- **Hairline separator:** `border-top: 1px solid var(--border); padding-top: 14px;` inside multi-row cards.

---

## 4. Component Spec

### 4.1 Nav bar

Sticky top. `padding: 18px 36px`. Border-bottom hairline. Backdrop blur over the page bg.

**Left side:** Status LED (8x8 green dot, glow) + mono label `RUNTIME ONLINE`. Vertical hairline. Mono subtext `us-east-1 · λ fabops_agent_handler`.

**Right side:** Three Inter text links: `how it works`, `architecture`, `github`. Color `var(--fg-muted)`, 12px. Hover lifts to `var(--fg-secondary)`.

- `how it works` opens the modal (§4.5).
- `architecture` opens the GitHub `REPORT.md` in a new tab.
- `github` opens the repo root in a new tab.

### 4.2 Hero

Padding: `64px 36px 48px`, inside the 880px container.

**Eyebrow:** `// FABOPS COPILOT` in mono, 11px, `var(--accent-orange)`, letter-spacing 1.5px, weight 600.

**Headline:** Inter 42px, weight 600, letter-spacing -1.2px, line-height 1.1, color `var(--fg-primary)`.
> Diagnoses why a service part is at stockout risk and recommends an action.

**Subline:** Mono 13px, `var(--fg-muted)`, letter-spacing 0.3px.
> 9-node LangGraph · MCP-native · grounded in DynamoDB + SEC filings + FRED

### 4.3 Query panel

Single card. Three regions stacked, separated by hairlines.

**Top row:** Mono label `ASK THE AGENT` (left). Mono hint `⌘ + ↵ to run` (right, `var(--fg-faint)`).

**Middle:** Textarea, 64px min-height, mono 14px, `var(--fg-primary)`, no border, transparent background, no resize handle. Placeholder text in `var(--fg-faint)`.

**Bottom row:** Three example chips on the left, Run button on the right.

- **Example chips.** Mono 10px, mono label `EXAMPLES` prefix, then three chips: `policy drift A7`, `supply risk B12`, `demand spike C3`. Background `var(--bg-base)`, border `var(--border)`, padding `5px 10px`, border-radius 4px.
- **Run button.** Inter 13px, weight 600, padding `8px 18px`, background `var(--accent-green)`, color `var(--bg-base)`, border-radius 5px. Label: `Run agent →`.

**Synthetic data label.** 11px Inter italic in `var(--fg-faint)`, full text from the current frontend, sits below the card with `margin-top: 10px`.

#### 4.3.1 Chip behavior (locked: option 2)

Click on a chip:
1. Fills the textarea with the canned full question for that chip.
2. Triggers the same handler as the Run button immediately.
3. Visibly flashes the chip background to `var(--accent-orange)` for 200ms so the user sees which chip ran.

If the user wants to edit the example, they cancel the in-flight run and edit the textarea. We do not need an undo, the cancellation just means the next click on Run wins.

**Chip to question map:**

| Chip               | Full query                                                                                  |
|--------------------|---------------------------------------------------------------------------------------------|
| `policy drift A7`  | "Why is part A7 about to stock out at the Taiwan fab, and what should I do?"                |
| `supply risk B12`  | "Part B12 keeps slipping. Is the supplier the problem and what should I do about it?"       |
| `demand spike C3`  | "Demand for C3 looks higher than the forecast. Is something real happening and how do I respond?" |

The exact part IDs need to match real rows in the seeded DynamoDB tables. Implementation phase will pick three IDs from `fabops_inventory` whose drift was injected by `inject_gold_drift.py` and update this table accordingly.

### 4.4 Animated execution panel (loading state)

Replaces the spinner. Visible only between Run click and response.

Card with three regions:

**Header row:** Mono label `AGENT EXECUTION`. Right side: pulsing green LED + mono `RUNNING`.

**Progress bar:** 9 segments in a `display: grid; grid-template-columns: repeat(9, 1fr); gap: 6px;` strip, 4px tall, segments are 2px-rounded rectangles. Segments cycle through three states:
- `pending` (default): `var(--border)`
- `active` (currently running): `var(--accent-green)` with a 6px green box-shadow glow
- `done`: solid `var(--accent-green)`, no glow

**Per-node log:** Mono 11px, line-height 1.9, nine rows. Each row is `glyph + node_name + spacer + timing/note`. Glyph color encodes state: `✓` green for done, `▸` orange for active, blank `var(--fg-faint)` for pending.

#### 4.4.1 Animation honesty

We do not have a streaming connection from the Lambda. The progression is client-side, paced by a fixed schedule tuned to observed warm latency. The schedule is in `app.js` as a constant array.

```js
const NODE_SCHEDULE_MS = [
  ["entry",                  150],
  ["check_policy_staleness", 700],
  ["check_demand_drift",     900],
  ["check_supply_drift",    1100],
  ["ground_in_disclosures", 3500],
  ["diagnose",              5500],
  ["prescribe_action",      1100],
  ["verify",                 100],   // gated off, near-instant
  ["finalize",              1100],
];
// total ≈ 14.2s, matches warm Lambda from the project memory snapshot
```

Behavior:

- The animation starts the moment the user clicks Run (or a chip).
- If the response arrives before the animation finishes, the animation **fast-forwards** to "done" on all remaining nodes within 300ms, then renders results.
- If the response is slower than the schedule, the animation **holds on the last node** (`finalize`) with the active glyph until the response lands, then snaps everything to done.
- On a cold start (50 to 55 seconds), this means the user sees the bar progress, then sit on `finalize` for up to 40 seconds. That is acceptable, the pre-warm should usually prevent it.
- On error, the active node turns red, glyph becomes `✗`, and an error row appears below the log.

After the response renders, the panel is **replaced** by the results state (it does not stack). The audit trail card in the results state uses the **real** `audit` payload from the response, so the animated phase is theatre and the post-run phase is honest.

### 4.5 Results state

Renders after a successful response. Replaces the loading panel and the query panel collapses into a query echo strip at the top.

**Order, top to bottom:**

1. **Query echo.** Mono label `QUERY` and mono body in `var(--fg-secondary)`. Not a card, just two lines of text inside the page padding.
2. **Diagnosis card.** See §4.5.1.
3. **Recommended action card.** See §4.5.2.
4. **Citations card.** See §4.5.3.
5. **Audit trail card.** See §4.5.4.

A "New query" affordance lives in the page nav area (or a small mono link below the audit trail) that brings back the full query panel and clears the results.

#### 4.5.1 Diagnosis card

Single card, `padding: 24px 26px`.

**Header row:** Mono label `DIAGNOSIS` (left). Right side: green LED dot, mono text `VERIFIED · {totalDurationSec}s`.

**Headline paragraph.** Inter 21px, weight 500, letter-spacing -0.3px, line-height 1.4, color `var(--fg-primary)`. Built from the response by template:

> Primary driver is `[DRIVER CHIP]`. Part `{part_id}` will stock out around `{stockout_date_human}`. `{one-line evidence sentence from diagnosis.reasoning}`.

The driver chip is inline (vertical-align nudged 2px), background `var(--accent-{driver}-bg)`, color `var(--accent-{driver})`, mono 14px, padding `2px 9px`, border-radius 4px, weight 700.

Date and key numbers inside the headline are wrapped in a span with `color: var(--accent-orange); font-weight: 600;` (one inline highlight per sentence, max).

**Stat row.** Below the headline, separated by a top hairline. Three columns laid out with `display: flex; gap: 32px;`, each column has a 9px mono label and a 15px mono value. Labels: `P90 STOCKOUT`, `CONFIDENCE`, `{DRIVER-SPECIFIC METRIC}`.

The third metric depends on the driver:
- POLICY DRIFT: `POLICY AGE` (e.g. `409d · thr 90d`)
- SUPPLY RISK: `LEAD-TIME SLIP` (e.g. `+18d vs baseline`)
- DEMAND SHIFT: `RUN-RATE DELTA` (e.g. `+34% wk-over-wk`)
- NONE: `SIGNAL` (e.g. `within bounds`)

If the response does not contain the specific metric, omit the third column entirely (do not render a placeholder).

#### 4.5.2 Recommended action card

Single card, `padding: 22px 26px`.

- Mono label `RECOMMENDED ACTION`, 10px, `var(--fg-muted)`.
- Inter 17px headline in `var(--fg-primary)`, weight 600.
- Inter 13px rationale in `var(--fg-muted)`, line-height 1.55.

Headline copy comes from a template keyed by `diagnosis.action`:

| `action` value          | Headline template                                       |
|-------------------------|---------------------------------------------------------|
| `refresh_reorder_policy`| Refresh the reorder policy for part `{part_id}`         |
| `place_reorder`         | Place a reorder for part `{part_id}` at the new run-rate|
| `expedite`              | Expedite part `{part_id}` and qualify a backup supplier |
| `monitor`               | Monitor part `{part_id}`, no action required today      |

Rationale uses `diagnosis.reasoning` from the response.

#### 4.5.3 Citations card

Single card, padding `20px 24px`. Header: mono label `CITATIONS · {n} SOURCES`.

Body: rows of citations, each row separated by a top hairline (the first row has no top hairline). Each row contains:

- **Source chip:** mono 10px, `var(--fg-muted)` text, `border: 1px solid var(--border)`, padding `1px 7px`, border-radius 3px. Label is the source type in caps: `DYNAMODB`, `SEC EDGAR`, `FRED`, `INTERNAL`.
- **Subtitle:** mono 10px, `var(--fg-faint)`, location pointer (e.g. `fabops_policies / part_id=A7` or `AMAT 10-Q · 2025-Q3 · risk factors`).
- **Excerpt:** Inter 13px, `var(--fg-secondary)`, line-height 1.5. Truncated to first 220 characters with an ellipsis if longer.

Source chips do **not** use color (no green border, no orange border). Restraint rule.

If `data.url` exists, the subtitle is wrapped in an `<a>` that opens the URL in a new tab, color stays `var(--fg-faint)` and gets `text-decoration: underline` on hover.

#### 4.5.4 Audit trail card

Collapsed by default. Single card with one-row header:

- Left: mono label `AUDIT TRAIL · 9 NODES · {totalDurationSec}s`
- Right: mono `▼ expand` in `var(--fg-faint)`, click toggles to `▲ collapse`.

Expanded body: same per-node log layout as §4.4 but with all real timings from `data.audit`. Rows in `data.audit` are joined to the canonical 9-node order and rendered with their actual `duration_ms` and `note` fields. A node that was skipped (e.g. `verify` when the gate is off) shows `skipped (gate off)` in faint mono and a green ✓ glyph.

If the audit payload is missing or empty, the card renders the header in faint mono with the text `AUDIT TRAIL · unavailable` and is not expandable.

### 4.6 "How it works" modal

Triggered by the nav `how it works` link or by pressing `?` on the keyboard.

**Backdrop:** Fixed full-screen overlay, `background: rgba(10, 14, 20, 0.85);`. The page grid pattern is visible through the backdrop.

**Modal container:** Centered, max-width 680px, `background: #0d121a; border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 20px 60px rgba(0,0,0,0.6);`. Closes with × button (top right), Esc key, or click on the backdrop.

**Modal header:** `padding: 20px 28px`, hairline border-bottom. Eyebrow `// FABOPS COPILOT` in mono orange. Title `How it works` in Inter 18px weight 600.

**Section structure:** Four sections, hairline separators between them. Each section starts with a mono label `§N · TITLE`, 10px, `var(--fg-muted)`.

- **§1 · WHAT IT IS.** One paragraph of Inter 14px in `var(--fg-secondary)`, line-height 1.65.
- **§2 · THE FOUR DRIVERS.** Four rows. Each row has a fixed-width chip (96px min, centered text) on the left and a one-line explanation on the right. Chip styles match the driver chips from §4.5.1, plus the `NONE` chip in green. Each line names the action verb in `var(--fg-primary)` to anchor the read.
- **§3 · THE 9-NODE GRAPH.** Pre-formatted block, mono 11px, line-height 1.85. Numbered list with side-comments in `var(--fg-faint)` (the comments visually align in the same column). Followed by a one-line Inter 12px caption: "Every node writes to a DynamoDB audit spine, so every claim the agent makes is traceable."
- **§4 · WHAT'S REAL, WHAT'S NOT.** Two-column grid, REAL on the left in a faint green-tinted card (`var(--accent-green-bg)` background, `1a3329` border), SYNTHETIC on the right in a faint orange-tinted card (`#1f1408` background, `#332210` border). This is the **only** place in the app that uses tinted backgrounds for cards. The contrast is the point of the section.

Modal copy is fixed text in the design. No template, no dynamic data.

---

## 5. Files Touched

Frontend only.

| File                  | Change                                                                               |
|-----------------------|--------------------------------------------------------------------------------------|
| `frontend/index.html` | Full rewrite. Sticky nav, hero, query panel, modal markup, two empty containers for loading and results. |
| `frontend/styles.css` | Full rewrite. CSS custom properties for tokens, all component styles. |
| `frontend/app.js`     | Significant extension. Pre-warm stays. Add: chip handlers, modal open/close + Esc key, animated execution scheduler, results renderer with the v2 layout, audit trail toggle. |
| `frontend/config.js`  | No change. |

No new files. No npm install. No build step. Single static page deployed by Amplify on push, same as today.

External dependency: Google Fonts CSS link in the `<head>` for Inter (400/500/600) and JetBrains Mono (400/600). If the font request fails, the system fallbacks render fine and the page is still legible.

---

## 6. Backend Contract

The frontend assumes the existing JSON response shape from `fabops_agent_handler`:

```jsonc
{
  "answer": "string, full model output",
  "diagnosis": {
    "primary_driver": "policy" | "supply" | "demand" | "none",
    "confidence": 0.0,
    "reasoning": "one or two sentence rationale",
    "action": "refresh_reorder_policy" | "place_reorder" | "expedite" | "monitor"
  },
  "p90_stockout_date": "YYYY-MM-DD" | null,
  "citations": [
    { "source": "string", "url": "string?", "excerpt": "string?" }
  ],
  "audit": [
    { "node": "string", "duration_ms": 0, "note": "string?" }
  ]
}
```

Two fields are needed that may not exist today:

1. `audit` (array of per-node entries with timing). The agent already writes audit rows to DynamoDB via the `_audit` helper. The runtime handler may or may not return them in the response payload. **Implementation phase needs to verify this and, if missing, add a single line to the handler to include them.** This is the only backend touch the spec allows, and it is read-only on data the agent already produces.
2. Driver-specific metric values for the third stat column in §4.5.1 (`POLICY AGE`, `LEAD-TIME SLIP`, `RUN-RATE DELTA`, `SIGNAL`). If the diagnose node already surfaces these in `diagnosis` or as side fields on the response, render them. If not, render only the first two stats and skip the third column gracefully. **No backend change to add new metric fields in this pass.**

---

## 7. Edge Cases and Error Handling

| Scenario                                       | Behavior                                                                       |
|------------------------------------------------|--------------------------------------------------------------------------------|
| User clicks Run with empty textarea            | Disabled state on the button, no request fired                                 |
| User clicks a chip while a request is in flight| Cancel the in-flight fetch via `AbortController`, start the new one            |
| Lambda returns 4xx or 5xx                      | Active node turns red with ✗, error row in the log, results state not rendered |
| Lambda times out (network error / 504)         | Same as above, error row text "Lambda did not respond, try again"             |
| Response is missing `diagnosis`                | Render a single-card error state with the raw `answer` text                    |
| Response missing `audit`                       | Audit trail card shows `unavailable` and is not expandable                     |
| Response missing `p90_stockout_date`           | Stat column shows `not computed` in faint mono                                 |
| `citations` is empty                           | Citations card shows label `CITATIONS · 0 SOURCES` and a single faint row "no external sources cited" |
| Animation finishes before response arrives     | Hold on `finalize` with active glyph until response lands                      |
| Response arrives before animation finishes     | Fast-forward all remaining nodes to done within 300ms, then render results     |
| User presses Esc with modal open               | Close modal                                                                    |
| User presses Esc with no modal                 | No-op                                                                          |
| User presses ⌘+↵ in textarea                   | Same as clicking Run                                                           |
| User presses `?` outside textarea              | Open the modal                                                                 |
| Cold start (50 to 55 seconds)                  | Pre-warm should usually prevent it. If hit: animation completes, holds on `finalize`, user sees the LED still pulsing |

---

## 8. Implementation Order

Sequential. Each step is committable and reviewable on its own.

1. **CSS theme.** Custom properties, font imports, base layout (body bg, grid pattern, max-width container, typography defaults). No JS changes. After: existing components look "themed but unchanged."
2. **Nav and hero.** Replace the existing header with the sticky nav + LED + links. Replace the existing h1/subtitle with the eyebrow + headline + subline.
3. **Query panel and chips.** Rewrite the existing `.query-panel` markup. Wire chip click handler that fills the textarea and triggers Run. Add the cmd+enter binding.
4. **Animated execution panel.** Build the markup for the loading state. Implement the scheduler. Wire it to start on Run / chip click. Hide the existing `.loading` element.
5. **Results state v2.** Rewrite `renderResults()` from scratch against the v2 layout. Build helpers for the diagnosis sentence template, action template, and citations rendering. Hook up the audit trail collapse toggle.
6. **"How it works" modal.** Add modal markup (hidden), add open/close handlers (nav link, ×, Esc, backdrop click), add `?` keyboard shortcut. Modal content is static HTML in `index.html`.
7. **Verify against deployed Lambda.** Open the live URL, run all three example chips, verify each renders the right driver chip color and the right action text. Verify the audit trail expands and shows real timings. Verify cold start fallback animation behavior. Verify the modal opens from the link and Esc.
8. **Commit, push, watch Amplify deploy.** Smoke test the deployed URL.

Each step is a separate commit with a `feat(frontend):` or `style(frontend):` conventional commit message.

---

## 9. Acceptance Criteria

The polish pass is done when:

1. The Amplify URL renders the new dark theme with no console errors.
2. Clicking each of the three example chips fires a real Lambda invoke and renders a structured results state with the correct driver chip and the correct action card.
3. The animated execution panel runs end-to-end on a warm invoke without visible glitches, and holds on `finalize` on a cold invoke until the response lands.
4. The audit trail card expands to show real per-node timings from the response.
5. The "how it works" modal opens from the nav link, from `?`, and from clicking the link, and closes from ×, Esc, and backdrop click.
6. All four driver chip colors render correctly when the corresponding example is run (orange policy, red supply, purple demand, green none).
7. No em dashes anywhere in HTML, CSS, JS, commit messages, or this design doc.
8. The page is desktop-usable at 1280px and 1440px viewports. Mobile is explicitly out of scope.
9. README hero screenshot is updated to reflect the new design.

---

## 10. Risks and Open Questions

1. **Audit payload may not be in the response today.** Mitigation: verify in the implementation phase, add a single line to `runtime.py` if needed, treat as the only allowed backend touch.
2. **Chip queries need real seeded part IDs.** Mitigation: implementation phase queries `fabops_inventory` for parts that match the three driver branches and updates the chip-to-question table in this doc.
3. **Cold start with pre-warm failing.** If a recruiter loads the page over a flaky network, the warmup POST may fail silently and the first Run is a 50-second wait. The animation holds on `finalize` so the page does not look frozen, but this is still ugly. Acceptable risk for this pass. Provisioned concurrency is the real fix and is out of scope.
4. **Driver-specific third stat metric** may not exist in the response today. Mitigation: render two columns instead of three when the metric is missing. No template error.
5. **Google Fonts blocked or slow.** System fallbacks render fine but the look is degraded. Acceptable for a portfolio site, the recruiter audience does not have ad blockers that deep.

---

## 11. Definition of "matches the hero"

The single most important visual rule in this spec:

> Every card surface in the app is `var(--surface)` on the page grid background. Every card has the same border, the same border-radius, the same padding. Hierarchy comes from type size, type weight, and the position of the card on the page. Color is reserved for status (green) and the policy driver chip (orange). Other driver chips exist (red, purple) but are also restrained color use, never card backgrounds.

If a future change introduces a tinted card background or a colored card border, it has to earn its keep the way §4.6's REAL/SYNTHETIC cards do (the contrast is the point of the section). Otherwise the change violates this rule and gets pushed back.
