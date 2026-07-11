import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { buildScoreDistribution, conditionDistribution } from "../lib/forecastAnalytics";
import type { KalshiMarketState, Match, PolyLive } from "../lib/types";
import { kickoffEpoch } from "../lib/wc";
import { ForecastAnalyticsTabs } from "./ForecastAnalyticsTabs";

const match = {
  espn_id: "401", kickoff_utc: "2026-07-10T18:00:00Z", stage: "group", group: "B", venue: "Oracle Park", city: "Seattle",
  home: "Spain", away: "Belgium", tbd: false, completed: false, status: null, home_score: null, away_score: null, winner: null,
  pred: {
    p_home: .46, p_draw: .27, p_away: .27, elo_home: 1884, elo_away: 1852, per_model: [],
    scoreline: { xg_home: 1.42, xg_away: 1.08, p_over25: .46, p_btts: .53, most_likely: "1-1", most_likely_p: .12, top_scores: [{ score: "1-1", p: .12 }, { score: "1-0", p: .11 }, { score: "2-1", p: .09 }] },
  },
} satisfies Match;

const poly = (prices: { home: number; draw: number; away: number } | null = { home: .42, draw: .29, away: .29 }): PolyLive => ({
  champion: {}, matches: prices ? { [kickoffEpoch(match.kickoff_utc)]: { ...prices, src: "ws", ts: Date.parse("2026-07-10T17:59:55Z") } } : {},
  championFresh: true, updatedAt: Date.parse("2026-07-10T17:59:55Z"), wsConnected: true,
});

const kalshi: KalshiMarketState = {
  status: "live", source: "kalshi-rest", eventTicker: "KXWC", updatedAt: Date.parse("2026-07-10T17:59:55Z"), outcomes: {}, stale: false, failures: 0,
};

const text = (root: ReactTestRenderer) => JSON.stringify(root.toJSON());

