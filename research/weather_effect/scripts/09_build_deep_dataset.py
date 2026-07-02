"""
09_build_deep_dataset.py — v2 深挖数据集: 在 matches_weather.csv 基础上补五类数据。

  A. 扩展天气 (Open-Meteo): 湿球温度/太阳辐射/风速/云量/降水, 开球时刻 + 比赛 2h 窗口均值
  B. 球场环境: 封闭空调馆(达拉斯/休斯顿/亚特兰大) vs 顶棚(SoFi/温哥华) vs 露天
     —— 空调馆里"场外气温"不代表场上体感, 是角度⑥的隐藏测量误差
  C. 赛程疲劳控制: 赛会第几天 / 各队第几场 / 双方休息天数(取较小值)
  D. ESPN summary: 上座人数 / 技术统计(传球/控球/犯规/牌) / 换人时间 / 比赛中断(降温暂停代理)
  E. PMSR page-2 全量队级: xG/传球/line breaks/压迫/二点球/最终三区接球 + 距离/Zone4 (重解析)

输出: out/matches_deep.csv, out/pmsr_team_stats.csv
PDF 保留在 scratchpad/fifa_pdf_keep/ 供后续球员级 OCR 试验。
前置: 先跑 01(刷新 matches_weather.csv 到最新完赛场次)。
"""
import json, re, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import pandas as pd
import requests
import pdfplumber

ROOT = Path("/home/ubuntu/worldcup-oracle")
RW = ROOT / "research/weather_effect"
SC = Path("/tmp/claude-1000/-home-ubuntu/425320c7-7790-479f-a972-88a803318312/scratchpad/fifa_pdf_keep")
SC.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}

mw = pd.read_csv(RW / "out/matches_weather.csv")
mw["espn_id"] = mw.espn_id.astype(str)
mw["kickoff_utc"] = pd.to_datetime(mw.kickoff_utc, utc=True)
print(f"base: {len(mw)} completed matches")

# ── B. 球场环境(2026 届静态知识) ────────────────────────────────────────
VENUE_ENV = {  # venue_city -> indoor_ac(封闭+空调) / roof_canopy(有顶/可闭顶,无强空调) / open
    "Arlington, Texas": "indoor_ac",        # AT&T Stadium, 可闭顶+空调
    "Houston, Texas": "indoor_ac",          # NRG Stadium, 可闭顶+空调
    "Atlanta, Georgia": "indoor_ac",        # Mercedes-Benz, 可闭顶+空调
    "Vancouver": "roof_canopy",             # BC Place, 可闭顶
    "Inglewood, California": "roof_canopy", # SoFi, 固定顶棚+敞开侧面(遮阳无空调)
}
mw["venue_env"] = mw.venue_city.map(VENUE_ENV).fillna("open")
mw["open_air"] = (mw.venue_env == "open").astype(int)

# ── C. 赛程疲劳控制 ────────────────────────────────────────────────────
t0 = mw.kickoff_utc.min().normalize()
mw["tournament_day"] = (mw.kickoff_utc - t0).dt.total_seconds() / 86400
# 各队出场序号与休息天数
team_games: dict[str, list] = {}
for _, r in mw.sort_values("kickoff_utc").iterrows():
    for t in (r.home_team, r.away_team):
        team_games.setdefault(t, []).append((r.espn_id, r.kickoff_utc))
md, rest = {}, {}
for t, gs in team_games.items():
    for i, (eid, ko) in enumerate(gs):
        md.setdefault(eid, []).append(i + 1)
        rest.setdefault(eid, []).append(
            (ko - gs[i - 1][1]).total_seconds() / 86400 if i else np.nan)
mw["matchday_mean"] = mw.espn_id.map(lambda e: float(np.mean(md[e])))
mw["rest_days_min"] = mw.espn_id.map(
    lambda e: float(np.nanmin(rest[e])) if not all(np.isnan(x) for x in rest[e]) else np.nan)

