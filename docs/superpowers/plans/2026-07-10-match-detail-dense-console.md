# MATCH DETAIL Dense Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the sparse fixed-height three-column MATCH DETAIL with a content-driven two-column console whose pre-match stats collapse and whose in-play stats expand.

**Architecture:** Keep `MatchModal` as the composition boundary and add presentation-only variants to `LiveStats` and `MatchDetail`. No data hook, API, prediction, or market behavior changes. Browser assertions provide the red/green layout contract because the project has no component test runner.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, Playwright CLI, Cloudflare Pages

## Global Constraints

- Preserve all existing match, model, weather, live-stat, and Polymarket data behavior.
- Use the existing 4/8/12/16px spacing rhythm and dark control-room visual language.
- Desktop uses a roughly 60/40 two-column layout with the market column at least 420px wide.
- Below `xl` (1280px), content order is prediction → live stats → market and the dialog scrolls naturally.
- Do not add dependencies or change APIs, data structures, subscriptions, or prediction logic.
- Existing default `LiveStats` and `MatchDetail` call sites must remain visually unchanged.

---

### Task 1: Add compact adaptive live stats

**Files:**
- Modify: `web/components/LiveStats.tsx`
- Test: Playwright browser assertion against the built dashboard

**Interfaces:**
- Consumes: existing `LiveStats` props `espnId`, `home`, `away`, and `live`
- Produces: optional `compact?: boolean` prop plus `data-live-stats-mode` and `data-live-stats-state` DOM contracts

- [ ] **Step 1: Write the failing browser assertion**

Open an upcoming match and require the compact contract before it exists:

```bash
playwright-cli -s=match-detail run-code "async page => {
  await page.locator('[data-match-state=active]').first().click();
  const stats = page.locator('[data-live-stats-mode=compact]');
  if (await stats.count() !== 1) throw new Error('compact live stats missing');
}"
```

- [ ] **Step 2: Run the assertion to verify it fails**

Expected: FAIL with `compact live stats missing`.

- [ ] **Step 3: Add the compact presentation prop and state markers**

Extend the signature without changing existing callers:

```tsx
export function LiveStats({
  espnId,
  home,
  away,
  live,
  compact = false,
}: {
  espnId: string;
  home: string;
  away: string;
  live: boolean;
  compact?: boolean;
}) {
  const stats = useMatchStats(espnId, true);
  const started = !!stats && stats.state !== "pre";
  const state = started ? "started" : live ? "loading" : "pre";
```

Give the root an observable contract and use the existing visual style for the default branch:

```tsx
<div
  data-live-stats-mode={compact ? "compact" : "default"}
  data-live-stats-state={state}
  className={`border border-zinc-800/80 bg-zinc-950/60 ${compact ? "rounded-[3px] p-2" : "rounded-xl p-3"}`}
>
```

For `compact && !started`, render one dense row instead of the current tall empty body:

```tsx
<div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1">
  <span className="lbl lbl-faint">04</span>
  <span className="lbl text-[var(--ink)]">LIVE STATS · 实时数据</span>
  <span className="lbl lbl-faint ml-auto">{live ? "加载中…" : "开赛后更新"}</span>
  <span className="mono basis-full text-[10px] text-[var(--ink-faint)] sm:ml-auto sm:basis-auto">
    控球 · 射门 · 角球 · 牌
  </span>
</div>
```

For `compact && started`, retain the current `ROWS.map((r) => { ... })` block byte-for-byte and change only its parent class from `space-y-2` to this conditional class:

```tsx
<div className={compact ? "grid gap-x-4 gap-y-1.5 sm:grid-cols-2" : "space-y-2"}>
  {ROWS.map((r) => {
    const h = stats!.home[r.name];
    const a = stats!.away[r.name];
    if (h == null && a == null) return null;
    const hv = h ?? 0;
    const av = a ?? 0;
    const total = hv + av;
    const hShare = total > 0 ? (hv / total) * 100 : 50;
    const hLead = hv > av;
    const aLead = av > hv;
    return (
      <div key={r.name}>
        <div className="mono flex items-center justify-between text-[12px] tabular-nums">
          <span style={{ color: hLead ? "var(--up)" : "var(--ink-dim)", fontWeight: hLead ? 700 : 400 }}>
            {fmt(hv, r.pct, r.scale)}
          </span>
          <span className="lbl lbl-faint">{r.label}</span>
          <span style={{ color: aLead ? "var(--down)" : "var(--ink-dim)", fontWeight: aLead ? 700 : 400 }}>
            {fmt(av, r.pct, r.scale)}
          </span>
        </div>
        <div className="mt-1 flex h-1 overflow-hidden rounded-sm bg-[rgba(255,255,255,.05)]">
          <div style={{ width: `${hShare}%`, background: "var(--up)" }} />
          <div style={{ width: `${100 - hShare}%`, background: "var(--down)" }} />
        </div>
      </div>
    );
  })}
</div>
```

