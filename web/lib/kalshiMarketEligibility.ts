export function shouldEnableKalshiMarket(fixture: { home: string; away: string; tbd: boolean }): boolean {
  return !fixture.tbd && fixture.home.trim().length > 0 && fixture.away.trim().length > 0;
}
