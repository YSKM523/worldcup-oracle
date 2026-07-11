# Match Forecast Four-Tab Console Design

## Goal

Replace the console-only `MODEL MATRIX` / `MATCH DOSSIER` filler with four focused analytical tabs that use the center column efficiently on 27–32 inch monitoring displays without repeating the always-visible match forecast summary.

## Layout and interaction

- Keep the existing console header, fixture identity, advancement/WDL bar, score chips, xG, BTTS, model disagreement, and Polymarket summary always visible.
- Add one flat tab rail immediately below that summary: `VALUE`, `SCRIPTS`, `SCORES`, `WATCH`.
- Default to `SCORES` every time the match dialog opens.
- Preserve the selected tab while the same dialog remains mounted. Do not auto-rotate tabs.
- The tab body fills the remaining center-column height and scrolls internally only when necessary.
- The card-mode `FocusCard` used elsewhere remains unchanged.
- Remove the console `MODEL MATRIX` and `MATCH DOSSIER` sections completely.

## Tab contents

### VALUE · 盘口价值

Render home/draw/away rows with AI probability, normalized Polymarket probability when available, AI fair decimal odds, market decimal odds, edge in percentage points, direction, and half-Kelly sizing. Missing market inputs render an explicit unavailable state rather than fabricated values.

### SCRIPTS · 比赛剧本

Build a normalized Poisson score grid from the existing home/away xG values, then group it into three evidence-backed scripts: home-win paths, draw paths, and away-win paths. Each script shows aggregate probability and its leading scorelines. Labels describe the result path, not invented tactical events.

### SCORES · 比分分布

Default tab. Render a compact score matrix covering 0–0 through 3–3, plus an aggregated `4+` tail. Highlight the most likely score, use the existing home/draw/away colors, and show the top-score ranking. Cell probabilities come from a normalized Poisson grid derived only from the supplied xG values; the existing top-score output remains the authoritative highlight/ranking. If xG is unavailable, render an explicit unavailable state.

### WATCH · 盯盘清单

Render observable market/feed health: Polymarket connection and freshness, Kalshi live/stale/unavailable, AI-versus-market divergence, weather, kickoff/feed state, and concise threshold-based alerts. Do not generate unsupported lineup or tactical claims. Do not duplicate the right column's order book, volume, or trade tape.

## Responsive behavior

- Desktop console: tab body consumes the remaining full-height center surface and aligns with the right market column bottom inset.
- Below 1280px: tabs remain in the prediction section's existing stacked position; the rail may horizontally scroll without wrapping.
- All controls remain keyboard-accessible and expose selected state with `aria-selected` and a tabpanel relationship.

## Testing and acceptance

- Component tests prove `SCORES` is the initial tab, each tab switches content, the previous model-matrix/dossier content is absent, and missing inputs degrade explicitly.
- Browser verification at 1920×1080 and 2560×1440 confirms the center panel fills its column without document overflow.
- Existing match-console, Kalshi, telemetry, TypeScript, build, and close-interaction tests remain green.
