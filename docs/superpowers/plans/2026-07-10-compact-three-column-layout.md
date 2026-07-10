# Compact Three-Column Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WorldCup Oracle dashboard denser and more efficient for large-screen monitoring while preserving its three-column control-room identity and all existing data behavior.

**Architecture:** Keep the existing `Dashboard` component tree and change only presentational markup, Tailwind layout utilities, and shared CSS spacing primitives. Move the single-screen three-column breakpoint to 1280px, top-align panel content, flatten the performance summary, and tighten repeated rows without adding state or data dependencies.

**Tech Stack:** Next.js 16.2.9, React 19.2.4, TypeScript 5, Tailwind CSS 4, Playwright CLI.

## Global Constraints

- No data schema, fetching, hook, prediction, collector, or pipeline changes.
- Preserve the existing dark control-room palette, typography, semantic colors, and reduced-motion handling.
- Use a 4px spacing scale: 4, 8, 12, and 16px.
- Desktop ≥1280px remains a single-screen three-column layout.
- 768–1279px uses a two-column natural-scroll layout; below 768px remains single-column.
- Preserve all current match, model, market, ranking, drawer, and navigation information.
- Do not stage or commit pipeline-generated weather, research, or `web/public/*.json` artifacts.

---

### Task 1: Responsive Frame and Shared Spacing

**Files:**
- Modify: `web/app/globals.css:11-136`
- Modify: `web/components/Dashboard.tsx:1278-1307`

**Interfaces:**
- Consumes: existing `.panel`, `.panel-head`, `.panel-body`, and dashboard Tailwind classes.
- Produces: a 1280px single-screen breakpoint and semantic CSS spacing tokens used by later tasks.

- [ ] **Step 1: Verify the current 1024px layout fails the intended two-column contract**

Run against the current static build:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
playwright-cli open http://127.0.0.1:4173
playwright-cli resize 1024 768
playwright-cli run-code "async page => { const panels=[...await page.locator('.panel').all()]; const r=await panels[2].boundingBox(); if (!r || r.width < 900) throw new Error('MATCHDAY is not full-width at 1024px: '+JSON.stringify(r)); }"
```

Expected: FAIL because the current 1024px `MATCHDAY` panel is roughly 439px wide.

- [ ] **Step 2: Add the semantic 4px spacing scale and move panel scrolling to 1280px**

Add to `:root` in `web/app/globals.css`:

```css
  --space-xs: 4px;
  --space-sm: 8px;
  --space-md: 12px;
  --space-lg: 16px;
```

Replace `.panel-head` padding and the panel-scroll media query with:

```css
.panel-head {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--line);
  flex: none;
}

@media (min-width: 1280px) {
  .panel-body {
    overflow-y: auto;
  }
}
```

Update the adjacent comments so they describe the 1280px breakpoint.

- [ ] **Step 3: Change only the root dashboard layout utilities from `lg` to `xl`**

Use this root markup in `Dashboard.tsx`:

```tsx
<div className="dash-root flex min-h-dvh flex-col gap-2 p-2 xl:grid xl:h-dvh xl:grid-rows-[auto_minmax(0,1fr)_auto] xl:overflow-hidden">
```

Use this main grid and panel placement:

```tsx
<div className="grid min-h-0 grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(260px,22%)_minmax(0,1fr)_minmax(340px,26%)]">
  <PerformancePanel
    data={data}
    onOpen={() => setDrawer({ kind: "record" })}
    className="order-2 xl:order-none"
  />
  <MatchdayPanel
    data={data}
    live={live}
    poly={poly}
    onOpenMatch={(m) => setDrawer({ kind: "match", m })}
    className="order-1 md:col-span-2 xl:order-none xl:col-span-1"
  />
  <ChampionPanel
    data={data}
    poly={poly}
    onOpen={() => setDrawer({ kind: "champions" })}
    className="order-3 xl:order-none"
  />
</div>
```

Do not change `lg` utilities inside the match detail modal; those belong to the modal's own responsive layout.

- [ ] **Step 4: Build and verify both sides of the breakpoint**

Run:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
cd web
npx tsc --noEmit
npm run build
```

Expected: both commands exit 0.

Reload the static server, then run:

```bash
playwright-cli reload
playwright-cli resize 1024 768
playwright-cli run-code "async page => { const r=await page.locator('.panel').nth(2).boundingBox(); if (!r || r.width < 900) throw new Error('MATCHDAY width '+JSON.stringify(r)); if ((await page.evaluate(() => document.body.scrollWidth)) > 1024) throw new Error('horizontal overflow'); }"
playwright-cli resize 1366 768
playwright-cli run-code "async page => { const ps=await page.locator('.panel').all(); const boxes=await Promise.all(ps.slice(1,4).map(p=>p.boundingBox())); if (boxes.some(b=>!b) || new Set(boxes.map(b=>Math.round(b.y))).size !== 1) throw new Error('three-column row missing: '+JSON.stringify(boxes)); }"
```

