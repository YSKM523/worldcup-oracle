"""
01_build_dataset.py — 拼装天气效应研究的分析底表。

输出: research/weather_effect/out/matches_weather.csv
每行一场已完赛的 2026 世界杯比赛，带:
  - 比分/结果/总进球
  - 模型赛前胜率 (p_home/draw/away) + brier
  - favorite / underdog 判定 + 是否爆冷
  - 球场城市的经纬度/时区
  - 开球那一小时的气温、相对湿度、体感温度(apparent)
  - 本地开球小时 + 时段分类
"""
import sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd
import requests

ROOT = Path("/home/ubuntu/worldcup-oracle")
OUT = ROOT / "research/weather_effect/out"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. 16 个主办城市 -> 球场经纬度 + 时区 (venue_city 字符串按 parquet 里的原样为 key)
# ---------------------------------------------------------------------------
CITIES = {
    "Arlington, Texas":            (32.7473, -97.0945, "America/Chicago",    "AT&T Stadium"),
    "Inglewood, California":       (33.9535, -118.3392, "America/Los_Angeles","SoFi Stadium"),
    "East Rutherford, New Jersey": (40.8135, -74.0745, "America/New_York",   "MetLife Stadium"),
    "Atlanta, Georgia":            (33.7554, -84.4008, "America/New_York",   "Mercedes-Benz Stadium"),
    "Foxborough, Massachusetts":   (42.0909, -71.2643, "America/New_York",   "Gillette Stadium"),
    "Vancouver":                   (49.2768, -123.1120,"America/Vancouver",  "BC Place"),
    "Houston, Texas":              (29.6847, -95.4107, "America/Chicago",    "NRG Stadium"),
    "Miami Gardens, Florida":      (25.9580, -80.2389, "America/New_York",   "Hard Rock Stadium"),
    "Toronto":                     (43.6332, -79.4185, "America/Toronto",    "BMO Field"),
    "Santa Clara, California":     (37.4030, -121.9700,"America/Los_Angeles","Levi's Stadium"),
    "Philadelphia, Pennsylvania":  (39.9008, -75.1675, "America/New_York",   "Lincoln Financial Field"),
    "Seattle, Washington":         (47.5952, -122.3316,"America/Los_Angeles","Lumen Field"),
    "Kansas City, Missouri":       (39.0489, -94.4839, "America/Chicago",    "Arrowhead Stadium"),
    "Mexico City":                 (19.3029, -99.1505, "America/Mexico_City","Estadio Azteca"),
    "Guadalajara":                 (20.6819, -103.4625,"America/Mexico_City","Estadio Akron"),
    "Guadalupe":                   (25.6690, -100.2440,"America/Monterrey",  "Estadio BBVA (Monterrey)"),
}

# ---------------------------------------------------------------------------
# 2. 载入比赛结果 (已完赛) + 模型胜率
# ---------------------------------------------------------------------------
res = pd.read_parquet(ROOT / "data/cache/wc2026_results.parquet")
res = res[res.completed].copy()
res["kickoff_utc"] = pd.to_datetime(res["kickoff_utc"], utc=True)
res["home_score"] = res["home_score"].astype(int)
res["away_score"] = res["away_score"].astype(int)
res["total_goals"] = res["home_score"] + res["away_score"]
res["gd"] = res["home_score"] - res["away_score"]
res["outcome"] = np.where(res.gd > 0, "H", np.where(res.gd < 0, "A", "D"))

# 模型赛前概率
mp = pd.read_csv(ROOT / "results/evaluations/match_scores.csv")
mp["kickoff_utc"] = pd.to_datetime(mp["kickoff_utc"], utc=True)
mp = mp[["kickoff_utc", "home_team", "away_team", "p_home", "p_draw", "p_away", "brier"]]

df = res.merge(mp, on=["kickoff_utc", "home_team", "away_team"], how="left")
print(f"[merge] results={len(res)}  matched_model_probs={df.p_home.notna().sum()}")

# ---------------------------------------------------------------------------
# 3. favorite / underdog + 爆冷判定 (用模型赛前概率;缺失则跳过该场的爆冷分析)
#    淘汰赛: 模型给的是晋级概率(p_draw=0), 故按 ESPN winner 列(含点球晋级方)判;
#    小组赛: 按 90 分钟结果判(favorite 没赢=爆冷, 含被逼平)。
# ---------------------------------------------------------------------------
def favorite_side(r):
    if pd.isna(r.p_home):
        return np.nan
    # favorite = 胜率更高的一方(主/客)
    return "H" if r.p_home >= r.p_away else "A"

df["fav_side"] = df.apply(favorite_side, axis=1)
df["p_fav"] = df.apply(lambda r: np.nan if pd.isna(r.fav_side)
                       else (r.p_home if r.fav_side == "H" else r.p_away), axis=1)

