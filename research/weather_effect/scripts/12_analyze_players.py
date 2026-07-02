"""
12_analyze_players.py — 球员级 + 队级"热×实力"分析。

A. 热×实力交互(队级, 不依赖 OCR): favorite 与 underdog 在高温下的跑动降幅是否不同?
   —— "热天削强队"假设的直接检验。每场两行(队级距离), 湿球×是否favorite 交互。
B. 球员级(OCR, 通过行级校验的数据):
   - Zone 5 真冲刺距离 / 冲刺次数 / 极速 vs 湿球温度(露天场)
   - 队均极速 vs 热(爆发力上限是否受热影响 —— Sky 的"最高时速不受热"复检)
输出: out/stats_players.json + figs/fig11_heat_x_strength.png
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _stats_utils import perm_corr, np_json, RS
from sklearn.linear_model import LinearRegression

ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
FIG = ROOT / "figs"
m = pd.read_csv(ROOT / "out/matches_deep.csv")
S = {}

# ── A. 队级 热×实力 交互 ──────────────────────────────────────────────
# 每场拆两行: (team, dist, is_fav, opp_elo_gap)。fav 用模型 p_fav 方(缺失场剔除)。
rows = []
for _, r in m.dropna(subset=["dist_h", "fav_side", "wet_bulb_ko"]).iterrows():
    for side in ("h", "a"):
        is_fav = int((r.fav_side == "H") == (side == "h"))
        rows.append(dict(espn_id=r.espn_id, team=r.home_team if side == "h" else r.away_team,
                         dist=r[f"dist_{side}"], zone4=r[f"zone4_{side}"], is_fav=is_fav,
                         wet_bulb=r.wet_bulb_ko, apparent=r.apparent_c,
                         open_air=r.open_air, p_fav=r.p_fav))
tl = pd.DataFrame(rows)
op = tl[tl.open_air == 1].copy()
S["A_n_team_obs_open"] = len(op)

# 交互回归: dist ~ wet_bulb + is_fav + wet_bulb×is_fav (露天)
X = pd.DataFrame({"wb": op.wet_bulb, "fav": op.is_fav, "wb_x_fav": op.wet_bulb * op.is_fav})
lr = LinearRegression().fit(X, op.dist)
S["A_interaction_km_per_degC_extra_for_fav"] = round(lr.coef_[2], 4)
# 置换检验交互项: 打乱 is_fav(场内配对交换)
obs = lr.coef_[2]
cnt = 0
nperm = 5000
for _ in range(nperm):
    sh = op.copy()
    flip = RS.rand(len(sh) // 2) < 0.5           # 每场是否交换双方 fav 标签
    flips = np.repeat(flip, 2)[:len(sh)]
    sh["is_fav"] = np.where(flips, 1 - sh.is_fav, sh.is_fav)
    Xp = pd.DataFrame({"wb": sh.wet_bulb, "fav": sh.is_fav, "wb_x_fav": sh.wet_bulb * sh.is_fav})
    c = LinearRegression().fit(Xp, sh.dist).coef_[2]
    cnt += abs(c) >= abs(obs) - 1e-12
S["A_interaction_perm_p"] = round((cnt + 1) / (nperm + 1), 4)
# 分桶直观: 热(wb>=22)/凉 × fav/dog 平均每队跑动
op["hot"] = (op.wet_bulb >= 22).astype(int)
piv = op.groupby(["hot", "is_fav"]).dist.agg(["mean", "count"]).round(2)
S["A_bucket_mean_dist"] = {f"hot{h}_fav{f}": dict(mean=float(piv.loc[(h, f), 'mean']),
                                                  n=int(piv.loc[(h, f), 'count']))
                           for h in (0, 1) for f in (0, 1) if (h, f) in piv.index}

# ── B. 球员级(OCR) ────────────────────────────────────────────────────
pp_path = ROOT / "out/player_physical.csv"
if pp_path.exists():
    pp = pd.read_csv(pp_path)
    S["B_n_player_rows"] = len(pp)
    S["B_n_team_pages"] = int(pp.groupby(["match_no", "team"]).ngroups)
    # join 天气: 经 pmsr match_no → teamset → matches_deep
    pm = pd.read_csv(ROOT / "out/pmsr_team_stats.csv")[["match_no", "home_team", "away_team"]]
    pp = pp.merge(pm, on="match_no", how="left")
    pp["teamset"] = pp.apply(lambda r: frozenset([r.home_team, r.away_team]), axis=1)
    mw = m.copy()
    mw["teamset"] = mw.apply(lambda r: frozenset([r.home_team, r.away_team]), axis=1)
    pp = pp.merge(mw[["teamset", "wet_bulb_ko", "apparent_c", "open_air", "venue_env"]],
                  on="teamset", how="left")
    # 队级聚合(只用覆盖率≥0.97 的完整队页)
    full = pp[pp.coverage >= 0.97]
    agg = full.groupby(["match_no", "team"]).agg(
        z5=("z5", "sum"), sprints=("sprints", "sum"), top_speed_max=("top_speed", "max"),
        top_speed_mean=("top_speed", "mean"), dist=("dist_m", "sum"),
        wet_bulb=("wet_bulb_ko", "first"), apparent=("apparent_c", "first"),
        open_air=("open_air", "first")).reset_index()
    S["B_n_full_teams"] = len(agg)
    ago = agg[agg.open_air == 1]
    S["B_open_n"] = len(ago)
    for y, lbl in [("z5", "zone5_true_sprint_m"), ("sprints", "sprint_count"),
                   ("top_speed_max", "top_speed_max"), ("top_speed_mean", "top_speed_mean")]:
        r_, p_, n_ = perm_corr(ago.wet_bulb, ago[y])
        S[f"B_open_{lbl}_vs_wetbulb"] = dict(rho=round(r_, 3), p=round(p_, 4), n=n_)
else:
    S["B_note"] = "player_physical.csv 不存在(OCR 未完成)"

# ── 图: 热×实力 ───────────────────────────────────────────────────────
plt.rcParams.update({"figure.dpi": 110, "font.size": 10, "axes.grid": True, "grid.alpha": .3})
fig, ax = plt.subplots(figsize=(7.5, 4.8))
for fav, c, lbl in [(1, "#c0392b", "favorite"), (0, "#2980b9", "underdog")]:
    d = op[op.is_fav == fav]
    ax.scatter(d.wet_bulb, d.dist, s=34, c=c, alpha=.6, edgecolor="w", label=lbl)
    b = np.polyfit(d.wet_bulb, d.dist, 1)
    xs = np.linspace(op.wet_bulb.min(), op.wet_bulb.max(), 40)
    ax.plot(xs, np.polyval(b, xs), "--", c=c, lw=2)
ax.set(title=f"Heat x strength (open-air, team-level): interaction "
             f"{S['A_interaction_km_per_degC_extra_for_fav']} km/°C (p={S['A_interaction_perm_p']})",
       xlabel="Wet-bulb temp at kickoff (°C)", ylabel="Team distance (km)")
ax.legend()
fig.tight_layout(); fig.savefig(FIG / "fig11_heat_x_strength.png"); plt.close(fig)

json.dump(S, open(ROOT / "out/stats_players.json", "w"), ensure_ascii=False, indent=2, default=np_json)
print(json.dumps(S, ensure_ascii=False, indent=2, default=np_json))