- [ ] **Step 4: Enable compact mode in `MatchModal` temporarily for the green check**

```tsx
<LiveStats
  espnId={m.espn_id}
  home={m.home}
  away={m.away}
  live={m.completed || live[m.espn_id]?.state === "in" || !!live[m.espn_id]?.completed}
  compact
/>
```

- [ ] **Step 5: Build and verify the compact assertion passes**

Run:

```bash
cd web
npx tsc --noEmit
npm run build
```

Expected: both commands exit 0. Reload the browser and rerun Step 1; expected PASS. Assert the pre-match compact block is no taller than 72px:

```bash
playwright-cli -s=match-detail run-code "async page => {
  const stats = page.locator('[data-live-stats-mode=compact]');
  const height = await stats.evaluate(e => e.getBoundingClientRect().height);
  if (height > 72) throw new Error('pre-match stats too tall: ' + height);
  return height;
}"
```

- [ ] **Step 6: Commit**

```bash
git add web/components/LiveStats.tsx web/components/Dashboard.tsx
git commit -m "refactor(web): add compact live stats mode"
```

---

### Task 2: Flatten the order-book console surface

**Files:**
- Modify: `web/components/MatchDetail.tsx`
- Modify: `web/components/Dashboard.tsx`
- Test: Playwright browser assertion against the built dashboard

**Interfaces:**
- Consumes: existing `MatchDetail` data props
- Produces: optional `variant?: "card" | "console"` prop; default remains `"card"`

- [ ] **Step 1: Write the failing console-variant assertion**

```bash
playwright-cli -s=match-detail run-code "async page => {
  const detail = page.locator('[data-match-detail-variant=console]');
  if (await detail.count() !== 1) throw new Error('console order book missing');
}"
```

- [ ] **Step 2: Run the assertion to verify it fails**

Expected: FAIL with `console order book missing`.

- [ ] **Step 3: Add a presentation-only variant**

Extend the component signature:

```tsx
export function MatchDetail({
  slug,
  kickoffUtc,
  home,
  away,
  pred,
  liveEntry,
  variant = "card",
}: {
  slug: string;
  kickoffUtc: string;
  home: string;
  away: string;
  pred?: Pred;
  liveEntry?: LiveEntry;
  variant?: "card" | "console";
}) {
```

Select the outer surface from the variant while leaving every market section intact:

```tsx
const consoleMode = variant === "console";

return (
  <div
    data-match-detail-variant={variant}
    className={
      consoleMode
        ? "space-y-2"
        : "mt-3 space-y-3 rounded-xl border border-zinc-800/80 bg-zinc-950/60 p-3"
    }
  >
```

Use the same variant classes for the error state so it does not reintroduce a nested card in the modal:

```tsx
const errorClass = consoleMode
  ? "py-8 text-center text-xs text-zinc-600"
  : "mt-3 rounded-xl border border-zinc-800/80 bg-zinc-950/60 p-3 text-center text-xs text-zinc-600";
```

- [ ] **Step 4: Enable the console variant only in `MatchModal`**

```tsx
<MatchDetail
  slug={slug}
  kickoffUtc={m.kickoff_utc}
  home={m.home}
  away={m.away}
  pred={m.pred}
  liveEntry={live[m.espn_id]}
  variant="console"
/>
```

- [ ] **Step 5: Build and verify the variant passes**

Run `npx tsc --noEmit && npm run build` from `web/`; expected exit 0. Reload and rerun Step 1; expected PASS. Also verify the console root has no border or top margin:

