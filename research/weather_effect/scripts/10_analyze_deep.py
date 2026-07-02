"""
10_analyze_deep.py — v2 深挖分析。

预先指定的主假设 H1(验证性): 露天场比赛中, 开球体感温度 ↑ → 双方合计跑动 ↓。
  阴性对照: 封闭空调馆(室外温度不代表场上环境)中该效应应消失。
其余全部为探索性(H2-H7), 统一置换检验。

H1 体能×场馆环境(露天/顶棚/空调馆分层 + 湿球温度 + 多元控制)
H2 教练疲劳响应: 首次换人时间 / 60' 前换人数 vs 热
H3 比赛中断(降温暂停代理) vs 湿球温度
H4 比赛节奏: 传球/压迫/line breaks vs 热(露天)
H5 纪律: 犯规/红黄牌 vs 热
H7 xG vs 热(比进球更高功效的进攻产出)
附: 天气与赛程的共线性诊断(越到后期越热?)

输出: out/stats_deep.json + figs/fig8-10
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _stats_utils import perm_corr, residualize, ci_mean, np_json
from sklearn.linear_model import LinearRegression

ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
FIG = ROOT / "figs"
m = pd.read_csv(ROOT / "out/matches_deep.csv")
S = {"n": len(m), "primary_hypothesis":
     "H1: 露天场 apparent_c(开球) vs dist_total 负相关; 空调馆为阴性对照"}

phys = m.dropna(subset=["dist_total"]).copy()
env_n = phys.venue_env.value_counts().to_dict()
S["physical_n_by_env"] = env_n
print("physical matches by env:", env_n)

def corr(d, x, y, method="spearman"):
    r, p, n = perm_corr(d[x], d[y], method)
    return dict(rho=round(r, 3), p=round(p, 4), n=n)

# ── H1 主假设: 分层 + 湿球 ─────────────────────────────────────────────
op = phys[phys.venue_env == "open"]
ac = phys[phys.venue_env == "indoor_ac"]
cn = phys[phys.venue_env == "roof_canopy"]
S["H1_primary_open_apparent_vs_dist"] = corr(op, "apparent_c", "dist_total")
S["H1_negctrl_indoorac_apparent_vs_dist"] = corr(ac, "apparent_c", "dist_total")
S["H1_canopy_apparent_vs_dist"] = corr(cn, "apparent_c", "dist_total")
S["H1_all_apparent_vs_dist"] = corr(phys, "apparent_c", "dist_total")
S["H1_open_wetbulb_ko"] = corr(op, "wet_bulb_ko", "dist_total")
S["H1_open_wetbulb_2h"] = corr(op, "wet_bulb_2h", "dist_total")
S["H1_open_radiation"] = corr(op, "radiation_ko", "dist_total")
# 露天场斜率
b = np.polyfit(op.apparent_c, op.dist_total, 1)
S["H1_open_slope_km_per_degC"] = round(b[0], 3)

# 多元(露天): dist ~ apparent + altitude(经纬度代) + matchday + rest
def multi(d, xcols, y):
    dd = d.dropna(subset=xcols + [y])
    X = dd[xcols]; Y = dd[y]
    Xz = (X - X.mean()) / X.std(); Yz = (Y - Y.mean()) / Y.std()
    lr = LinearRegression().fit(Xz, Yz)
    return {"n": len(dd), "r2": round(lr.score(Xz, Yz), 3),
            **{f"beta_{c}": round(v, 3) for c, v in zip(xcols, lr.coef_)}}
# altitude 需重算? 09 没带 altitude — 用 07 的城市海拔近似: 从 lat/lon 不行, 直接查表
ELEV = {"Mexico City": 2245, "Guadalajara": 1665, "Guadalupe": 488, "Atlanta, Georgia": 307,
        "Kansas City, Missouri": 259, "Arlington, Texas": 176, "Foxborough, Massachusetts": 89,
        "Toronto": 83, "Inglewood, California": 40, "Vancouver": 18, "Houston, Texas": 13,
        "Seattle, Washington": 11, "Miami Gardens, Florida": 5, "East Rutherford, New Jersey": 4,
        "Santa Clara, California": 3, "Philadelphia, Pennsylvania": 0}
phys["altitude_m"] = phys.venue_city.map(ELEV)
op = phys[phys.venue_env == "open"]
S["H1_open_multivariate"] = multi(
    op, ["apparent_c", "altitude_m", "matchday_mean", "rest_days_min"], "dist_total")

# 交互检验: 全样本 dist ~ apparent×open_air (露天斜率是否显著更陡)
dd = phys.dropna(subset=["apparent_c", "dist_total"])
X = pd.DataFrame({"app": dd.apparent_c, "open": dd.open_air,
                  "app_x_open": dd.apparent_c * dd.open_air})
lr = LinearRegression().fit(X, dd.dist_total)
S["H1_interaction_slope_open_extra_km_per_degC"] = round(lr.coef_[2], 3)

# ── H2 教练疲劳响应(露天) ──────────────────────────────────────────────
opm = m[m.venue_env == "open"]
S["H2_first_sub_vs_apparent_open"] = corr(opm.dropna(subset=["first_sub_mean"]),
                                          "apparent_c", "first_sub_mean")
S["H2_subs_by60_vs_apparent_open"] = corr(opm.dropna(subset=["subs_by60_total"]),
                                          "apparent_c", "subs_by60_total")
S["H2_first_sub_vs_apparent_all"] = corr(m.dropna(subset=["first_sub_mean"]),
                                         "apparent_c", "first_sub_mean")

# ── H3 中断/降温暂停 vs 湿球 ───────────────────────────────────────────
S["H3_delays_vs_wetbulb_open"] = corr(opm.dropna(subset=["delays"]), "wet_bulb_ko", "delays")
hotwb = m[m.wet_bulb_ko >= 24]; coolwb = m[m.wet_bulb_ko < 24]
S["H3_delays_by_wetbulb"] = {
    "wetbulb>=24": dict(n=len(hotwb), mean_delays=round(hotwb.delays.mean(), 2)),
    "wetbulb<24": dict(n=len(coolwb), mean_delays=round(coolwb.delays.mean(), 2))}

# ── H4 节奏(露天, PMSR) ────────────────────────────────────────────────
op4 = op.copy()
op4["passes_pm"] = op4.passes_h + op4.passes_a
op4["pressures_pm"] = op4.pressures_h + op4.pressures_a
op4["linebreaks_pm"] = op4.linebreaks_h + op4.linebreaks_a
for k, col in [("passes", "passes_pm"), ("pressures", "pressures_pm"),
               ("linebreaks", "linebreaks_pm"), ("zone4", "zone4_total")]:
    S[f"H4_{k}_vs_apparent_open"] = corr(op4.dropna(subset=[col]), "apparent_c", col)

# ── H5 纪律 ────────────────────────────────────────────────────────────
S["H5_fouls_vs_apparent_all"] = corr(m.dropna(subset=["fouls_total"]), "apparent_c", "fouls_total")
S["H5_cards_vs_apparent_all"] = corr(m.dropna(subset=["cards_total"]), "apparent_c", "cards_total")

# ── H7 xG ─────────────────────────────────────────────────────────────
S["H7_xg_vs_apparent_open"] = corr(op.dropna(subset=["xg_total"]), "apparent_c", "xg_total")
S["H7_xg_vs_apparent_all"] = corr(phys.dropna(subset=["xg_total"]), "apparent_c", "xg_total")

# ── 共线性诊断: 天气 vs 赛程 ───────────────────────────────────────────
S["diag_apparent_vs_tournamentday"] = corr(m, "tournament_day", "apparent_c")
S["diag_apparent_vs_matchday"] = corr(m.dropna(subset=["matchday_mean"]), "matchday_mean", "apparent_c")

# ── 图 ────────────────────────────────────────────────────────────────
plt.rcParams.update({"figure.dpi": 110, "font.size": 10, "axes.grid": True, "grid.alpha": .3})
# fig8: 分层散点 露天 vs 空调馆
fig, ax = plt.subplots(1, 2, figsize=(12, 4.6), sharey=True)
for i, (d, ttl, c) in enumerate([(op, "Open-air", "#c0392b"), (ac, "Indoor AC (negative control)", "#7f8c8d")]):
    ax[i].scatter(d.apparent_c, d.dist_total, s=46, c=c, alpha=.75, edgecolor="w")
    if len(d) > 4:
        bb = np.polyfit(d.apparent_c, d.dist_total, 1)
        xs = np.linspace(d.apparent_c.min(), d.apparent_c.max(), 40)
        ax[i].plot(xs, np.polyval(bb, xs), "--", c="#2c3e50", lw=2)
    key = "H1_primary_open_apparent_vs_dist" if i == 0 else "H1_negctrl_indoorac_apparent_vs_dist"
    ax[i].set(title=f"{ttl}: rho={S[key]['rho']}, p={S[key]['p']}, n={S[key]['n']}",
              xlabel="Apparent temp at kickoff (°C)")
ax[0].set_ylabel("Combined distance (km)")
fig.tight_layout(); fig.savefig(FIG / "fig8_env_stratified.png"); plt.close(fig)

# fig9: 教练响应+中断
fig, ax = plt.subplots(1, 2, figsize=(12, 4.6))
d9 = opm.dropna(subset=["first_sub_mean"])
ax[0].scatter(d9.apparent_c, d9.first_sub_mean, s=46, c="#2980b9", alpha=.75, edgecolor="w")
bb = np.polyfit(d9.apparent_c, d9.first_sub_mean, 1)
xs = np.linspace(d9.apparent_c.min(), d9.apparent_c.max(), 40)
ax[0].plot(xs, np.polyval(bb, xs), "--", c="#2c3e50", lw=2)
r9 = S["H2_first_sub_vs_apparent_open"]
ax[0].set(title=f"Open-air: first substitution minute vs heat (rho={r9['rho']}, p={r9['p']})",
          xlabel="Apparent temp (°C)", ylabel="Mean first-sub minute (both teams)")
d9b = m.dropna(subset=["delays", "wet_bulb_ko"])
ax[1].scatter(d9b.wet_bulb_ko, d9b.delays, s=46, c="#16a085", alpha=.7, edgecolor="w")
r9b = S["H3_delays_vs_wetbulb_open"]
ax[1].set(title=f"Match interruptions vs wet-bulb temp (open: rho={r9b['rho']}, p={r9b['p']})",
          xlabel="Wet-bulb temp at kickoff (°C)", ylabel="Start-delay events")
fig.tight_layout(); fig.savefig(FIG / "fig9_coach_response.png"); plt.close(fig)

# fig10: 节奏面板
fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
for i, (col, lbl) in enumerate([("passes_pm", "Total passes"), ("pressures_pm", "Defensive pressures"),
                                 ("linebreaks_pm", "Completed line breaks")]):
    d10 = op4.dropna(subset=[col])
    ax[i].scatter(d10.apparent_c, d10[col], s=40, c="#8e44ad", alpha=.7, edgecolor="w")
    if len(d10) > 4:
        bb = np.polyfit(d10.apparent_c, d10[col], 1)
        xs = np.linspace(d10.apparent_c.min(), d10.apparent_c.max(), 40)
        ax[i].plot(xs, np.polyval(bb, xs), "--", c="#2c3e50", lw=1.8)
    k = ["H4_passes_vs_apparent_open", "H4_pressures_vs_apparent_open", "H4_linebreaks_vs_apparent_open"][i]
    ax[i].set(title=f"{lbl} (rho={S[k]['rho']}, p={S[k]['p']})", xlabel="Apparent temp (°C)")
ax[0].set_ylabel("Both teams combined (open-air)")
fig.tight_layout(); fig.savefig(FIG / "fig10_tempo.png"); plt.close(fig)

json.dump(S, open(ROOT / "out/stats_deep.json", "w"), ensure_ascii=False, indent=2, default=np_json)
print(json.dumps(S, ensure_ascii=False, indent=2, default=np_json))
