# Live Polymarket odds + decimal odds display

**Status:** approved 2026-06-12

## Goal

1. Show Polymarket odds in (near) real time instead of the once-daily baked
   snapshot.
2. Add per-match (W/D/L) Polymarket lines to match cards.
3. Display odds as **decimal odds** (= 1 / raw price, vig included) instead of
   percentages.

## Polymarket Gamma API (reverse-engineered 2026-06-12)

Base: `https://gamma-api.polymarket.com`. **CORS is open** (`access-control-allow-origin: *`),
so the browser can fetch directly, like the existing ESPN live-score hook.
CDN `cache-control: max-age=300` → effective freshness ~5 min.

### Champion (winner) market
- Active event slug: **`world-cup-winner`** (the hardcoded
  `2026-fifa-world-cup-winner-595` / `-winner` slugs are dead — the Python
  fetcher only works today via its title-search fallback; fix the slug).
- `GET /events?slug=world-cup-winner` → one event, ~60 binary markets
  ("Will X win the 2026 FIFA World Cup?"), `outcomePrices[0]` = raw Yes price.
  Payload ~217 KB.

### Per-match moneyline (W/D/L)
- Each match is a Gamma event titled `"{home} vs. {away}"` (no `" - "` suffix),
  slug `fifwc-{h3}-{a3}-{YYYY-MM-DD}` (e.g. `fifwc-bra-mar-2026-06-13`), with
  exactly **3 markets**:
  - `Will {home} win on {date}?`  → Yes = P(home)
  - `Will {away} win on {date}?`  → Yes = P(away)
  - `Will {home} vs. {away} end in a draw?` → Yes = P(draw)
  - Sum ≈ 1 (small vig/underround). Payload by slug ~17 KB.
- Discover via tag **`102232` (FIFA World Cup)**: `GET /events?tag_id=102232&limit=100&closed=false`
  lists ~71 moneyline events (plus futures and `"- Player Props"` events with
  270 markets each). **The full list is ~4 MB** (props nested) — too heavy for
  the browser to poll; the pipeline pulls it server-side.
- **Match key:** the event's `endDate` equals our `kickoff_utc` exactly. Match
  PM events to our fixtures by kickoff timestamp; tie-break parallel kickoffs by
  normalized team names. No slug guessing, no team-code map needed.

## Architecture

**Split: heavy discovery server-side, light polling client-side.**

### Pipeline (Python, daily) — `data/fetcher_polymarket.py`, `visualization/dashboard.py`
- Fix champion slug → `world-cup-winner`.
- Champion: keep de-vigged `market` prob (existing) **and** add raw price so the
  client has a static decimal-odds fallback.
- New `fetch_match_moneylines()`: page tag 102232, filter to 3-market `"X vs. Y"`
  events, return `{kickoff_utc: {slug, home_price, draw_price, away_price, volume}}`
  keyed by kickoff (team-name cross-check via existing `TEAM_NAME_ALIASES`).
- `_build_matches()` attaches `market` (raw H/D/A prices + slug) to each match
  row in `data.json`. `_build_champions()` adds raw champion price.

### Browser (live, ~5 min) — new `web/lib/usePolymarket.ts` (mirrors `useLive`)
- Poll: (1) champion market (`world-cup-winner`); (2) the focus-day +
  in-progress matches' moneyline events **by stored slug** (few × 17 KB).
- Returns `{ champion: {team: rawPrice}, matches: {kickoff: {h,d,a}}, fresh }`.
- Components prefer live values; fall back to `data.json` snapshot; silent on
  failure (keep snapshot), same as the ESPN hook.

### Display — `web/lib/wc.ts`, `MatchCards.tsx`, `Views.tsx`, `app/page.tsx`
- `decimalOdds(p) = p > 0 ? 1 / p : null`, formatted `x.xx`. Uses **raw** price
  (vig included) per product decision.
- Champions page: `market` column → decimal odds (live raw). Edge recomputed
  live from static AI prob vs live **de-vigged** market; `models_agree` kept from
  snapshot. AI side stays a probability %.
- Match cards: new row under the W/D/L bar — `Polymarket 赔率 主x.xx / 平x.xx /
  客x.xx`, with a live dot when fresh.
- Freshness indicator in header / on cards (live vs snapshot time).

## Scope decisions
- Live polling covers only **today + in-progress** matches (history/future use
  the daily snapshot) — same philosophy as the ESPN score hook.
- AI side stays a probability %; only the market is shown as decimal odds.
- Decimal odds from **raw** price (tradeable odds), not de-vigged.

## Out of scope
- Per-match player props / corners / totals markets.
- Live polling of every fixture (only focus/in-progress).
- Historical odds charts.
