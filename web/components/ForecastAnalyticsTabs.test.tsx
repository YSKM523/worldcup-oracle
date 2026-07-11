import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    const rendered = render({ match: { ...match, pred: { ...match.pred!, scoreline: { ...match.pred!.scoreline, most_likely: "3-3" } } } });

    expect(rendered.root.findByProps({ "data-forecast-score": "3-3" }).props["data-most-likely"]).toBe(true);
    expect(rendered.root.findByProps({ "data-forecast-score": "1-1" }).props["data-most-likely"]).toBeUndefined();
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

  it("rejects non-finite weather rather than displaying a fabricated reading", () => {
    const rendered = render({ weather: { temp_c: Number.NaN, humidity_pct: Number.POSITIVE_INFINITY, apparent_c: 22, hot: false, forecast: false, exp_delta_pp: 0 } });
    act(() => rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.onClick());

    expect(text(rendered)).toContain("WEATHER UNAVAILABLE");
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