Expected: both assertions pass.

- [ ] **Step 5: Commit the responsive frame**

```bash
git add web/app/globals.css web/components/Dashboard.tsx
git commit -m "refactor(web): tighten dashboard responsive frame"
```

---

### Task 2: Compact Performance Panel

**Files:**
- Modify: `web/components/Dashboard.tsx:202-392`

**Interfaces:**
- Consumes: existing `Data.performance`, `meta.match_edge`, `meta.calibration`, `STAGE_ZH`, and `zh()`.
- Produces: the same `PerformancePanel` props and behavior with a top-aligned, flatter presentation.

- [ ] **Step 1: Record the current tall-screen expansion as a failing visual metric**

At 1920×1080, run:

```bash
playwright-cli resize 1920 1080
playwright-cli run-code "async page => { const body=page.locator('.panel').nth(1).locator('.panel-body > div'); const sections=await body.locator(':scope > div').all(); const verdict=await sections[4].boundingBox(); if (!verdict || verdict.height > 180) throw new Error('verdict region is stretched: '+JSON.stringify(verdict)); }"
```

Expected: FAIL because the verdict region currently absorbs the unused panel height.

- [ ] **Step 2: Replace the hero and Brier cards with one compact summary band**

Change the outer wrapper to:

```tsx
<div className="flex h-full flex-col gap-3 p-3">
```

Replace the first two cards with:

```tsx
<div className="grid grid-cols-[minmax(0,1fr)_minmax(104px,.72fr)] border-b border-[var(--line)] pb-3">
  <div className="pr-3">
    <div className="flex items-end justify-between gap-2">
      <span className="mono text-3xl font-bold leading-none" style={{ color: "var(--up)" }}>
        {winPct}
      </span>
      <span className="lbl text-right leading-[1.25]">胜平负<br />判对率</span>
    </div>
    <div className="lbl lbl-faint mt-2">WINNER HIT · {p.details.length} MATCHES</div>
  </div>
  <div className="border-l border-[var(--line)] pl-3">
    <div className="flex items-baseline justify-between gap-2">
      <span className="lbl">BRIER</span>
      <span className="mono text-[15px] font-semibold">{brier}</span>
    </div>
    <div className="bar-track mt-2">
      <div className="bar-fill" style={{ width: `${brierBar * 100}%`, background: "var(--up)" }} />
    </div>
    <div className="lbl lbl-faint mt-2">基线 .667</div>
  </div>
</div>
```

- [ ] **Step 3: Flatten analytical groups and remove vertical stretch**

Change the stage section wrapper to:

```tsx
<div className="border-t border-[var(--line)] pt-3">
```

Change the recent-verdict wrapper from `flex min-h-0 flex-1 flex-col` to:

```tsx
<div className="flex flex-col">
```

Change its score summary from `mt-auto pt-3` to:

```tsx
className="mono mt-3 text-[11px]"
```

Keep the ensemble and calibration blocks immediately after it. Do not change the number of verdicts or any performance calculations.

- [ ] **Step 4: Verify the panel no longer stretches related content apart**