# ── A. 扩展天气: 每城批量, 开球时刻 + 2h 窗口均值 ──────────────────────
HOURLY = "wet_bulb_temperature_2m,shortwave_radiation,wind_speed_10m,cloud_cover,precipitation"
VARS = ["wet_bulb", "radiation", "wind", "cloud", "precip"]
d0, d1 = mw.kickoff_utc.min().strftime("%Y-%m-%d"), mw.kickoff_utc.max().strftime("%Y-%m-%d")
wx_city = {}
for city, g in mw.groupby("venue_city"):
    lat, lon = g.iloc[0].lat, g.iloc[0].lon
    df = None
    for ep in ("archive-api.open-meteo.com/v1/archive",
               "historical-forecast-api.open-meteo.com/v1/forecast"):
        try:
            j = requests.get(f"https://{ep}", params=dict(
                latitude=lat, longitude=lon, start_date=d0, end_date=d1,
                hourly=HOURLY, timezone="UTC"), timeout=60).json()
            h = j["hourly"]
            part = pd.DataFrame(
                dict(zip(VARS, (h["wet_bulb_temperature_2m"], h["shortwave_radiation"],
                                h["wind_speed_10m"], h["cloud_cover"], h["precipitation"]))),
                index=pd.to_datetime(h["time"], utc=True))
            df = part if df is None else df.combine_first(part)
        except Exception as e:
            print(f"  wx {city} {ep}: {e}")
    wx_city[city] = df
    time.sleep(0.2)

def wx_at(r):
    df = wx_city.get(r.venue_city)
    if df is None: return pd.Series(dtype=float)
    hr = r.kickoff_utc.floor("h")
    out = {}
    win = df.reindex([hr, hr + pd.Timedelta(hours=1), hr + pd.Timedelta(hours=2)])
    for v in VARS:
        out[f"{v}_ko"] = df[v].get(hr, np.nan)
        out[f"{v}_2h"] = win[v].mean()
    return pd.Series(out)

mw = pd.concat([mw, mw.apply(wx_at, axis=1)], axis=1)
print(f"weather ext: wet_bulb coverage {mw.wet_bulb_ko.notna().sum()}/{len(mw)}")

# ── D. ESPN summary: 上座/技术统计/换人/中断 ───────────────────────────
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={}"
BOX_KEYS = {"possessionPct": "poss", "totalPasses": "epasses", "accuratePasses": "eacc_passes",
            "foulsCommitted": "fouls", "yellowCards": "yellows", "redCards": "reds",
            "totalShots": "shots"}

def fetch_espn(eid):
    try:
        j = requests.get(SUMMARY.format(eid), timeout=30).json()
    except Exception as e:
        return {"espn_id": eid, "err": str(e)}
    rec = {"espn_id": eid, "err": ""}
    rec["attendance"] = (j.get("gameInfo") or {}).get("attendance")
    for side, t in zip(("h", "a"), (j.get("boxscore") or {}).get("teams", [])):
        for s in t.get("statistics", []):
            k = BOX_KEYS.get(s.get("name"))
            if k:
                try: rec[f"{k}_{side}"] = float(str(s.get("displayValue", "")).replace("%", ""))
                except ValueError: pass
    subs, delays = {"h": [], "a": []}, 0
    teams = [t.get("team", {}).get("displayName") for t in (j.get("boxscore") or {}).get("teams", [])]
    for e in j.get("keyEvents") or []:
        tid = (e.get("type") or {}).get("id")
        mn = re.match(r"(\d+)", str((e.get("clock") or {}).get("displayValue", "")))
        mn = int(mn.group(1)) if mn else None
        if tid == "76" and mn is not None:            # substitution
            nm = (e.get("team") or {}).get("displayName")
            if teams and nm == teams[0]: subs["h"].append(mn)
            elif teams and len(teams) > 1 and nm == teams[1]: subs["a"].append(mn)
        elif tid == "129":                            # start delay (降温暂停/中断代理)
            delays += 1
    rec["delays"] = delays
    for side in ("h", "a"):
        rec[f"first_sub_{side}"] = min(subs[side]) if subs[side] else np.nan
        rec[f"subs_by60_{side}"] = sum(1 for x in subs[side] if x <= 60)
    return rec

print("fetching ESPN summaries ...")
with ThreadPoolExecutor(max_workers=4) as ex:
    espn = pd.DataFrame(list(ex.map(fetch_espn, mw.espn_id.tolist())))
