import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FocusCard } from "./MatchCards";
import { LiveStats } from "./LiveStats";

vi.mock("../lib/useMatchStats", () => ({
  useMatchStats: () => ({
    state: "in",
    detail: "61'",
    home: { possessionPct: 65, totalShots: 11 },
    away: { possessionPct: 35, totalShots: 3 },
  }),
}));

const findSurface = (root: ReactTestRenderer, surface: string) =>
  root.root.find((node) => node.props["data-console-surface"] === surface);

describe("match console surfaces", () => {
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

  it("renders LIVE STATS as a flat rail surface in console mode", () => {
    act(() => {
      root = create(React.createElement(LiveStats as React.ComponentType<Record<string, unknown>>, {
        espnId: "401", home: "Spain", away: "Belgium", live: true, variant: "console",
      }));
    });
    const surface = findSurface(root!, "stats");
    expect(surface.props.className).toContain("rounded-none");
    expect(surface.props.className).toContain("border-0");
    expect(surface.props.className).toContain("h-full");
    expect(surface.props.className).toContain("flex-col");
    expect(JSON.stringify(root!.toJSON())).toContain("LIVE STATS · 实时数据");
  });

  it("renders prediction as a flat terminal surface with its own console header", () => {
    act(() => {
      root = create(React.createElement(FocusCard as React.ComponentType<Record<string, unknown>>, {
        m: {
          espn_id: "401", kickoff_utc: "2026-07-10T19:00:00Z", stage: "quarterfinal", group: null,
          venue: "SoFi Stadium", city: "Inglewood, California", home: "Spain", away: "Belgium",
          tbd: false, completed: false, status: "in", home_score: 1, away_score: 1, winner: null,
          detail: {
            elo_home: 2386, elo_away: 2201, rank_home: 1, rank_away: 6,
            form_home: [{ date: "2026-07-01", opp: "France", score: "2-0", res: "W" }],
            form_away: [{ date: "2026-07-01", opp: "Germany", score: "1-1", res: "D" }],
            h2h: { n: 8, w: 7, d: 1, l: 0, last: [] },
            advance_home: .7, advance_away: .3, champion_home: .214, champion_away: .047,
            analysis: "Spain control the matchup.",
          },
        },
        meta: { models: [] }, live: {}, poly: { matches: {}, champion: {}, championFresh: false, updatedAt: null, wsConnected: false },
        hideBook: true, variant: "console",
      }));
    });
    const surface = findSurface(root!, "prediction");
    expect(surface.props.className).toContain("rounded-none");
    expect(surface.props.className).toContain("border-0");
    expect(surface.props.className).toContain("h-full");
    expect(surface.props.className).toContain("flex-col");
    expect(JSON.stringify(root!.toJSON())).toContain("MATCH FORECAST · 模型预测");
    expect(JSON.stringify(root!.toJSON())).toContain("MATCH DOSSIER · 近期态势");
    expect(JSON.stringify(root!.toJSON())).toContain("法国");
    expect(JSON.stringify(root!.toJSON())).toContain("德国");
  });
});