describe("ForecastAnalyticsTabs", () => {
  let root: ReactTestRenderer | null = null;

  beforeEach(() => {
    (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    vi.spyOn(console, "error").mockImplementation((message, ...args) => {
      if (String(message).includes("react-test-renderer is deprecated")) return;
      console.warn(message, ...args);
    });
  });

  afterEach(() => {
    if (root) act(() => root?.unmount());
    root = null;
    vi.restoreAllMocks();
    vi.useRealTimers();
    delete (globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
  });

  const render = (props: Partial<React.ComponentProps<typeof ForecastAnalyticsTabs>> = {}) => {
    act(() => {
      root = create(createElement(ForecastAnalyticsTabs, { match, poly: poly(), kalshi, ...props }));
    });
    return root!;
  };

  it("defaults to scores and switches every tab panel", () => {
    const rendered = render();

    expect(rendered.root.findByProps({ "data-forecast-tab": "scores" }).props["aria-selected"]).toBe(true);
    expect(text(rendered)).toContain("比分分布");
    act(() => rendered.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());
    expect(text(rendered)).toContain("AI FAIR");
    act(() => rendered.root.findByProps({ "data-forecast-tab": "scripts" }).props.onClick());
    expect(text(rendered)).toContain("比赛剧本");
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
    expect(text(rendered)).toContain("盯盘清单");
  });

  it("uses clamped roving tab selection and moves focus on ArrowRight and ArrowLeft", () => {
    const focus = new Map<string, Array<ReturnType<typeof vi.fn>>>();
    act(() => {
      root = create(createElement(ForecastAnalyticsTabs, { match, poly: poly(), kalshi }), {
        createNodeMock: (element) => {
          if (element.type !== "button") return {};
          const mock = vi.fn();
          const tab = (element.props as { "data-forecast-tab": string })["data-forecast-tab"];
          focus.set(tab, [...(focus.get(tab) ?? []), mock]);
          return { focus: mock };
        },
      });
    });
    const rendered = root!;
    const focusCalls = (tab: string) => focus.get(tab)?.reduce((sum, mock) => sum + mock.mock.calls.length, 0);
    const scores = rendered.root.findByProps({ "data-forecast-tab": "scores" });
    const preventDefault = vi.fn();

    act(() => scores.props.onKeyDown({ key: "ArrowRight", preventDefault }));

    expect(preventDefault).toHaveBeenCalledOnce();
    expect(rendered.root.findByProps({ "data-forecast-tab": "watch" }).props["aria-selected"]).toBe(true);
    expect(rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.tabIndex).toBe(0);
    expect(focusCalls("watch")).toBe(1);
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onKeyDown({ key: "ArrowRight", preventDefault }));
    expect(rendered.root.findByProps({ "data-forecast-tab": "watch" }).props["aria-selected"]).toBe(true);
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onKeyDown({ key: "ArrowLeft", preventDefault }));
    expect(rendered.root.findByProps({ "data-forecast-tab": "scores" }).props["aria-selected"]).toBe(true);
    expect(focusCalls("scores")).toBe(1);
    act(() => rendered.root.findByProps({ "data-forecast-tab": "scores" }).props.onKeyDown({ key: "ArrowLeft", preventDefault }));
    expect(rendered.root.findByProps({ "data-forecast-tab": "scripts" }).props["aria-selected"]).toBe(true);
    expect(focusCalls("scripts")).toBe(1);
    act(() => rendered.root.findByProps({ "data-forecast-tab": "scripts" }).props.onKeyDown({ key: "ArrowLeft", preventDefault }));
    expect(rendered.root.findByProps({ "data-forecast-tab": "value" }).props["aria-selected"]).toBe(true);
    expect(focusCalls("value")).toBe(1);
    act(() => rendered.root.findByProps({ "data-forecast-tab": "value" }).props.onKeyDown({ key: "ArrowLeft", preventDefault }));
    expect(rendered.root.findByProps({ "data-forecast-tab": "value" }).props["aria-selected"]).toBe(true);
  });

  it("labels absent market data as unavailable instead of inventing value", () => {
    const rendered = render({ poly: poly(null) });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());

    expect(text(rendered)).toContain("MARKET UNAVAILABLE");
  });

  it("labels missing xG score modeling unavailable", () => {
    const rendered = render({ match: { ...match, pred: { ...match.pred!, scoreline: { ...match.pred!.scoreline, xg_home: Number.NaN } } } });

    expect(text(rendered)).toContain("SCORE MODEL UNAVAILABLE");
  });

  it("scopes tab IDs per instance and keeps every controlled panel mounted", () => {
    act(() => {
      root = create(createElement("div", null,
        createElement(ForecastAnalyticsTabs, { match, poly: poly(), kalshi }),
        createElement(ForecastAnalyticsTabs, { match, poly: poly(), kalshi }),
      ));
    });
    const sections = root!.root.findAllByProps({ "data-forecast-tabs": true });
    const ids = sections.flatMap((section) => section.findAllByProps({ role: "tab" }).map((tab) => tab.props.id));

    expect(new Set(ids).size).toBe(ids.length);
    for (const section of sections) {
      const panels = section.findAllByProps({ role: "tabpanel" });
      expect(panels).toHaveLength(4);
      for (const tab of section.findAllByProps({ role: "tab" })) {
        expect(panels.some((panel) => panel.props.id === tab.props["aria-controls"])).toBe(true);
      }
    }
  });

  it("honors the supplied most-likely score over a divergent Poisson mode", () => {
    const rendered = render({ poly: poly(null), match: { ...match, pred: { ...match.pred!, scoreline: { ...match.pred!.scoreline, most_likely: "3-3" } } } });

    expect(rendered.root.findByProps({ "data-forecast-score": "3-3" }).props["data-most-likely"]).toBe(true);
    expect(rendered.root.findByProps({ "data-forecast-score": "1-1" }).props["data-most-likely"]).toBeUndefined();
  });

  it("encodes home, draw, and away score cells with semantic side attributes and colors", () => {
    const rendered = render();
    const home = rendered.root.findByProps({ "data-forecast-score": "1-0" });
    const draw = rendered.root.findByProps({ "data-forecast-score": "1-1" });
    const away = rendered.root.findByProps({ "data-forecast-score": "0-1" });

    expect(home.props["data-forecast-score-side"]).toBe("home");
    expect(home.props.className).toContain("bg-emerald");
    expect(draw.props["data-forecast-score-side"]).toBe("draw");
    expect(draw.props.className).toContain("bg-zinc");
    expect(away.props["data-forecast-score-side"]).toBe("away");
    expect(away.props.className).toContain("bg-rose");
  });

  it("marks a supplied 4-0 mode in the aggregate tail without highlighting an unrelated grid cell", () => {
    const rendered = render({ poly: poly(null), match: { ...match, pred: { ...match.pred!, scoreline: { ...match.pred!.scoreline, most_likely: "4-0", top_scores: [{ score: "4-0", p: .04 }] } } } });

    expect(rendered.root.findByProps({ "data-forecast-score-tail": true }).props["data-most-likely"]).toBe("4-0");
    expect(rendered.root.findByProps({ "data-forecast-score": "1-1" }).props["data-most-likely"]).toBeUndefined();
    expect(text(rendered)).toContain("4-0");
  });

  it("conditions the score distribution on de-vigged market prices by default", () => {
    const rendered = render();

    expect(rendered.root.findAllByProps({ "data-forecast-score-source": "market" }).length).toBe(2);
    // per-side mass of the conditioned grid == de-vigged 1X2 (.42/.29/.29 sums to 1)
    const scriptMass = (side: string) =>
      rendered.root.findByProps({ "data-forecast-script": side }).findByType("strong").children.join("");
    expect(scriptMass("home")).toBe("42.0%");
    expect(scriptMass("draw")).toBe("29.0%");
    expect(scriptMass("away")).toBe("29.0%");
  });

  it("switches back to the AI grid via the source toggle and restores the supplied mode", () => {
    const rendered = render();

    act(() => rendered.root.findAllByProps({ "data-forecast-source-btn": "ai" })[0].props.onClick());

    expect(rendered.root.findAllByProps({ "data-forecast-score-source": "ai" }).length).toBe(2);
    expect(rendered.root.findByProps({ "data-forecast-score": "1-1" }).props["data-most-likely"]).toBe(true);
  });

  it("falls back to the AI grid and disables the market toggle without market data", () => {
    const rendered = render({ poly: poly(null) });

    expect(rendered.root.findAllByProps({ "data-forecast-score-source": "ai" }).length).toBe(2);
    expect(rendered.root.findAllByProps({ "data-forecast-source-btn": "market" })[0].props.disabled).toBe(true);
  });

  it("shows market decimal odds and direction, while null market fields degrade", () => {
    const rendered = render();
    act(() => rendered.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());
    expect(text(rendered)).toContain("PM Odds");
    expect(text(rendered)).toContain("Direction");
    expect(text(rendered)).toContain("2.38");
    expect(text(rendered)).toContain("BUY");

    const unavailable = render({ poly: poly(null) });
    act(() => unavailable.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());
    expect(text(unavailable)).toContain("MARKET UNAVAILABLE");
    expect(text(unavailable)).not.toContain("BUY");
    expect(text(unavailable)).not.toContain("SELL");
  });

  it("rejects malformed AI probabilities instead of calculating impossible fair odds", () => {
    const rendered = render({ match: { ...match, pred: { ...match.pred!, p_home: 1.1, p_draw: .2, p_away: .2 } } });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());

    expect(text(rendered)).toContain("AI MODEL UNAVAILABLE");
    expect(text(rendered)).not.toContain("AI FAIR");

    const unnormalized = render({ match: { ...match, pred: { ...match.pred!, p_home: .6, p_draw: .4, p_away: .4 } } });
    act(() => unnormalized.root.findByProps({ "data-forecast-tab": "value" }).props.onClick());
    expect(text(unnormalized)).toContain("AI MODEL UNAVAILABLE");
  });

  it("rejects non-finite weather rather than displaying a fabricated reading", () => {
    const rendered = render({ weather: { temp_c: Number.NaN, humidity_pct: Number.POSITIVE_INFINITY, apparent_c: 22, hot: false, forecast: false, exp_delta_pp: 0 } });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());

    expect(text(rendered)).toContain("WEATHER UNAVAILABLE");
  });

  it("updates a fresh quote timestamp to stale and clears the watch clock on unmount", () => {
    vi.useFakeTimers();
    const now = Date.parse("2026-07-10T18:00:00Z");
    vi.setSystemTime(now);
    const rendered = render({ poly: { ...poly(), updatedAt: null, matches: { [kickoffEpoch(match.kickoff_utc)]: { home: .42, draw: .29, away: .29, src: "ws", ts: now } } } });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
    expect(text(rendered)).toContain("PM WS · FRESH");
    expect(vi.getTimerCount()).toBe(1);

    act(() => { vi.advanceTimersByTime(16_000); });
    expect(text(rendered)).toContain("PM WS · STALE");
    act(() => rendered.unmount());
    root = null;
    expect(vi.getTimerCount()).toBe(0);
  });

  it("labels each match quote by its own source and reports global socket state separately", () => {
    vi.useFakeTimers();
    const now = Date.parse("2026-07-10T18:00:00Z");
    vi.setSystemTime(now);
    const gamma = render({ poly: { ...poly(), wsConnected: true, matches: { [kickoffEpoch(match.kickoff_utc)]: { home: .42, draw: .29, away: .29, src: "gamma", ts: now } } } });
    act(() => gamma.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
    expect(text(gamma)).toContain("PM REST/GAMMA · FRESH");
    expect(text(gamma)).toContain("SOCKET UP");
    expect(text(gamma)).not.toContain("PM WS · FRESH");

    const ws = render({ poly: { ...poly(), wsConnected: false, matches: { [kickoffEpoch(match.kickoff_utc)]: { home: .42, draw: .29, away: .29, src: "ws", ts: now } } } });
    act(() => ws.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
    expect(text(ws)).toContain("PM WS · FRESH");
    expect(text(ws)).toContain("SOCKET DOWN");

    const unknown = render({ poly: { ...poly(), matches: { [kickoffEpoch(match.kickoff_utc)]: { home: .42, draw: .29, away: .29, ts: now } } } });
    act(() => unknown.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
    expect(text(unknown)).toContain("PM SOURCE UNKNOWN · FRESH");
  });

  it("tiers AI versus normalized PM divergence and suppresses alerts without a market", () => {
    const alert = (prices: { home: number; draw: number; away: number } | null) => {
      const rendered = render({ poly: poly(prices) });
      act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());
      return rendered.root.findAll((node) => node.props["data-forecast-divergence-alert"] != null);
    };

    expect(alert({ home: .42, draw: .29, away: .29 })[0].props["data-forecast-divergence-alert"]).toBe("normal");
    expect(alert({ home: .40, draw: .25, away: .35 })[0].props["data-forecast-divergence-alert"]).toBe("warning");
    expect(alert({ home: .30, draw: .25, away: .45 })[0].props["data-forecast-divergence-alert"]).toBe("critical");
    expect(alert(null)).toHaveLength(0);
  });

  it("marks an old quote timestamp stale", () => {
    vi.useFakeTimers();
    const now = Date.parse("2026-07-10T18:00:00Z");
    vi.setSystemTime(now);
    const rendered = render({ poly: { ...poly(), matches: { [kickoffEpoch(match.kickoff_utc)]: { home: .42, draw: .29, away: .29, src: "ws", ts: now - 15_001 } } } });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());

    expect(text(rendered)).toContain("PM WS · STALE");
  });

  it("uses quote timestamps ahead of the global Polymarket timestamp", () => {
    vi.useFakeTimers();
    const now = Date.parse("2026-07-10T18:00:00Z");
    vi.setSystemTime(now);
    const rendered = render({ poly: { ...poly(), updatedAt: now, matches: { [kickoffEpoch(match.kickoff_utc)]: { home: .42, draw: .29, away: .29, src: "ws", ts: now - 15_001 } } } });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());

    expect(text(rendered)).toContain("PM WS · STALE");
  });

  it("never renders retired console filler in any analytics panel", () => {
    const rendered = render();
    for (const tab of ["value", "scripts", "scores", "watch"] as const) {
      act(() => rendered.root.findByProps({ "data-forecast-tab": tab }).props.onClick());
      expect(text(rendered)).not.toContain("MODEL MATRIX · 模型矩阵");
      expect(text(rendered)).not.toContain("MATCH DOSSIER · 近期态势");
    }
  });
});

describe("conditionDistribution", () => {
  it("rescales each outcome region to the target probs and keeps within-side scoreline ratios", () => {
    const base = buildScoreDistribution(1.42, 1.08)!;
    const probs = { home: .5, draw: .2, away: .3 } as const;
    const conditioned = conditionDistribution(base, probs)!;

    for (const side of ["home", "draw", "away"] as const) {
      const mass = conditioned.cells.filter((cell) => cell.side === side).reduce((sum, cell) => sum + cell.p, 0)
        + conditioned.tailBySide[side];
      expect(mass).toBeCloseTo(probs[side], 10);
    }
    const ratio = (cells: typeof base.cells) =>
      cells.find((cell) => cell.label === "1-0")!.p / cells.find((cell) => cell.label === "2-1")!.p;
    expect(ratio(conditioned.cells)).toBeCloseTo(ratio(base.cells), 10);
  });

  it("rejects degenerate probabilities", () => {
    const base = buildScoreDistribution(1.42, 1.08)!;
    expect(conditionDistribution(base, { home: 1, draw: 0, away: 0 })).toBeNull();
    expect(conditionDistribution(base, { home: Number.NaN, draw: .5, away: .5 })).toBeNull();
  });
});