nerr = (espn.err.fillna("") != "").sum()
print(f"espn rows: {len(espn)}, errors: {nerr}")
if nerr: print(espn[espn.err != ""][["espn_id", "err"]].head().to_string())
# 防御: 任一列全网失败时补 NaN 列, 避免 KeyError
for c in ["epasses_h","epasses_a","fouls_h","fouls_a","yellows_h","yellows_a",
          "reds_h","reds_a","first_sub_h","first_sub_a","subs_by60_h","subs_by60_a",
          "attendance","delays","poss_h","poss_a","shots_h","shots_a"]:
    if c not in espn.columns: espn[c] = np.nan
mw = mw.merge(espn, on="espn_id", how="left")
mw["passes_total"] = mw.epasses_h + mw.epasses_a
mw["fouls_total"] = mw.fouls_h + mw.fouls_a
mw["cards_total"] = mw.yellows_h + mw.yellows_a + 3 * (mw.reds_h + mw.reds_a)
mw["first_sub_mean"] = mw[["first_sub_h", "first_sub_a"]].mean(axis=1)
mw["subs_by60_total"] = mw.subs_by60_h + mw.subs_by60_a
print(f"espn: attendance {mw.attendance.notna().sum()}, passes {mw.passes_total.notna().sum()}, "
      f"first_sub {mw.first_sub_mean.notna().sum()}")

# ── E. PMSR page-2 全量队级重解析(含新发布的淘汰赛报告) ────────────────
HUB = "https://www.fifatrainingcentre.com/en/fifa-world-cup-2026/match-report-hub.php"
html = requests.get(HUB, headers=UA, timeout=60).text
hrefs = sorted(set(re.findall(
    r'href="(/media/native/tournaments/fifa-world-cup/2026/[^"]+\.pdf)"', html)))
print(f"PMSR PDFs on hub: {len(hrefs)}")

CODE2NAME = {
    "ALG":"Algeria","ARG":"Argentina","AUS":"Australia","AUT":"Austria","BEL":"Belgium",
    "BIH":"Bosnia and Herzegovina","BRA":"Brazil","CAN":"Canada","CIV":"Ivory Coast",
    "COD":"DR Congo","COL":"Colombia","CPV":"Cape Verde","CRO":"Croatia","CUW":"Curaçao",
    "CZE":"Czech Republic","ECU":"Ecuador","EGY":"Egypt","ENG":"England","ESP":"Spain",
    "FRA":"France","GER":"Germany","GHA":"Ghana","HAI":"Haiti","IRN":"Iran","IRQ":"Iraq",
    "JOR":"Jordan","JPN":"Japan","KOR":"South Korea","KSA":"Saudi Arabia","MAR":"Morocco",
    "MEX":"Mexico","NED":"Netherlands","NOR":"Norway","NZL":"New Zealand","PAN":"Panama",
    "PAR":"Paraguay","POR":"Portugal","QAT":"Qatar","RSA":"South Africa","SCO":"Scotland",
    "SEN":"Senegal","SUI":"Switzerland","SWE":"Sweden","TUN":"Tunisia","TUR":"Turkey",
    "URU":"Uruguay","USA":"United States","UZB":"Uzbekistan",
}
FNPAIR = re.compile(r"M\d+[ _-]+([A-Z]{3})[ _-]+[Vv][ _-]+([A-Z]{3})")
# page-2 行模板: (列名, 正则)。home 值在左, away 在右。
ROWS = [
    ("xg",        re.compile(r"([\d.]+)\s*xG \(Expected Goals\)\s*([\d.]+)")),
    ("passes",    re.compile(r"(\d+)\s*\((\d+)\)\s*Total Passes \(Complete\)\s*(\d+)\s*\((\d+)\)")),
    ("linebreaks",re.compile(r"(\d+)\s*Completed Line Breaks\s*(\d+)")),
    ("recff",     re.compile(r"(\d+)\s*Receptions in the Final Third\s*(\d+)")),
    ("progress",  re.compile(r"(\d+)\s*Ball Progressions\s*(\d+)")),
    ("pressures", re.compile(r"(\d+)\s*\((\d+)\)\s*Defensive Pressures Applied \(Direct Pressures\)\s*(\d+)\s*\((\d+)\)")),
    ("turnovers", re.compile(r"(\d+)\s*Forced Turnovers\s*(\d+)")),
    ("secondballs",re.compile(r"(\d+)\s*Second Balls\s*(\d+)")),
    ("dist",      re.compile(r"([\d.]+)\s*km\s*Total Distance Covered\s*([\d.]+)\s*km")),
    # 标签自带 "20-25 km/h": 必须锚过 km/h 再取客队值, 否则误捕常数 25
    ("zone4",     re.compile(r"([\d.]+)\s*km\s*Zone 4.*?km/h\s*([\d.]+)\s*km")),
]

