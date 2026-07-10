# Knockout Map Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the unused lower dashboard area with a real-data knockout map covering quarterfinals, semifinals, and the final.

**Architecture:** Add a focused `KnockoutMap` presentational component that derives stage columns from the existing `Match[]` and `LiveMap` props. Keep panel chrome and modal state in `Dashboard.tsx`, then change the large-desktop content grid to two rows with the champion panel spanning both rows and the knockout panel spanning the lower-left two columns.

**Tech Stack:** Next.js 16.2.9, React 19.2.4, TypeScript 5, Tailwind CSS 4, Playwright CLI.

## Global Constraints

- No new API, payload field, state store, odds feed, prediction calculation, collector, or pipeline change.
- Use only `data.matches` and the existing `live` map.
- Preserve the dark control-room palette, panel chrome, typography, reduced-motion behavior, and 4/8/12/16px spacing scale.
- Large desktop ≥1280px remains a single-screen dashboard.
- 768–1279px remains a natural-scroll two-column layout; below 768px remains single-column.
- Do not stage or commit pipeline-generated weather, research, or `web/public/*.json` artifacts.
- Do not fix unrelated existing ESLint errors in this plan.

---

### Task 1: Knockout Map Component and Match States

**Files:**
- Create: `web/components/KnockoutMap.tsx`
- Modify: `web/components/Dashboard.tsx:1-25, 1025-1060, 1260-1310`

**Interfaces:**
- Consumes: `Match[]`, `LiveMap`, `Flag`, `fmtTime()`, `pct()`, and `zh()`.
- Produces: `KnockoutMap({ matches, live, onOpen }: KnockoutMapProps): React.ReactElement`.
- Produces DOM markers `data-knockout-stage="qf|sf|final"` and `data-match-state="completed|active|unresolved"` for regression checks.

- [ ] **Step 1: Verify the current page fails the knockout-panel contract**

Run against the current static build:

```bash
python3 -m http.server 4174 --directory web/out
```

Keep that server session running, then run:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
playwright-cli -s=knockout open http://127.0.0.1:4174
playwright-cli -s=knockout resize 1920 1080
playwright-cli -s=knockout run-code "async page => { const panel=page.getByText('KNOCKOUT MAP',{exact:false}); if (await panel.count() === 0) throw new Error('KNOCKOUT MAP panel missing'); }"
```

Expected: FAIL with `KNOCKOUT MAP panel missing`.

- [ ] **Step 2: Create the standalone component with stable stage derivation**

Create `web/components/KnockoutMap.tsx` with these public and private interfaces:

```tsx
"use client";

import { Flag } from "@/components/icons";
import type { LiveMap, Match } from "@/lib/types";
import { fmtTime, pct, zh } from "@/lib/wc";

type KnockoutMapProps = {
  matches: Match[];
  live: LiveMap;
  onOpen: (match: Match) => void;
};

const STAGES = ["qf", "sf", "final"] as const;
type KnockoutStage = (typeof STAGES)[number];

const stageMatches = (matches: Match[], stage: KnockoutStage) =>
  matches
    .filter((match) => match.stage === stage)
    .sort((a, b) => a.kickoff_utc.localeCompare(b.kickoff_utc));

const unresolvedName = (name: string) => /\b(?:Winner|Loser)\b/i.test(name);