def fav_won_fn(r):
    if pd.isna(r.fav_side):
        return np.nan
    fav_team = r.home_team if r.fav_side == "H" else r.away_team
    if r.stage != "group" and isinstance(r.winner, str) and r.winner:
        return int(r.winner == fav_team)          # 淘汰赛按晋级(含点球)
    return int(r.outcome == r.fav_side)           # 小组赛按 90 分钟结果
df["fav_won"] = df.apply(fav_won_fn, axis=1)
df["upset"] = df.fav_won.apply(lambda v: np.nan if pd.isna(v) else 1 - int(v))

# ---------------------------------------------------------------------------
# 4. 城市坐标/时区
# ---------------------------------------------------------------------------
missing = sorted(set(df.venue_city) - set(CITIES))
if missing:
    print("!! 未映射城市:", missing); sys.exit(1)
df["lat"] = df.venue_city.map(lambda c: CITIES[c][0])
df["lon"] = df.venue_city.map(lambda c: CITIES[c][1])
df["tz"]  = df.venue_city.map(lambda c: CITIES[c][2])
df["stadium"] = df.venue_city.map(lambda c: CITIES[c][3])

# 本地开球小时 + 时段
def local_hour(r):
    return r.kickoff_utc.tz_convert(r.tz).hour + r.kickoff_utc.tz_convert(r.tz).minute / 60
df["local_hour"] = df.apply(local_hour, axis=1)
def daypart(h):
    if h < 15:  return "midday(<15)"
    if h < 18:  return "afternoon(15-18)"
    if h < 21:  return "evening(18-21)"
    return "night(>=21)"
df["daypart"] = df.local_hour.apply(daypart)

# ---------------------------------------------------------------------------
# 5. 天气: Open-Meteo. 每城市一次批量请求覆盖全日期范围, 再按开球小时对齐。
#    存档 API 对最近几天有延迟 -> 缺失时回退历史预报 API。
# ---------------------------------------------------------------------------
HOURLY = "temperature_2m,relative_humidity_2m,apparent_temperature"
def fetch_city(lat, lon, d0, d1, endpoint):
    url = f"https://{endpoint}/v1/{'archive' if 'archive' in endpoint else 'forecast'}"
    params = dict(latitude=lat, longitude=lon, start_date=d0, end_date=d1,
                  hourly=HOURLY, timezone="UTC")
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    h = r.json()["hourly"]
    return pd.DataFrame({
        "t": pd.to_datetime(h["time"], utc=True),
        "temp": h["temperature_2m"],
        "rh": h["relative_humidity_2m"],
        "apparent": h["apparent_temperature"],
    }).set_index("t")

d0 = df.kickoff_utc.min().strftime("%Y-%m-%d")
d1 = df.kickoff_utc.max().strftime("%Y-%m-%d")
rows = []
for city, g in df.groupby("venue_city"):
    lat, lon = CITIES[city][0], CITIES[city][1]
    wx = None
    for ep in ("archive-api.open-meteo.com", "historical-forecast-api.open-meteo.com"):
        try:
            part = fetch_city(lat, lon, d0, d1, ep)
            wx = part if wx is None else wx.combine_first(part)
        except Exception as e:
            print(f"  [{city}] {ep} err: {e}")
    if wx is None:
        print(f"!! {city} 无天气数据"); continue
    for idx, r in g.iterrows():
        hr = r.kickoff_utc.floor("h")
        w = wx.reindex([hr]).iloc[0] if hr in wx.index else wx.iloc[(wx.index - hr).map(abs).argmin()]
        rows.append((idx, w["temp"], w["rh"], w["apparent"]))
    print(f"  [{city}] {len(g)} matches, weather rows={len(wx)}")
    time.sleep(0.3)

wxdf = pd.DataFrame(rows, columns=["idx", "temp_c", "humidity_pct", "apparent_c"]).set_index("idx")
df = df.join(wxdf)
df["heat_humidity_index"] = df.temp_c * df.humidity_pct / 100.0  # 简单热湿代理

# ---------------------------------------------------------------------------
# 6. 保存
# ---------------------------------------------------------------------------
cols = ["espn_id","date","kickoff_utc","stage","home_team","away_team",
        "home_score","away_score","total_goals","gd","outcome","winner",
        "p_home","p_draw","p_away","brier","fav_side","p_fav","upset","fav_won",
        "venue_city","stadium","lat","lon","tz","local_hour","daypart",
        "temp_c","humidity_pct","apparent_c","heat_humidity_index"]
out = df[cols].sort_values("kickoff_utc")
out.to_csv(OUT / "matches_weather.csv", index=False)
print(f"\n[done] {len(out)} rows -> {OUT/'matches_weather.csv'}")
print("weather coverage:", out.temp_c.notna().sum(), "/", len(out))
print(out[["kickoff_utc","home_team","away_team","total_goals","temp_c","humidity_pct","local_hour","upset"]].head(8).to_string())