def parse_pmsr(href):
    fname = href.split("/")[-1]
    mno = re.search(r"M(\d+)", fname)
    pair = FNPAIR.search(fname)
    rec = {"match_no": int(mno.group(1)) if mno else None,
           "home_team": CODE2NAME.get(pair.group(1)) if pair else None,
           "away_team": CODE2NAME.get(pair.group(2)) if pair else None, "err": ""}
    fn = SC / fname.replace(" ", "_")
    try:
        if not fn.exists() or fn.stat().st_size < 10000:
            r = requests.get("https://www.fifatrainingcentre.com" + href.replace(" ", "%20"),
                             headers=UA, timeout=120)
            r.raise_for_status()
            fn.write_bytes(r.content)
        with pdfplumber.open(fn) as pdf:
            p2 = pdf.pages[2].extract_text() or ""
        for name, rx in ROWS:
            m = rx.search(p2)
            if not m: continue
            g = m.groups()
            if len(g) == 2:
                rec[f"{name}_h"], rec[f"{name}_a"] = float(g[0]), float(g[1])
            elif len(g) == 4:  # value (sub) ... value (sub)
                rec[f"{name}_h"], rec[f"{name}_h2"] = float(g[0]), float(g[1])
                rec[f"{name}_a"], rec[f"{name}_a2"] = float(g[2]), float(g[3])
    except Exception as e:
        rec["err"] = str(e)
    return rec

print("downloading+parsing PMSR (kept for OCR) ...")
with ThreadPoolExecutor(max_workers=6) as ex:
    pmsr = pd.DataFrame(ex.map(parse_pmsr, hrefs))
ok = pmsr.dist_h.notna().sum()
print(f"pmsr parsed: {ok}/{len(pmsr)}")
pmsr.to_csv(RW / "out/pmsr_team_stats.csv", index=False)

# join到主表(按队名对, 双向)
pmsr_j = pmsr.dropna(subset=["home_team", "away_team", "dist_h"]).copy()
pmsr_j["teamset"] = pmsr_j.apply(lambda r: frozenset([r.home_team, r.away_team]), axis=1)
pmsr_j["swap"] = False
mw["teamset"] = mw.apply(lambda r: frozenset([r.home_team, r.away_team]), axis=1)
cols_pm = [c for c in pmsr_j.columns if c.endswith(("_h", "_a", "_h2", "_a2"))]
mrg = mw.merge(pmsr_j[["teamset", "home_team"] + cols_pm].rename(
    columns={"home_team": "pmsr_home"}), on="teamset", how="left")
# PMSR 的 home 可能与 ESPN 主客相反 → 需要时交换 _h/_a
swap = mrg.pmsr_home.notna() & (mrg.pmsr_home != mrg.home_team)
for c in cols_pm:
    if c.endswith("_h") or c.endswith("_h2"):
        c2 = c.replace("_h", "_a")
        tmp = mrg.loc[swap, c].copy()
        mrg.loc[swap, c] = mrg.loc[swap, c2]
        mrg.loc[swap, c2] = tmp
mrg["dist_total"] = mrg.dist_h + mrg.dist_a
mrg["zone4_total"] = mrg.zone4_h + mrg.zone4_a
mrg["xg_total"] = mrg.xg_h + mrg.xg_a
mrg["pass_tempo"] = (mrg.passes_h + mrg.passes_a)  # ESPN 传球数亦可, PMSR 为准
mrg = mrg.drop(columns=["teamset", "pmsr_home"])
print(f"joined pmsr into {mrg.dist_total.notna().sum()}/{len(mrg)} matches")

mrg.to_csv(RW / "out/matches_deep.csv", index=False)
print(f"[done] out/matches_deep.csv  {mrg.shape}")
