export interface ScoreEntry {
  score: string;
  p: number;
}

export interface Scoreline {
  top_scores: ScoreEntry[];
  most_likely: string;
  most_likely_p: number;
  xg_home: number;
  xg_away: number;
  p_over25: number;
  p_btts: number;
}

export interface PerModel {
  p_home: number;
  p_draw: number;
  p_away: number;
  p_adv_home?: number;
}

export interface Pred {
  p_home: number;
  p_draw: number;
  p_away: number;
  p_adv_home?: number;
  p_adv_away?: number;
  scoreline: Scoreline;
  per_model: PerModel[];
  elo_home: number;
  elo_away: number;
}

export interface Locked {
  p_home: number;
  p_draw: number;
  p_away: number;
  pred_score: string | null;
  brier: number | null;
}

export interface FormEntry {
  date: string;
  opp: string;
  score: string;
  res: "W" | "D" | "L";
}

export interface H2H {
  n: number;
  w: number;
  d: number;
  l: number;
  last: { date: string; score: string; tournament: string }[];
}

export interface Detail {
  elo_home: number;
  elo_away: number;
  rank_home: number;
  rank_away: number;
  form_home: FormEntry[];
  form_away: FormEntry[];
  h2h: H2H;
  advance_home: number;
  advance_away: number;
  champion_home: number;
  champion_away: number;
  analysis: string;
}

/** Raw Polymarket per-match W/D/L prices (vig included) + event slug. */
export interface MatchMarket {
  slug: string;
  home: number;
  draw: number;
  away: number;
  volume: number;
}

export interface Match {
  espn_id: string;
  kickoff_utc: string;
  stage: string;
  group: string | null;
  venue: string | null;
  city: string | null;
  home: string;
  away: string;
  tbd: boolean;
  completed: boolean;
  status: string | null;
  home_score: number | null;
  away_score: number | null;
  winner: string | null;
  pred?: Pred;
  locked?: Locked;
  detail?: Detail;
  market?: MatchMarket;
  edge?: MatchEdge[];
}

export interface GroupRow {
  team: string;
  played: number;
  w: number;
  d: number;
  l: number;
  gf: number;
  ga: number;
  gd: number;
  pts: number;
  p_advance: number;
}

export interface Edge {
  edge_pct: number;
  direction: "BUY" | "SELL";
  strength: string;
  models_agree: number;
  half_kelly: number;
}

export interface MatchEdge {
  side: "home" | "draw" | "away";
  edge_pct: number;
  direction: "BUY" | "SELL";
  half_kelly: number;
  models_agree: number;
  strength: string;
}

export interface Champion {
  team: string;
  ai: number;
  market: number;
  market_raw: number;
  edge: Edge | null;
  per_model: Record<string, number>;
  stages: {
    advance: number;
    r16: number;
    qf: number;
    sf: number;
    final: number;
    champion: number;
  };
}

export interface PerfDetail {
  kickoff_utc: string;
  stage: string;
  home: string;
  away: string;
  score: string;
  pred_score: string | null;
  p_home: number;
  p_draw: number;
  p_away: number;
  brier: number | null;
  winner_hit: boolean;
  score_hit: boolean | null;
}

export interface Performance {
  n_scored: number;
  mean_brier: number | null;
  winner_hit_rate: number | null;
  score_hits: number;
  n_score_preds: number;
  details: PerfDetail[];
  scoreboard: {
    n_pairs: number;
    n_teams: number;
    ai_brier: number;
    pm_brier: number;
    leader: string;
  } | null;
}

export interface CalibrationMeta {
  T: number;
  delta: number;
  n_wc: number;
  draw_rate_observed: number | null;
  draw_rate_predicted_raw: number | null;
}

