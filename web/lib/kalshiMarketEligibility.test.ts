import { describe, expect, it } from "vitest";
import { shouldEnableKalshiMarket } from "./kalshiMarketEligibility";

describe("shouldEnableKalshiMarket", () => {
  it("disables polling for TBD fixtures even when placeholder teams are present", () => {
    expect(shouldEnableKalshiMarket({ home: "Winner QF1", away: "Winner QF2", tbd: true })).toBe(false);
  });

  it("enables a confirmed fixture with teams independently of a Polymarket slug", () => {
    expect(shouldEnableKalshiMarket({ home: "Spain", away: "Belgium", tbd: false })).toBe(true);
  });
});
