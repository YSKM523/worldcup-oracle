"""
08_export_web.py — 导出 web/public/weather.json 供 dashboard「天气研究」板块使用。

内容:
  study    六角度研究的关键结论数字(读 out/stats*.json)
  matches  每场天气: 已完赛=实测(matches_weather.csv);
           未开赛且对阵已定=Open-Meteo 预报(16 天窗口内)
  adjust   实验性天气校准参数(角度④校准残差 ~ 温度, 正部 James-Stein 收缩)
           —— 明确标注实验性, 不改官方预测; |t|<1 时收缩为 0(诚实归零)

与 data.json 同模式: 同时写 web/public/ 和 web/out/(cron 不重跑 next build)。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import requests

ROOT = Path("/home/ubuntu/worldcup-oracle")
RW = ROOT / "research/weather_effect"
WEB_PUBLIC = ROOT / "web/public"
WEB_OUT = ROOT / "web/out"

HOURLY = "temperature_2m,relative_humidity_2m,apparent_temperature"
HOT_C = 27.0

# ── 1. 已完赛: 实测天气 ────────────────────────────────────────────────
mw = pd.read_csv(RW / "out/matches_weather.csv")
mw["espn_id"] = mw.espn_id.astype(str)
city_geo = mw.drop_duplicates("venue_city").set_index("venue_city")[["lat", "lon"]]

matches = {}
for _, r in mw.iterrows():
    matches[r.espn_id] = {
        "temp_c": round(float(r.temp_c), 1),
        "humidity_pct": int(r.humidity_pct),
        "apparent_c": round(float(r.apparent_c), 1),
        "hot": bool(r.temp_c >= HOT_C),
        "forecast": False,
    }

# ── 2. 未开赛且对阵已定: 预报天气(Open-Meteo forecast, ≤16 天) ─────────
res = pd.read_parquet(ROOT / "data/cache/wc2026_results.parquet")
res["espn_id"] = res.espn_id.astype(str)
res["kickoff_utc"] = pd.to_datetime(res.kickoff_utc, utc=True)
placeholder = res.home_team.str.contains("Winner|Loser", na=True) | \
              res.away_team.str.contains("Winner|Loser", na=True)
upcoming = res[~res.completed & ~placeholder & res.venue_city.isin(city_geo.index)]

fc_cache: dict[str, pd.DataFrame] = {}
def forecast_city(city):
    if city not in fc_cache:
        g = city_geo.loc[city]
        j = requests.get("https://api.open-meteo.com/v1/forecast",
                         params=dict(latitude=g.lat, longitude=g.lon, hourly=HOURLY,
                                     timezone="UTC", forecast_days=16), timeout=30).json()
        h = j["hourly"]
        fc_cache[city] = pd.DataFrame(
            {"temp": h["temperature_2m"], "rh": h["relative_humidity_2m"],
             "app": h["apparent_temperature"]},
            index=pd.to_datetime(h["time"], utc=True))
    return fc_cache[city]

n_fc = 0
for _, r in upcoming.iterrows():
    try:
        wx = forecast_city(r.venue_city)
        hr = r.kickoff_utc.floor("h")
        if hr not in wx.index:
            continue                      # 超出预报窗口, 等下次 cron
        w = wx.loc[hr]
        if pd.isna(w.temp):
            continue
        matches[r.espn_id] = {
            "temp_c": round(float(w.temp), 1),
            "humidity_pct": int(w.rh),
            "apparent_c": round(float(w.app), 1),
            "hot": bool(w.temp >= HOT_C),
            "forecast": True,
        }
        n_fc += 1
    except Exception as e:
        print(f"  forecast err {r.venue_city}: {e}")

# ── 3. 实验性天气校准(角度④): calib_resid ~ temp 的收缩斜率 ──────────
d = mw.dropna(subset=["p_fav", "fav_won"]).copy()
d["calib_resid"] = d.fav_won - d.p_fav
x = d.temp_c.to_numpy(float); y = d.calib_resid.to_numpy(float)
n = len(x)
slope, intercept = np.polyfit(x, y, 1)
resid = y - (slope * x + intercept)
se = np.sqrt((resid**2).sum() / (n - 2) / ((x - x.mean())**2).sum())
t = slope / se
shrink = max(0.0, 1.0 - 1.0 / (t * t)) if t != 0 else 0.0   # 正部 James-Stein
slope_shrunk = slope * shrink
CAP_PP = 3.0                                                # 修正幅度封顶 ±3pp
adjust = {
    "slope_pp_per_degC": round(slope * 100, 3),
    "t_stat": round(float(t), 2),
    "shrink_factor": round(float(shrink), 3),
    "slope_shrunk_pp_per_degC": round(slope_shrunk * 100, 3),
    "ref_temp_c": round(float(x.mean()), 1),
    "cap_pp": CAP_PP,
    "n": int(n),
    "note": "实验性: favorite 校准残差~温度的收缩斜率; 研究结论为不显著, |t|<1 时自动归零",
}
# 每场的实验修正(pp, 加到 favorite 概率上; 负=酷热削 favorite)
for eid, w in matches.items():
    delta = slope_shrunk * (w["temp_c"] - x.mean()) * 100
    w["exp_delta_pp"] = round(float(np.clip(delta, -CAP_PP, CAP_PP)), 1)

# ── 4. 研究结论摘要(读 stats*.json, 数字与 REPORT 同源) ───────────────
s  = json.load(open(RW / "out/stats.json"))
sp = json.load(open(RW / "out/stats_physical.json"))
sa = json.load(open(RW / "out/stats_altitude.json"))
sf = json.load(open(RW / "out/stats_fatigue.json"))
study = {
    "n_matches": s["n_total"],
    "n_physical": sp["n_matches"],
    "dist_vs_apparent": sp["corr"]["combined_dist_km"]["apparent_c"],      # ★主结果
    "dist_vs_temp": sp["corr"]["combined_dist_km"]["temp_c"],
    "sprint_vs_temp": sp["corr"]["combined_sprint_km"]["temp_c"],
    "slope_km_per_degC": sp["slope_dist_per_degC_km"],
    "dist_buckets": sp["temp_buckets"],
    "altitude_partial": sa["A_partial_controlling_altitude"],
    "altitude_excl_high": sa["C_exclude_high_altitude"],
    "upset_partial": s["angle1_upset"]["partial_corr_controlling_p_fav"]["temp_c"],
    "upset_buckets": s["angle1_upset"]["buckets"],
    "goals_vs_temp": s["angle2_goals"]["corr"]["temp_c"],
    "h2_share_vs_temp": sf["h2_share_vs_weather"]["temp_c"],
    "calib_buckets": s["angle4_model"]["brier_buckets"],
}

payload = json.dumps({
    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    "study": study,
    "adjust": adjust,
    "matches": matches,
}, ensure_ascii=False)

WEB_PUBLIC.mkdir(parents=True, exist_ok=True)
(WEB_PUBLIC / "weather.json").write_text(payload)
if WEB_OUT.exists():
    (WEB_OUT / "weather.json").write_text(payload)

# 图表同步(研究 figs -> web 静态资源; out 也要, cron 不重跑 next build)
import shutil
for dest in (WEB_PUBLIC / "research", *( [WEB_OUT / "research"] if WEB_OUT.exists() else [] )):
    dest.mkdir(parents=True, exist_ok=True)
    for fig in (RW / "figs").glob("*.png"):
        shutil.copy2(fig, dest / fig.name)
print(f"[done] weather.json: {len(matches)} matches ({n_fc} forecast), "
      f"adjust slope={adjust['slope_shrunk_pp_per_degC']}pp/°C (shrink={adjust['shrink_factor']})")
