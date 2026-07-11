import { createElement } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, describe, expect, it, vi } from "vitest";
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

  afterEach(() => {
    if (root) act(() => root?.unmount());
    root = null;
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

  it("uses roving tab selection without wrapping on ArrowRight", () => {
    const rendered = render();
    const scores = rendered.root.findByProps({ "data-forecast-tab": "scores" });
    const preventDefault = vi.fn();

    act(() => scores.props.onKeyDown({ key: "ArrowRight", preventDefault }));

    expect(preventDefault).toHaveBeenCalledOnce();
    expect(rendered.root.findByProps({ "data-forecast-tab": "watch" }).props["aria-selected"]).toBe(true);
    expect(rendered.root.findByProps({ "data-forecast-tab": "watch" }).props.tabIndex).toBe(0);
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
});