```bash
playwright-cli -s=match-detail run-code "async page => {
  const detail = page.locator('[data-match-detail-variant=console]');
  const style = await detail.evaluate(e => ({
    border: getComputedStyle(e).borderTopWidth,
    marginTop: getComputedStyle(e).marginTop,
  }));
  if (style.border !== '0px' || style.marginTop !== '0px') throw new Error(JSON.stringify(style));
  return style;
}"
```

- [ ] **Step 6: Commit**

```bash
git add web/components/MatchDetail.tsx web/components/Dashboard.tsx
git commit -m "refactor(web): flatten match order book console"
```

---

### Task 3: Replace the fixed three-column modal with a content-driven two-column console

**Files:**
- Modify: `web/components/Dashboard.tsx`
- Test: Playwright browser assertions at desktop and mobile sizes

**Interfaces:**
- Consumes: compact `LiveStats` and console `MatchDetail` from Tasks 1–2
- Produces: `data-match-modal-grid` DOM contract and prediction → stats → market source order

- [ ] **Step 1: Write the failing desktop geometry assertion**

```bash
playwright-cli -s=match-detail resize 1920 1080
playwright-cli -s=match-detail run-code "async page => {
  const grid = page.locator('[data-match-modal-grid]');
  if (await grid.count() !== 1) throw new Error('two-column modal grid missing');
  const columns = await grid.locator(':scope > section').count();
  if (columns !== 2) throw new Error('expected 2 columns, got ' + columns);
}"
```

- [ ] **Step 2: Run the assertion to verify it fails**

Expected: FAIL with `two-column modal grid missing`.

- [ ] **Step 3: Implement the content-driven shell and two-column composition**

Replace the fixed inline height and three-column grid with:

```tsx
<div
  className="panel reveal flex max-h-[calc(100dvh-16px)] w-full max-w-[1440px] flex-col xl:max-h-[90vh]"
  onClick={(e) => e.stopPropagation()}
>
  <div className="panel-head">
    <span className="lbl lbl-faint">▚</span>
    <span className="lbl text-[var(--ink)]">MATCH DETAIL · {zh(m.home)} vs {zh(m.away)}</span>
    <span className="lbl lbl-faint ml-2 hidden sm:inline">
      {(m.stage === "group" && m.group ? `${m.group}组` : STAGE_ZH[m.stage] ?? m.stage)}
      {m.city ? ` · ${m.city}` : ""}
    </span>
    <button onClick={onClose} className="ml-auto flex h-6 w-6 items-center justify-center rounded-[3px] border border-[var(--line)]" aria-label="关闭">
      <XIcon className="h-3.5 w-3.5" />
    </button>
  </div>
  <div
    data-match-modal-grid
    className="grid min-h-0 max-h-[calc(100dvh-54px)] grid-cols-1 overflow-y-auto xl:max-h-[calc(90vh-37px)] xl:grid-cols-[minmax(0,3fr)_minmax(420px,2fr)] xl:overflow-hidden"
  >
    <section className="drawer-scroll min-h-0 space-y-3 border-b border-[var(--line)] p-3 xl:overflow-y-auto xl:border-b-0 xl:border-r">
      <FocusCard m={m} meta={meta} live={live} poly={poly} weather={weather} hideBook />
      <LiveStats
        espnId={m.espn_id}
        home={m.home}
        away={m.away}
        live={m.completed || live[m.espn_id]?.state === "in" || !!live[m.espn_id]?.completed}
        compact
      />
    </section>
    <section className="drawer-scroll min-h-0 p-3 xl:overflow-y-auto">
      <div className="mb-2 flex items-center gap-2">
        <span className="lbl lbl-faint">05</span>
        <span className="lbl text-[var(--ink)]">LIVE 盘口 · ORDER BOOK</span>
      </div>
      {slug ? (
        <MatchDetail
          slug={slug}
          kickoffUtc={m.kickoff_utc}
          home={m.home}
          away={m.away}
          pred={m.pred}
          liveEntry={live[m.espn_id]}
          variant="console"
        />
      ) : (
        <div className="mono flex min-h-40 items-center justify-center text-center text-[12px] text-[var(--ink-faint)]">
          该场暂无 Polymarket 盘口
        </div>
      )}
    </section>
  </div>
</div>
```

