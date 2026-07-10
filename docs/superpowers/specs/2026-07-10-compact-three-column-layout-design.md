# WorldCup Oracle Compact Three-Column Layout Design

**Date:** 2026-07-10  
**Status:** Approved direction — Option B, compact three-column dashboard

## Context

The dashboard is primarily used by its owner for long-running monitoring on a
large desktop display. The desired character is compact, efficient,
professional, restrained, and strongly real-time. This pass improves spatial
composition and density without changing prediction, market, live-score, or
weather data flows.

## Current Problems

Visual inspection at 1920×1080, 1440×900, and 1024×768 identified four layout
problems:

1. The focus match floats vertically in the center panel while `NEXT UP` is
   pinned to the bottom, leaving large gaps between related information.
2. The performance panel uses a growing flex region to push its model metadata
   to the bottom. On tall displays this creates a large empty band; at 1024px
   the same structure crowds and visually overlaps the verdict grid.
3. The three-column layout starts at 1024px even though the side panels need
   more width. This makes the desktop composition too dense at 1024–1279px.
4. Spacing is individually reasonable but lacks a single rhythm: adjacent
   groups mix 8, 10, 12, and 14px padding without a clear relationship.

## Chosen Direction

Retain the existing three-column mission-control information architecture. Do
not introduce a new navigation model, new dashboard metrics, decorative
effects, or a different visual identity. Improve density through top alignment,
flatter grouping, consistent spacing, and a safer responsive breakpoint.

## Layout Structure

### Large desktop: 1280px and above

- Keep a single-screen structure: compact top bar, three-column dashboard,
  compact bottom ticker.
- Use the exact grid
  `minmax(260px,22%) minmax(0,1fr) minmax(340px,26%)`.
- Keep an 8px outer page inset and 8px inter-panel gaps.
- Panels remain equal height for a stable control-room silhouette, but their
  content is top-aligned. Any unused capacity remains below the content instead
  of being inserted between related sections.
- Panel bodies scroll internally only when viewport height is insufficient.

### Tablet and compact desktop: 768–1279px

- Use the existing two-column composition instead of forcing three columns.
- `MATCHDAY` spans the full top row; `PERFORMANCE` and `CHAMPION RACE` share the
  row below.
- Use natural document scrolling. Do not lock the page height or introduce
  nested panel scrolling in this range.

### Mobile: below 768px

- Preserve the current single-column order: `MATCHDAY`, `PERFORMANCE`, then
  `CHAMPION RACE`.
- Keep all critical information available; adapt rather than hide.

## Spacing System

Use a 4px base scale:

- 4px: micro spacing inside labels, badges, and compact rows.
- 8px: standard sibling gap and panel-to-panel gap.
- 12px: primary panel-body inset and separation between content groups.
- 16px: separation for major sub-sections when a divider is not sufficient.

Avoid new arbitrary padding values. Prefer `gap` for sibling layout and subtle
dividers for grouping. Keep existing 11–13px monitoring text; density must not
come from reducing legibility.

## Component Changes

### TopBar and Ticker

- Reduce vertical padding enough to make the header and ticker visibly compact
  while preserving their current information.
- Keep the UTC clock, connection state, market volume, sync time, and navigation
  actions in their existing order.
- Preserve the live dot as the primary animated element.

### PerformancePanel

- Replace the vertically stacked hero treatment with a compact summary band for
  hit rate and mean Brier.
- Keep the champion-market and match-market comparisons as a two-column row.
- Retain stage accuracy and recent verdicts, but remove flex growth that pushes
  the model/calibration metadata to the bottom of the viewport.
- Place model and calibration metadata directly after the verdict section,
  separated by a divider.
- Use dividers and alignment instead of additional nested-card backgrounds where
  the content belongs to the same analytical group.

### MatchdayPanel

- Top-align the focus match immediately below the panel header.
- Place `NEXT UP` directly after the focus card with an 8–12px group gap; do not
  pin it to the bottom of the panel.
- Preserve all current prediction, scoreline, model, market, head-to-head, and
  summary content.
- Reduce internal padding and gaps using the shared 4px scale without changing
  text size or truncating critical information.

### ChampionPanel

- Tighten row height and vertical padding while retaining rank, flag, team,
  edge, AI probability, market probability, and dual bars.
- Keep the maximum-divergence section directly after the visible ranking.
- Allow short desktop viewports to scroll internally; do not compress rows below
  a comfortable scan height.

## Interaction and Accessibility

- No interaction behavior changes are required.
- Preserve keyboard-operable buttons and existing drawer/modal behavior.
- State must remain understandable through text and numbers, not color alone.
- Preserve reduced-motion handling and avoid new ambient animations.

## Data and Architecture

- No data schema, fetching, hook, prediction, collector, or pipeline changes.
- Keep the existing `Dashboard` component hierarchy and drawer contracts.
- Prefer CSS/Tailwind layout changes and small presentational reshaping over new
  state or effects.

## Verification

Validate with fresh browser captures at:

- 1920×1080, 2560×1440, and 3440×1440: single-screen three-column layout, no
  page scroll, obvious focus-match hierarchy, and no large gaps between related
  blocks.
- 1366×768: three columns remain readable, with internal panel scroll only when
  necessary and no clipping.
- 1024×768 and 1180×820: two-column layout, no overlap or horizontal overflow.
- 768×1024 and 390×844: natural scroll, correct panel order, no horizontal
  overflow.

Run TypeScript checking and a production build. Compare screenshots before and
after, inspect browser console output, and confirm that the Git diff contains no
data or business-logic changes.

## Out of Scope

- New metrics, charts, tabs, routes, or live-data sources.
- A visual rebrand, new color palette, typography replacement, or motion pass.
- Collector, prediction-model, research, and deployment changes.
- Unrelated pre-existing lint cleanup outside the layout components touched by
  this pass.
