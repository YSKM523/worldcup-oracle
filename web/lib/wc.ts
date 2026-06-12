const ZH: Record<string, string> = {
  Mexico: "墨西哥", "South Korea": "韩国", "Czech Republic": "捷克", "South Africa": "南非",
  "United States": "美国", Turkey: "土耳其", Australia: "澳大利亚", Paraguay: "巴拉圭",
  Canada: "加拿大", Switzerland: "瑞士", "Bosnia and Herzegovina": "波黑", Qatar: "卡塔尔",
  Brazil: "巴西", Morocco: "摩洛哥", Scotland: "苏格兰", Haiti: "海地",
  Germany: "德国", "Ivory Coast": "科特迪瓦", Ecuador: "厄瓜多尔", "Curaçao": "库拉索",
  Netherlands: "荷兰", Japan: "日本", Sweden: "瑞典", Tunisia: "突尼斯",
  Belgium: "比利时", Iran: "伊朗", Egypt: "埃及", "New Zealand": "新西兰",
  Spain: "西班牙", Uruguay: "乌拉圭", "Saudi Arabia": "沙特阿拉伯", "Cape Verde": "佛得角",
  Argentina: "阿根廷", Algeria: "阿尔及利亚", Austria: "奥地利", Jordan: "约旦",
  France: "法国", Senegal: "塞内加尔", Iraq: "伊拉克", Norway: "挪威",
  Portugal: "葡萄牙", Colombia: "哥伦比亚", Uzbekistan: "乌兹别克斯坦", "DR Congo": "刚果(金)",
  England: "英格兰", Croatia: "克罗地亚", Ghana: "加纳", Panama: "巴拿马",
};

// ISO codes → self-hosted SVG flags in public/flags/ (flag emoji don't render
// on Windows; SVGs are crisp and cross-platform). Scotland/England use the
// FIFA sub-national codes that flagcdn ships.
const ISO: Record<string, string> = {
  Mexico: "mx", "South Korea": "kr", "Czech Republic": "cz", "South Africa": "za",
  "United States": "us", Turkey: "tr", Australia: "au", Paraguay: "py",
  Canada: "ca", Switzerland: "ch", "Bosnia and Herzegovina": "ba", Qatar: "qa",
  Brazil: "br", Morocco: "ma", Scotland: "gb-sct", Haiti: "ht",
  Germany: "de", "Ivory Coast": "ci", Ecuador: "ec", "Curaçao": "cw",
  Netherlands: "nl", Japan: "jp", Sweden: "se", Tunisia: "tn",
  Belgium: "be", Iran: "ir", Egypt: "eg", "New Zealand": "nz",
  Spain: "es", Uruguay: "uy", "Saudi Arabia": "sa", "Cape Verde": "cv",
  Argentina: "ar", Algeria: "dz", Austria: "at", Jordan: "jo",
  France: "fr", Senegal: "sn", Iraq: "iq", Norway: "no",
  Portugal: "pt", Colombia: "co", Uzbekistan: "uz", "DR Congo": "cd",
  England: "gb-eng", Croatia: "hr", Ghana: "gh", Panama: "pa",
};

export const STAGE_ZH: Record<string, string> = {
  group: "小组赛", r32: "32 强", r16: "16 强", qf: "1/4 决赛",
  sf: "半决赛", third: "季军赛", final: "决赛",
};

export const KO_STAGES = new Set(["r32", "r16", "qf", "sf", "third", "final"]);

export const MODEL_SHORT: Record<string, string> = {
  "Chronos-2": "Chronos",
  "TimesFM-2.5": "TimesFM",
  FlowState: "FlowState",
  "Actual-Elo": "Elo",
};

