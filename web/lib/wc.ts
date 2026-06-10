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

const FLAG: Record<string, string> = {
  Mexico: "🇲🇽", "South Korea": "🇰🇷", "Czech Republic": "🇨🇿", "South Africa": "🇿🇦",
  "United States": "🇺🇸", Turkey: "🇹🇷", Australia: "🇦🇺", Paraguay: "🇵🇾",
  Canada: "🇨🇦", Switzerland: "🇨🇭", "Bosnia and Herzegovina": "🇧🇦", Qatar: "🇶🇦",
  Brazil: "🇧🇷", Morocco: "🇲🇦", Scotland: "🏴󠁧󠁢󠁳󠁣󠁴󠁿", Haiti: "🇭🇹",
  Germany: "🇩🇪", "Ivory Coast": "🇨🇮", Ecuador: "🇪🇨", "Curaçao": "🇨🇼",
  Netherlands: "🇳🇱", Japan: "🇯🇵", Sweden: "🇸🇪", Tunisia: "🇹🇳",
  Belgium: "🇧🇪", Iran: "🇮🇷", Egypt: "🇪🇬", "New Zealand": "🇳🇿",
  Spain: "🇪🇸", Uruguay: "🇺🇾", "Saudi Arabia": "🇸🇦", "Cape Verde": "🇨🇻",
  Argentina: "🇦🇷", Algeria: "🇩🇿", Austria: "🇦🇹", Jordan: "🇯🇴",
  France: "🇫🇷", Senegal: "🇸🇳", Iraq: "🇮🇶", Norway: "🇳🇴",
  Portugal: "🇵🇹", Colombia: "🇨🇴", Uzbekistan: "🇺🇿", "DR Congo": "🇨🇩",
  England: "🏴󠁧󠁢󠁥󠁮󠁧󠁿", Croatia: "🇭🇷", Ghana: "🇬🇭", Panama: "🇵🇦",
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

export const flag = (name: string) => FLAG[name] ?? "•";

export const pct = (p: number, digits = 0) => `${(p * 100).toFixed(digits)}%`;

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