Do not use `my-auto`, a fixed `height`, or a dedicated empty stats column.

- [ ] **Step 4: Build and verify desktop geometry**

Run `npx tsc --noEmit && npm run build` from `web/`; expected exit 0. Reload and rerun Step 1; expected PASS. Then verify content-driven height and column ratio:

```bash
playwright-cli -s=match-detail run-code "async page => {
  const dialog = page.locator('.fixed.inset-0.z-50 > .panel');
  const grid = page.locator('[data-match-modal-grid]');
  const box = await dialog.evaluate(e => e.getBoundingClientRect().toJSON());
  const cols = await grid.locator(':scope > section').evaluateAll(els => els.map(e => e.getBoundingClientRect().width));
  const viewport = page.viewportSize();
  if (box.height >= (viewport?.height ?? 1080) * .9) throw new Error('dialog still fixed-height: ' + box.height);
  const ratio = cols[0] / cols[1];
  if (ratio < 1.35 || ratio > 1.65) throw new Error('unexpected column ratio: ' + ratio);
  return { box, cols, ratio };
}"
```

- [ ] **Step 5: Verify responsive source order and overflow**

Run the following sizes: 1920×1080, 1366×768, 1024×768, and 390×844.

```bash
playwright-cli -s=match-detail run-code "async page => {
  const sizes = [[1920,1080],[1366,768],[1024,768],[390,844]];
  const results = [];
  for (const [width,height] of sizes) {
    await page.setViewportSize({ width, height });
    const metrics = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    if (metrics.scrollWidth > metrics.clientWidth + 1) throw new Error('horizontal overflow at ' + width);
    results.push({ width, height, ...metrics });
  }
  return results;
}"
```

At 1024px and 390px, inspect the DOM/source order and screenshot to confirm prediction → live stats → market.

- [ ] **Step 6: Verify interactions and both stats states**

- Open an upcoming knockout node: expect `data-live-stats-state="pre"` or `"loading"`, height ≤72px.
- Switch each available outcome tab: selected visual state changes and the depth ladder remains visible.
- Close with `Escape`, reopen a completed knockout node, and wait for `data-live-stats-state="started"`; expect the expanded metric matrix when ESPN provides stats.
- Close with the icon and verify the modal leaves the DOM.

- [ ] **Step 7: Commit**

```bash
git add web/components/Dashboard.tsx
git commit -m "refactor(web): compact match detail into two columns"
```

---

### Task 4: Final regression, merge, and deploy

**Files:**
- Verify: `web/components/Dashboard.tsx`
- Verify: `web/components/LiveStats.tsx`
- Verify: `web/components/MatchDetail.tsx`

**Interfaces:**
- Consumes: completed Tasks 1–3
- Produces: verified production deployment

- [ ] **Step 1: Run fresh static checks**

```bash
cd web
npx tsc --noEmit
npm run build
npx eslint components/LiveStats.tsx components/MatchDetail.tsx
```

Expected: TypeScript, production build, and targeted ESLint all exit 0. Run full `npm run lint` and confirm the repository does not exceed its existing baseline of 10 errors.

- [ ] **Step 2: Run final browser regression**

Repeat Task 3 at 1920×1080, 1366×768, 1024×768, and 390×844. Capture screenshots after the reveal animation settles. Verify there are no unexpected console errors and that the order-book tabs, `Escape`, close icon, and backdrop close all work.

- [ ] **Step 3: Review the diff and repository scope**

```bash
git diff --check
git status --short
git log --oneline main..HEAD
```

Expected: only the three scoped frontend files are changed by implementation commits; generated weather and live-data changes in the main workspace remain untouched.

- [ ] **Step 4: Merge the verified branch and rebuild on `main`**

Fast-forward merge the feature branch into `main`, then run `npm run build` again from `web/`. Remove the owned `.worktrees/` worktree only after the merged build succeeds.

- [ ] **Step 5: Deploy and verify production**

```bash
npx wrangler pages deploy web/out --project-name worldcup-oracle --branch main --commit-dirty=true
```

Open `https://worldcup-oracle.pages.dev` at 1920×1080, open MATCH DETAIL, and rerun the two-column geometry, compact-stats, no-overflow, and close-interaction assertions.