export interface Meta {
  generated_at: string;
  models: string[];
  snapshot_as_of: string | null;
  sim_date: string | null;
  matchday: string | null;
  n_matches: number;
  n_completed: number;
  odds_time?: string;
  volume?: number;
  calibration?: CalibrationMeta | null;
  match_edge?: {
    ai_brier: number | null;
    pm_brier: number | null;
    n_scored: number;
    edge_hit_rate: number | null;
    n_no_market?: number;
  } | null;
}

export interface Data {
  meta: Meta;
  matches: Match[];
  groups: Record<string, GroupRow[]>;
  champions: Champion[];
  performance: Performance;
}

/* ── 天气研究 (research/weather_effect → weather.json) ─────────── */

export interface MatchWeather {
  temp_c: number;
  humidity_pct: number;
  apparent_c: number;
  hot: boolean;
  forecast: boolean;
  /** 实验性 favorite 概率修正 (pp, 负=酷热削 favorite)。不计入官方预测。 */
  exp_delta_pp: number;
}

export interface WeatherCorr {
  rho?: number;
  r?: number;
  p: number;
  n: number;
}

export interface WeatherAdjust {
  slope_pp_per_degC: number;
  t_stat: number;
  shrink_factor: number;
  slope_shrunk_pp_per_degC: number;
  ref_temp_c: number;
  cap_pp: number;
  n: number;
  note: string;
}

export interface WeatherStudy {
  n_matches: number;
  n_physical: number;
  dist_vs_apparent: WeatherCorr;
  dist_vs_temp: WeatherCorr;
  sprint_vs_temp: WeatherCorr;
  slope_km_per_degC: number;
  dist_buckets: Record<string, { n: number; mean_temp: number; mean_dist_km: number }>;
  altitude_partial: WeatherCorr;
  altitude_excl_high: WeatherCorr & { excluded_cities?: string[] };
  upset_partial: WeatherCorr;
  upset_buckets: Record<string, { n: number; upset_rate: number; ci: number[] }>;
  goals_vs_temp: WeatherCorr;
  h2_share_vs_temp: { stat: number; p: number; n: number };
  calib_buckets: Record<string, { n: number; mean_brier: number; mean_calib_resid: number }>;
}

export interface WeatherData {
  generated_at: string;
  study: WeatherStudy;
  adjust: WeatherAdjust;
  matches: Record<string, MatchWeather>;
}

export interface LiveEntry {
  state: "pre" | "in" | "post";
  completed: boolean;
  home_score: number;
  away_score: number;
  clock: string;
}

export type LiveMap = Record<string, LiveEntry>;

/** Live Polymarket odds, polled client-side; raw prices (vig included). */
export interface PolyMatchOdds {
  home: number;
  draw: number;
  away: number;
  /** "ws" = CLOB WebSocket 逐笔中间价; "gamma" = 5 分钟 CDN 轮询last价 */
  src?: "ws" | "gamma";
  /** epoch ms of the last update for this match */
  ts?: number;
  /** 三腿累计成交量 USD（YES+NO 双边，gamma 轮询取得；量大≠更可能，反映热度/分歧） */
  vol?: { home: number; draw: number; away: number };
}
export interface PolyLive {
  champion: Record<string, number>; // team → raw Yes price
  matches: Record<string, PolyMatchOdds>; // kickoff epoch (s) → W/D/L prices
  championFresh: boolean;
  updatedAt: number | null; // epoch ms of last successful poll
  /** CLOB WebSocket 当前是否在线（实时推送生效中） */
  wsConnected: boolean;
}

export type MarketSide = "home" | "draw" | "away";
export interface KalshiOutcomeQuote { ticker: string; bid: number | null; ask: number | null; mid: number | null; last: number | null; volume: number | null; }
export interface KalshiQuoteResponse { status: "live" | "unavailable" | "error"; source: "kalshi-rest"; eventTicker: string | null; updatedAt: number; outcomes: Partial<Record<MarketSide, KalshiOutcomeQuote>>; reason?: string; }
export interface KalshiMarketState extends KalshiQuoteResponse { stale: boolean; failures: number; }