export function KnockoutMap({ matches, live, onOpen }: KnockoutMapProps) {
  const stages = STAGES.map((stage) => ({
    stage,
    matches: stageMatches(matches, stage),
  }));

  if (stages.every(({ matches: rows }) => rows.length === 0)) {
    return (
      <div className="mono flex h-full items-center justify-center p-6 text-[12px] text-[var(--ink-faint)]">
        淘汰赛对阵尚未生成
      </div>
    );
  }

  return (
    <div className="grid h-full grid-cols-1 gap-3 p-3 md:grid-cols-[minmax(0,1.25fr)_20px_minmax(0,1fr)_20px_minmax(0,.9fr)] md:gap-2">
      {/* StageColumn and connector instances are added in Step 4. */}
    </div>
  );
}
```

- [ ] **Step 3: Implement completed, active, and unresolved match nodes**

Add `KnockoutNode` above `KnockoutMap`. It must compute state without new effects:

```tsx
function KnockoutNode({
  match,
  live,
  onOpen,
  final = false,
}: {
  match: Match;
  live: LiveMap;
  onOpen: (match: Match) => void;
  final?: boolean;
}) {
  const liveEntry = live[match.espn_id];
  const completed = match.completed || !!liveEntry?.completed;
  const inPlay = liveEntry?.state === "in";
  const unresolved =
    match.tbd || unresolvedName(match.home) || unresolvedName(match.away);
  const homeScore = liveEntry?.home_score ?? match.home_score;
  const awayScore = liveEntry?.away_score ?? match.away_score;
  const advHome = match.pred?.p_adv_home ?? match.pred?.p_home;
  const advAway = match.pred?.p_adv_away ?? match.pred?.p_away;
  const winner = match.winner ??
    (completed && homeScore != null && awayScore != null && homeScore !== awayScore
      ? homeScore > awayScore ? match.home : match.away
      : null);
  const state = unresolved ? "unresolved" : completed ? "completed" : "active";

  const body = (
    <>
      <div className="flex items-center justify-between gap-2">
        <span
          className="lbl lbl-faint"
          style={final ? { color: "var(--mkt)" } : undefined}
        >
          {completed ? "FT" : inPlay ? liveEntry.clock || "LIVE" : fmtTime(match.kickoff_utc)}
        </span>
        {final ? <span className="lbl text-[var(--mkt)]">FINAL</span> : null}
      </div>
      {[match.home, match.away].map((team, index) => {
        const score = index === 0 ? homeScore : awayScore;
        return (
          <div key={team} className={`mt-1.5 flex items-center gap-2 ${winner && winner !== team ? "opacity-40" : ""}`}>
            {unresolved ? null : <Flag name={team} className="h-3.5 w-5 shrink-0" />}
            <span className="min-w-0 flex-1 truncate text-[12px] font-semibold">{zh(team)}</span>
            {score != null ? <span className="mono text-[12px] font-bold">{score}</span> : null}
          </div>
        );
      })}
      {!unresolved && !completed && advHome != null && advAway != null ? (
        <div className="mt-2">
          <div className="flex h-1 overflow-hidden rounded-[2px] bg-[var(--line)]">
            <span style={{ width: pct(advHome, 2), background: "var(--up)" }} />
            <span style={{ width: pct(advAway, 2), background: "var(--down)" }} />
          </div>
          <div className="mono mt-1 flex justify-between text-[10px] text-[var(--ink-faint)]">
            <span>{pct(advHome)}</span><span>{pct(advAway)}</span>
          </div>
        </div>
      ) : null}
    </>
  );

  const classes = `block w-full rounded-[3px] border p-2 text-left ${
    final ? "border-[var(--line-strong)] bg-[var(--panel-2)]" : "border-[var(--line)] bg-[var(--panel)]"
  }`;

  return unresolved ? (
    <div data-match-state={state} className={classes}>{body}</div>
  ) : (
    <button data-match-state={state} className={`${classes} transition-colors hover:border-[var(--line-strong)] focus-visible:outline focus-visible:outline-1 focus-visible:outline-[var(--up)]`} onClick={() => onOpen(match)}>
      {body}
    </button>
  );
}
```

- [ ] **Step 4: Render three stage columns and quiet connectors**

Add:

```tsx
const STAGE_LABEL: Record<KnockoutStage, string> = {
  qf: "QUARTERFINALS · 1/4 决赛",
  sf: "SEMIFINALS · 半决赛",
  final: "FINAL · 决赛",
};

function StageColumn({ stage, matches, live, onOpen }: {
  stage: KnockoutStage;
  matches: Match[];
  live: LiveMap;
  onOpen: (match: Match) => void;
}) {
  return (
    <section data-knockout-stage={stage} className="flex min-w-0 flex-col">
      <div className="lbl lbl-faint mb-2">{STAGE_LABEL[stage]}</div>
      <div className="flex min-h-0 flex-1 flex-col justify-around gap-2">
        {matches.map((match) => (
          <KnockoutNode key={match.espn_id} match={match} live={live} onOpen={onOpen} final={stage === "final"} />
        ))}
      </div>
    </section>
  );
}