const PLACEHOLDERS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^Group ([A-L]) Winner$/, (m) => `${m[1]} 组第一`],
  [/^Group ([A-L]) 2nd Place$/, (m) => `${m[1]} 组第二`],
  [/^Third Place Group (.+)$/, (m) => `小组第三 (${m[1]})`],
  [/^Round of 32 (\d+) Winner$/, (m) => `32 强第 ${m[1]} 场胜者`],
  [/^Round of 16 (\d+) Winner$/, (m) => `16 强第 ${m[1]} 场胜者`],
  [/^Quarterfinal (\d+) Winner$/, (m) => `1/4 决赛第 ${m[1]} 场胜者`],
  [/^Semifinal (\d+) Winner$/, (m) => `半决赛第 ${m[1]} 场胜者`],
  [/^Semifinal (\d+) Loser$/, (m) => `半决赛第 ${m[1]} 场负者`],
];

export function zh(name: string): string {
  if (ZH[name]) return ZH[name];
  for (const [re, fn] of PLACEHOLDERS) {
    const m = name.match(re);
    if (m) return fn(m);
  }
  return name;
}

/** ISO code for a team, or null for TBD placeholders (e.g. "Group A Winner"). */
export const iso = (name: string): string | null => ISO[name] ?? null;

export const pct = (p: number, digits = 0) => `${(p * 100).toFixed(digits)}%`;

/** Decimal odds = 1 / probability (raw price, vig included). null if invalid. */
export const decimalOdds = (p: number | null | undefined): number | null =>
  p && p > 0 && p < 1 ? 1 / p : null;

/** Format decimal odds like "5.90"; em-dash when unavailable. */
export const oddsFmt = (p: number | null | undefined): string => {
  const o = decimalOdds(p);
  return o == null ? "—" : o.toFixed(2);
};

/** Kickoff ISO ('…Z' or '…+00:00') → epoch-second string, for odds matching. */
export const kickoffEpoch = (iso: string): string =>
  String(Math.floor(new Date(iso).getTime() / 1000));

// Polymarket display names → our canonical team names (for live champion odds).
const PM_TO_CANONICAL: Record<string, string> = {
  USA: "United States",
  US: "United States",
  "Korea Republic": "South Korea",
  Czechia: "Czech Republic",
  Turkiye: "Turkey",
  Türkiye: "Turkey",
  "Cote d'Ivoire": "Ivory Coast",
  "Côte d'Ivoire": "Ivory Coast",
  "Cabo Verde": "Cape Verde",
  Curacao: "Curaçao",
  Bosnia: "Bosnia and Herzegovina",
  "Bosnia-Herzegovina": "Bosnia and Herzegovina",
  "Dem. Rep. Congo": "DR Congo",
  "Congo DR": "DR Congo",
};

export const canonicalTeam = (pmName: string): string =>
  PM_TO_CANONICAL[pmName] ?? pmName;

/** Recompute the AI-vs-market edge from a live de-vigged market probability.
 *  Mirrors the pipeline (edge ≥2pp shown; STRONG ≥5pp with ≥3 models agreeing).
 *  models_agree comes from the daily snapshot — it can't be derived live. */
export function liveEdge(ai: number, marketDevig: number, modelsAgree: number) {
  const edgePct = Math.round((ai - marketDevig) * 100 * 100) / 100;
  if (Math.abs(edgePct) < 2) return null;
  return {
    edge_pct: edgePct,
    direction: edgePct >= 0 ? ("BUY" as const) : ("SELL" as const),
    strength: Math.abs(edgePct) >= 5 && modelsAgree >= 3 ? "STRONG EDGE" : "edge",
    models_agree: modelsAgree,
  };
}

export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });

export function localDateKey(iso: string): string {
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

export function fmtDay(key: string): string {
  const [y, mo, da] = key.split("-").map(Number);
  const wd = "日一二三四五六"[new Date(y, mo - 1, da).getDay()];
  return `${mo} 月 ${da} 日 · 周${wd}`;
}

export const todayKey = () => localDateKey(new Date().toISOString());

/** Venue-local matchday (UTC − 6h), matching the pipeline's grouping. */
export const venueDayKey = (iso: string) =>
  new Date(new Date(iso).getTime() - 6 * 3600e3).toISOString().slice(0, 10);