Run:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
cd web
npx tsc --noEmit
npm run build
cd ..
playwright-cli reload
playwright-cli resize 1920 1080
playwright-cli run-code "async page => { const body=page.locator('.panel').nth(1).locator('.panel-body > div'); const sections=await body.locator(':scope > div').all(); const verdict=await sections[3].boundingBox(); if (!verdict || verdict.height > 180) throw new Error('verdict region still stretched: '+JSON.stringify(verdict)); }"
```

Expected: TypeScript and build exit 0; the browser assertion passes.

- [ ] **Step 5: Commit the performance panel**

```bash
git add web/components/Dashboard.tsx
git commit -m "refactor(web): compact performance panel hierarchy"
```

---

### Task 3: Top-Align Matchday and Tighten Repeated Rows

**Files:**
- Modify: `web/components/Dashboard.tsx:120-182`
- Modify: `web/components/Dashboard.tsx:765-1028`
- Modify: `web/components/Dashboard.tsx:1031-1080`

**Interfaces:**
- Consumes: unchanged `MatchdayPanel`, `ChampionPanel`, `TopBar`, and `Ticker` props.
- Produces: unchanged component contracts with tighter vertical rhythm.

- [ ] **Step 1: Record the current floating focus region as a failing metric**

Run at 1920×1080:

```bash
playwright-cli resize 1920 1080
playwright-cli run-code "async page => { const panel=page.locator('.panel').nth(2); const body=await panel.locator('.panel-body').boundingBox(); const focus=await panel.locator('.panel-body > div > div').first().boundingBox(); if (!body || !focus || focus.height > 500) throw new Error('focus wrapper consumes spare height: '+JSON.stringify({body,focus})); }"
```

Expected: FAIL because the focus wrapper currently grows to fill the panel and uses `justify-evenly`.

- [ ] **Step 2: Top-align focus matches and attach `NEXT UP`**

Replace the focus wrapper with:

```tsx
<div className="flex flex-col gap-2 p-3">
```

Keep the focus card mapping unchanged. Retain the existing `NEXT UP` container directly after this wrapper, but tighten its header to `px-3 py-1.5` and each `NextUpRow` to `px-3 py-1.5`.

- [ ] **Step 3: Tighten champion rows and chrome using the 4px scale**

Change each champion row from `px-3 py-2` to `px-3 py-1.5`, and its bar group from `mt-1` to `mt-0.5`. Change the maximum-divergence block from `p-3` to `p-2` with `space-y-1.5`, and the final action row from `py-2.5` to `py-2`.

Change `TopBar` from `px-3.5 py-2.5` to `px-3 py-2`. Change `Ticker` from `px-3.5 py-2` to `px-3 py-1.5`. Preserve their information and ordering.

- [ ] **Step 4: Verify the focus wrapper, champion density, and build**

Run:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
cd web
npx tsc --noEmit
npm run build
cd ..
playwright-cli reload
playwright-cli resize 1920 1080
playwright-cli run-code "async page => { const focus=await page.locator('.panel').nth(2).locator('.panel-body > div > div').first().boundingBox(); const row=await page.locator('.panel').nth(3).locator('.panel-body [class*=border-t]').first().boundingBox(); if (!focus || focus.height > 500) throw new Error('focus wrapper '+JSON.stringify(focus)); if (!row || row.height > 48) throw new Error('champion row '+JSON.stringify(row)); }"
```

Expected: TypeScript and build exit 0; both bounding-box assertions pass.

- [ ] **Step 5: Commit the dense monitoring rhythm**

```bash
git add web/components/Dashboard.tsx
git commit -m "refactor(web): tighten live dashboard vertical rhythm"
```

---

### Task 4: Responsive Visual Regression and Handoff

**Files:**
- Modify only if verification exposes a layout regression: `web/app/globals.css`, `web/components/Dashboard.tsx`

**Interfaces:**
- Consumes: the completed layout from Tasks 1–3.
- Produces: verified desktop, compact-desktop, tablet, and mobile layouts with no data-logic diff.

- [ ] **Step 1: Build the final static export**

Run:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
cd web
npx tsc --noEmit
npm run build
```

Expected: both commands exit 0 and the static routes `/`, `/_not-found`, and `/icon.svg` are generated.

- [ ] **Step 2: Capture and assert all target viewports**

For each viewport, reload the static site, save a screenshot, and assert no horizontal overflow:

```bash
cd ..
for size in 1920x1080 2560x1440 3440x1440 1366x768 1180x820 1024x768 768x1024 390x844; do
  width=${size%x*}; height=${size#*x}
  playwright-cli resize "$width" "$height"
  playwright-cli reload
  playwright-cli screenshot --filename=".playwright-cli/compact-$size.png"
  playwright-cli run-code "async page => { const v=await page.evaluate(() => ({sw:document.body.scrollWidth,iw:innerWidth})); if (v.sw > v.iw) throw new Error('horizontal overflow '+JSON.stringify(v)); }"
done
```

Expected: all eight assertions pass.

- [ ] **Step 3: Inspect visual hierarchy and browser console**

Open the 1920×1080, 1366×768, 1024×768, and 390×844 screenshots. Confirm:

- focus match is the first obvious element after the header;
- no related blocks are separated by a large internal gap;
- 1024px uses a full-width `MATCHDAY` row;
- left-panel verdicts and model metadata do not overlap;
- mobile panel order remains matchday, performance, champion;
- text remains readable and no critical content is hidden.

Run:

```bash
playwright-cli console error
```

Expected: no application console errors.

- [ ] **Step 4: Check lint without hiding existing debt**

Run:

```bash
cd web
npm run lint
```

Expected baseline: the repository may still report the previously recorded 10 React/ESLint errors. Confirm the layout changes introduce no additional error locations or count; report the baseline honestly rather than claiming lint is green.

- [ ] **Step 5: Confirm scope and commit any verification-only correction**

Run:

```bash
cd ..
git diff --check
git diff --name-only HEAD~3..HEAD
git status --short
```

Expected: implementation commits touch only `web/app/globals.css` and `web/components/Dashboard.tsx`; pipeline-generated artifacts remain unstaged. If visual verification required a correction, stage only those two source files and commit:

```bash
git add web/app/globals.css web/components/Dashboard.tsx
git commit -m "fix(web): resolve compact dashboard visual regressions"
```