const Connector = () => (
  <div aria-hidden className="hidden items-center md:flex">
    <span className="h-px w-full bg-[var(--line-strong)]" />
  </div>
);
```

Replace the placeholder inside `KnockoutMap` with:

```tsx
<StageColumn {...stages[0]} live={live} onOpen={onOpen} />
<Connector />
<StageColumn {...stages[1]} live={live} onOpen={onOpen} />
<Connector />
<StageColumn {...stages[2]} live={live} onOpen={onOpen} />
```

- [ ] **Step 5: Wrap the component in existing panel chrome and render it**

Import `KnockoutMap` in `Dashboard.tsx`. Add:

```tsx
function KnockoutMapPanel({ data, live, onOpenMatch, className }: {
  data: Data;
  live: LiveMap;
  onOpenMatch: (match: Match) => void;
  className?: string;
}) {
  return (
    <Panel
      idx="04"
      title="KNOCKOUT MAP 淘汰赛态势"
      className={className}
      aside={<span className="lbl lbl-faint">FT · LIVE/KICKOFF · AI ADV%</span>}
    >
      <KnockoutMap matches={data.matches} live={live} onOpen={onOpenMatch} />
    </Panel>
  );
}
```

Render it after `MatchdayPanel` with temporary classes
`order-2 md:col-span-2 xl:order-none`. Change `PerformancePanel` to `order-3` and `ChampionPanel` to `order-4` so mobile/tablet order is correct.

- [ ] **Step 6: Build and verify content/state counts**

Run:

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
cd web
npx tsc --noEmit
npm run build
cd ..
playwright-cli -s=knockout reload
playwright-cli -s=knockout resize 1920 1080
playwright-cli -s=knockout run-code "async page => { const counts={qf:await page.locator('[data-knockout-stage=qf] [data-match-state]').count(),sf:await page.locator('[data-knockout-stage=sf] [data-match-state]').count(),final:await page.locator('[data-knockout-stage=final] [data-match-state]').count()}; if(JSON.stringify(counts)!==JSON.stringify({qf:4,sf:2,final:1})) throw new Error(JSON.stringify(counts)); }"
```

Expected: TypeScript/build exit 0 and counts equal `4 / 2 / 1`.

- [ ] **Step 7: Commit the knockout component**

```bash
git add web/components/KnockoutMap.tsx web/components/Dashboard.tsx
git commit -m "feat(web): add knockout map panel"
```

---

### Task 2: Two-Row Desktop Grid and Responsive Placement

**Files:**
- Modify: `web/components/Dashboard.tsx:1270-1325`

**Interfaces:**
- Consumes: `KnockoutMapPanel` from Task 1.
- Produces: the exact large-desktop two-row grid and the specified tablet/mobile order.

- [ ] **Step 1: Verify the temporary placement fails the two-row geometry**

Run at 1920×1080:

```bash
playwright-cli -s=knockout resize 1920 1080
playwright-cli -s=knockout run-code "async page => { const ko=await page.getByText('KNOCKOUT MAP 淘汰赛态势',{exact:true}).locator('xpath=ancestor::section').boundingBox(); const perf=await page.getByText('AI PERFORMANCE',{exact:true}).locator('xpath=ancestor::section').boundingBox(); if(!ko||!perf||ko.y<=perf.y+perf.height) throw new Error('knockout panel is not on row 2'); }"
```

Expected: FAIL because the grid still has no explicit large-desktop second row.

- [ ] **Step 2: Add the exact two-row grid**

Change the main grid to:

```tsx
<div className="grid min-h-0 grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-[minmax(260px,22%)_minmax(0,1fr)_minmax(340px,26%)] xl:grid-rows-[minmax(360px,.9fr)_minmax(260px,.7fr)]">
```

Use these large-desktop placements:

```tsx
<PerformancePanel className="order-3 xl:col-start-1 xl:row-start-1 xl:order-none" ... />
<MatchdayPanel className="order-1 md:col-span-2 xl:col-span-1 xl:col-start-2 xl:row-start-1 xl:order-none" ... />
<KnockoutMapPanel className="order-2 md:col-span-2 xl:col-span-2 xl:col-start-1 xl:row-start-2 xl:order-none" ... />
<ChampionPanel className="order-4 xl:col-start-3 xl:row-span-2 xl:row-start-1 xl:order-none" ... />
```

- [ ] **Step 3: Verify desktop geometry and compact-desktop order**

After build, run:

