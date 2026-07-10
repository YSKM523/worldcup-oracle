# WorldCup Oracle Knockout Map Dashboard Design

**Date:** 2026-07-10  
**Status:** Approved direction — knockout map filling the lower dashboard region

## Context

The compact three-column dashboard now groups related information correctly,
but large desktop displays still leave substantial unused space below the
performance and matchday content. The primary user monitors the dashboard for
extended periods on a large desktop display, so the unused area should carry
useful tournament-state information rather than decorative filler.

## Chosen Direction

Add a `KNOCKOUT MAP` panel built entirely from the existing `data.matches`
payload. On large desktops it spans the lower-left and lower-center area while
the champion panel continues to occupy the full right column. This preserves
the control-room identity and fills the largest empty region with the remaining
tournament path.

## Large-Desktop Layout

At 1280px and above, change the dashboard content grid from one row to two:

```text
┌──────────────────┬──────────────────────────────┬──────────────────┐
│ AI PERFORMANCE   │ MATCHDAY                     │ CHAMPION RACE    │
│                  │                              │                  │
├──────────────────┴──────────────────────────────┤                  │
│ KNOCKOUT MAP · QF → SF → FINAL                  │                  │
└─────────────────────────────────────────────────┴──────────────────┘
```

- Keep the existing three column widths:
  `minmax(260px,22%) minmax(0,1fr) minmax(340px,26%)`.
- Use two content rows with exact sizing
  `minmax(360px,0.9fr) minmax(260px,0.7fr)` and an 8px gap.
- `PerformancePanel` occupies column 1, row 1.
- `MatchdayPanel` occupies column 2, row 1.
- `ChampionPanel` occupies column 3 and spans both rows.
- `KnockoutMapPanel` spans columns 1–2 in row 2.
- Preserve the single-screen page lock and internal panel scrolling when the
  viewport is short.

## Compact-Desktop, Tablet, and Mobile Layout

### 768–1279px

- Keep the natural-scroll two-column grid.
- `MATCHDAY` spans both columns first.
- `KNOCKOUT MAP` spans both columns second.
- `PERFORMANCE` and `CHAMPION RACE` share the following row.

### Below 768px

- Use the order `MATCHDAY`, `KNOCKOUT MAP`, `PERFORMANCE`, `CHAMPION RACE`.
- Render knockout stages vertically instead of forcing horizontal overflow.
- Keep all match nodes readable without hiding teams, scores, or probabilities.

## Knockout Map Data Model

No new API or payload field is required. Derive the panel from
`data.matches`:

- Quarterfinals: matches where `stage === "qf"`.
- Semifinals: matches where `stage === "sf"`.
- Final: the match where `stage === "final"`.
- Sort each stage by `kickoff_utc` to produce stable bracket order.
- The first two quarterfinals feed semifinal 1; the final two feed semifinal 2.
- The two semifinals feed the final.

The component consumes the existing `Match`, `LiveMap`, `STAGE_ZH`, `pct()`,
`fmtTime()`, `Flag`, and `zh()` interfaces. It adds no state and performs no
network requests.

## Match Node States

Each node has one of three states:

### Completed

- Determine completion from `m.completed || live[m.espn_id]?.completed`.
- Show both teams, final score, and an `FT` label.
- Emphasize the advancing team using existing ink/up colors; dim the eliminated
  team.
- The node remains clickable and opens the existing match detail modal.

### Upcoming or In Play

- Show both teams, kickoff time or live score/clock, and stage label.
- If `m.pred.p_adv_home` and `m.pred.p_adv_away` exist, show a compact dual
  advancement bar and both percentages.
- If advancement probabilities are absent, fall back to the existing
  regulation probabilities without inventing values.
- The node remains clickable and opens the existing match detail modal.

### Unresolved Placeholder

- A match is unresolved when `m.tbd` is true or either team name still contains
  `Winner`/`Loser` placeholder text.
- Show neutral connector labels such as `QF2 WINNER` or `SF1 WINNER` using the
  existing faint ink color.
- Do not render a flag or probability bar for an unresolved participant.
- Disable match-detail interaction until real teams are resolved.

## Visual Composition

- Keep the existing panel chrome, registration marks, palette, typography, and
  4/8/12/16px spacing scale.
- Use a three-stage grid: four quarterfinal nodes, two semifinal nodes, one
  final node.
- Use thin horizontal connector rules between stages. Connectors remain quiet
  structural elements, not decorative animations.
- Use flat rows and dividers rather than nested cards.
- The final node receives slightly stronger border contrast and an amber date
  accent, without gradients or glow.
- Add a compact header legend for `FT`, live/upcoming, and advancement
  probability.

## Interaction and Accessibility

- Use semantic `<button>` elements for resolved matches.
- Preserve keyboard activation and visible hover/focus feedback.
- Use text (`FT`, kickoff time, percentages) in addition to color.
- Do not add ambient motion; existing live indicators may continue to pulse.
- Respect the existing reduced-motion stylesheet.

## Empty and Error States

- If no knockout matches exist, render `淘汰赛对阵尚未生成` in the panel body.
- Missing prediction data removes only the probability bar; team names and
  schedule information remain visible.
- Missing live data falls back to the static match state.
- No component failure may affect the existing performance, matchday, champion,
  or drawer panels.

## Component Boundaries

- Add `KnockoutMapPanel` and its small private match-node helpers to
  `web/components/Dashboard.tsx` near the other dashboard-only panels.
- Keep the existing `Panel` abstraction and `Dashboard` drawer state.
- Pass `onOpenMatch` from `Dashboard`; do not duplicate modal state.
- Do not split shared match-card components or change their public contracts in
  this pass.

## Verification

Validate with fresh browser captures at:

- 1920×1080, 2560×1440, and 3440×1440: two-row three-column single-screen
  layout, champion panel spanning both rows, and knockout map filling the lower
  two-column area.
- 1366×768: both grid rows remain present without page scrolling; short panels
  use internal scrolling without clipping.
- 1180×820 and 1024×768: matchday and knockout map each span both columns,
  followed by performance and champion panels.
- 768×1024 and 390×844: natural scrolling, correct panel order, vertical stage
  composition, and no horizontal overflow.

Run TypeScript checking and a production build. Inspect the browser console,
open one resolved match node to verify modal reuse, and confirm that the Git
diff contains no data, pipeline, collector, or research changes.

## Out of Scope

- New odds feeds, bracket APIs, prediction calculations, or collector changes.
- Third-place match visualization.
- Dragging, bracket editing, scenario simulation, or animated connectors.
- Rebranding, typography replacement, or unrelated ESLint cleanup.
