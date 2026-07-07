export interface InplayParams {
  pHome: number;
  pDraw: number;
  pAway: number;
  xgHome: number;
  xgAway: number;
  homeScore: number;
  awayScore: number;
  minute: number;
  totalMinutes?: 90 | 120;
}

export interface InplayProbs {
  home: number;
  draw: number;
  away: number;
}

const CAP = 10;
const EPS = 1e-12;

function finiteNonNegative(n: number): number {
  return Number.isFinite(n) ? Math.max(0, n) : 0;
}

function clampProb(p: number): number {
  if (!Number.isFinite(p)) return EPS;
  return Math.min(1 - EPS, Math.max(EPS, p));
}

function normalize(p: InplayProbs): InplayProbs {
  const home = finiteNonNegative(p.home);
  const draw = finiteNonNegative(p.draw);
  const away = finiteNonNegative(p.away);
  const total = home + draw + away;
  if (total <= 0) return { home: 1 / 3, draw: 1 / 3, away: 1 / 3 };
  return { home: home / total, draw: draw / total, away: away / total };
}

function logit(p: number): number {
  const q = clampProb(p);
  return Math.log(q / (1 - q));
}

function sigmoid(x: number): number {
  if (x >= 0) {
    const z = Math.exp(-x);
    return 1 / (1 + z);
  }
  const z = Math.exp(x);
  return z / (1 + z);
}

function poisson(lambda: number, cap: number): number[] {
  const p = new Array<number>(cap + 1);
  p[0] = Math.exp(-finiteNonNegative(lambda));
  for (let k = 1; k <= cap; k++) p[k] = (p[k - 1] * lambda) / k;
  return p;
}

function rawDoublePoisson({
  xgHome,
  xgAway,
  homeScore,
  awayScore,
  minute,
  totalMinutes = 90,
}: Omit<InplayParams, "pHome" | "pDraw" | "pAway">): InplayProbs {
  const elapsed = Math.min(totalMinutes, Math.max(0, Number.isFinite(minute) ? minute : 0));
  const remaining = Math.max(0, totalMinutes - elapsed);
  const lambdaHome = finiteNonNegative(xgHome) * (remaining / 90);
  const lambdaAway = finiteNonNegative(xgAway) * (remaining / 90);
  const homeGoals = poisson(lambdaHome, CAP);
  const awayGoals = poisson(lambdaAway, CAP);

  let home = 0;
  let draw = 0;
  let away = 0;
  for (let h = 0; h <= CAP; h++) {
    for (let a = 0; a <= CAP; a++) {
      const mass = homeGoals[h] * awayGoals[a];
      const finalHome = homeScore + h;
      const finalAway = awayScore + a;
      if (finalHome > finalAway) home += mass;
      else if (finalHome === finalAway) draw += mass;
      else away += mass;
    }
  }

  return normalize({ home, draw, away });
}

export function inplayProbs(params: InplayParams): InplayProbs {
  const totalMinutes = params.totalMinutes ?? 90;
  const prior = normalize({ home: params.pHome, draw: params.pDraw, away: params.pAway });
  const baseline = rawDoublePoisson({
    xgHome: params.xgHome,
    xgAway: params.xgAway,
    homeScore: 0,
    awayScore: 0,
    minute: 0,
    totalMinutes,
  });
  const current = rawDoublePoisson({ ...params, totalMinutes });

  /*
   * The xG-only double-Poisson baseline is not the calibrated pre-match model.
   * We therefore learn one binary log-odds offset per W/D/L outcome at kickoff:
   *   logit(calibrated_prior) - logit(raw_xg_baseline)
   * and apply those same offsets to every later raw in-play outcome before
   * renormalizing. At 0-0, t=0 this maps back to the supplied prior exactly.
   */
  const home = sigmoid(logit(current.home) + logit(prior.home) - logit(baseline.home));
  const draw = sigmoid(logit(current.draw) + logit(prior.draw) - logit(baseline.draw));
  const away = sigmoid(logit(current.away) + logit(prior.away) - logit(baseline.away));

  return normalize({ home, draw, away });
}

export function parseClock(clock: string): number | null {
  const s = clock.trim().toUpperCase();
  if (s === "HT") return 45;
  if (s === "FT") return 90;
  const m = /^(\d{1,3})['\u2019](?:\+\d+)?$/.exec(s);
  if (!m) return null;
  return Number(m[1]);
}