```bash
playwright-cli -s=knockout reload
playwright-cli -s=knockout resize 1920 1080
playwright-cli -s=knockout run-code "async page => { const panels=await page.locator('.panel').evaluateAll(els=>els.slice(1,5).map(e=>({head:e.querySelector('.panel-head')?.textContent||'',r:(()=>{const r=e.getBoundingClientRect();return{x:r.x,y:r.y,width:r.width,height:r.height}})()}))); const ko=panels.find(x=>x.head.includes('KNOCKOUT')); const champ=panels.find(x=>x.head.includes('CHAMPION')); const perf=panels.find(x=>x.head.includes('PERFORMANCE')); if(!ko||!champ||!perf||ko.r.y<=perf.r.y+perf.r.height||champ.r.height<ko.r.y+ko.r.height-champ.r.y-2) throw new Error(JSON.stringify(panels)); }"
playwright-cli -s=knockout resize 1024 768
playwright-cli -s=knockout run-code "async page => { const heads=await page.locator('.panel').evaluateAll(els=>els.slice(1,5).sort((a,b)=>a.getBoundingClientRect().y-b.getBoundingClientRect().y||a.getBoundingClientRect().x-b.getBoundingClientRect().x).map(e=>e.querySelector('.panel-head')?.textContent||'')); if(!heads[0].includes('MATCHDAY')||!heads[1].includes('KNOCKOUT')) throw new Error(JSON.stringify(heads)); }"
```

Expected: both assertions pass.

- [ ] **Step 4: Verify a resolved node reuses MatchModal**

Run:

```bash
playwright-cli -s=knockout resize 1920 1080
playwright-cli -s=knockout run-code "async page => { await page.locator('[data-match-state=completed]').first().click(); }"
playwright-cli -s=knockout run-code "async page => { if(await page.getByText(/MATCH DETAIL/).count()===0) throw new Error('match modal did not open'); }"
playwright-cli -s=knockout press Escape
```

Expected: the existing match detail modal opens and closes.

- [ ] **Step 5: Commit the responsive dashboard grid**

```bash
git add web/components/Dashboard.tsx
git commit -m "refactor(web): add two-row knockout dashboard grid"
```

---

### Task 3: Visual Regression, Merge, and Deployment Readiness

**Files:**
- Modify only if verification exposes a source regression: `web/components/KnockoutMap.tsx`, `web/components/Dashboard.tsx`

**Interfaces:**
- Consumes: Tasks 1–2.
- Produces: verified responsive output ready to merge and deploy.

- [ ] **Step 1: Run the final static build**

```bash
export PATH=/home/ubuntu/.nvm/versions/node/v22.22.0/bin:$PATH
cd web
npx tsc --noEmit
npm run build
```

Expected: both commands exit 0 and static routes `/`, `/_not-found`, and `/icon.svg` are generated.

- [ ] **Step 2: Capture all target viewports and assert no horizontal overflow**

```bash
cd ..
for size in 1920x1080 2560x1440 3440x1440 1366x768 1180x820 1024x768 768x1024 390x844
do
  width=${size%x*}
  height=${size#*x}
  playwright-cli -s=knockout resize "$width" "$height"
  playwright-cli -s=knockout reload
  playwright-cli -s=knockout screenshot --filename=".playwright-cli/knockout-$size.png"
  playwright-cli -s=knockout run-code "async page => { const v=await page.evaluate(()=>({sw:document.body.scrollWidth,iw:innerWidth,sh:document.body.scrollHeight,ih:innerHeight})); if(v.sw>v.iw) throw new Error(JSON.stringify(v)); if(v.iw>=1280&&v.sh!==v.ih) throw new Error('desktop page scroll '+JSON.stringify(v)); }"
done
```

Expected: all eight assertions pass.

- [ ] **Step 3: Inspect visuals and console output**

Inspect 1920×1080, 1366×768, 1024×768, and 390×844 screenshots. Confirm:

- the knockout map fills the lower-left two columns on large desktop;
- champion race spans the full right side;
- 4/2/1 match nodes remain readable;
- connectors align with stage columns;
- tablet and mobile stage layouts do not overflow;
- unresolved nodes remain neutral and non-clickable.

Run:

```bash
playwright-cli -s=knockout console error
```

Expected: no application console errors.

- [ ] **Step 4: Check scope and existing lint baseline**

```bash
cd web
npm run lint
cd ..
git diff --check
git diff --name-only HEAD~2..HEAD
git status --short
```

Expected: lint may still report the existing 10 errors; the change must not add locations or increase the count. Implementation commits touch only `web/components/KnockoutMap.tsx` and `web/components/Dashboard.tsx`; generated data remains unstaged.

- [ ] **Step 5: If verification required a correction, commit only source files**

```bash
git add web/components/KnockoutMap.tsx web/components/Dashboard.tsx
git commit -m "fix(web): resolve knockout map visual regressions"
```

Skip this commit when the worktree is already clean.
