"""
02_analyze.py — 四角度分析 + 出图 + 落盘 stats.json

角度①爆冷率 vs 天气(含扣实力后的偏相关)
角度②总进球 vs 天气
角度③本地开球时段效应
角度④模型残差(brier / 校准偏差) vs 天气

所有显著性用置换检验(permutation, 稳健于小样本);比例给 Wilson 95%CI。
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _stats_utils import perm_corr, residualize, wilson, ci_mean, demean_by, np_json, RS
ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
df = pd.read_csv(ROOT / "out/matches_weather.csv")
FIG = ROOT / "figs"; FIG.mkdir(exist_ok=True)
S = {"n_total": len(df)}

# ------- 工具函数 -------
WX = {"temp_c": "气温(°C)", "humidity_pct": "相对湿度(%)",
      "apparent_c": "体感温度(°C)", "heat_humidity_index": "热湿指数",
      "local_hour": "本地开球小时"}

# ============ 描述统计 ============
S["descriptive"] = {
    k: dict(min=round(df[k].min(),1), max=round(df[k].max(),1),
            mean=round(df[k].mean(),1), median=round(df[k].median(),1))
    for k in ["temp_c","humidity_pct","apparent_c","local_hour","total_goals"]
}
# 共线性: 天气变量之间 & 与时段
coll = df[["temp_c","humidity_pct","apparent_c","local_hour"]].corr(method="spearman").round(2)
S["collinearity_spearman"] = json.loads(coll.to_json())

# ============ 角度① 爆冷率 vs 天气 ============
d1 = df.dropna(subset=["upset","p_fav"]).copy()
S["n_with_model"] = len(d1)
S["overall_upset_rate"] = list(map(lambda v: round(v,3), wilson(int(d1.upset.sum()), len(d1))))
ang1 = {"raw_corr": {}, "partial_corr_controlling_p_fav": {}, "buckets": {}}
for k in ["temp_c","humidity_pct","apparent_c","heat_humidity_index"]:
    r, p, nn = perm_corr(d1[k], d1.upset, "spearman")
    ang1["raw_corr"][k] = dict(rho=round(r,3), p=round(p,4), n=nn)
    # 偏相关: upset 和 天气 都扣掉 p_fav(赛前实力差) 后再相关
    ru = residualize(d1.upset, d1.p_fav)
    rk = residualize(d1[k], d1.p_fav)
    pr, pp, pn = perm_corr(rk, ru, "pearson")
    ang1["partial_corr_controlling_p_fav"][k] = dict(r=round(pr,3), p=round(pp,4), n=pn)
# 温度分桶爆冷率
d1["temp_bucket"] = pd.cut(d1.temp_c, [-99,22,27,99], labels=["cool(<22)","mild(22-27)","hot(>=27)"])
for b, g in d1.groupby("temp_bucket", observed=True):
    p,lo,hi = wilson(int(g.upset.sum()), len(g))
    ang1["buckets"][str(b)] = dict(n=len(g), upset_rate=round(p,3), ci=[round(lo,3),round(hi,3)],
                                   mean_temp=round(g.temp_c.mean(),1))
S["angle1_upset"] = ang1

# ============ 角度② 总进球 vs 天气 ============
ang2 = {"corr": {}, "buckets": {}}
for k in ["temp_c","humidity_pct","apparent_c","heat_humidity_index"]:
    r,p,nn = perm_corr(df[k], df.total_goals, "spearman")
    ang2["corr"][k] = dict(rho=round(r,3), p=round(p,4), n=nn)
df["temp_bucket"] = pd.cut(df.temp_c, [-99,22,27,99], labels=["cool(<22)","mild(22-27)","hot(>=27)"])
for b,g in df.groupby("temp_bucket", observed=True):
    ang2["buckets"][str(b)] = dict(n=len(g), mean_goals=round(g.total_goals.mean(),2),
                                   sd=round(g.total_goals.std(),2), mean_temp=round(g.temp_c.mean(),1))
S["angle2_goals"] = ang2

# ============ 角度③ 开球时段效应 ============
ang3 = {}
order = ["midday(<15)","afternoon(15-18)","evening(18-21)","night(>=21)"]
for dp in order:
    g = df[df.daypart == dp]
    if len(g)==0: continue
    gm = df[(df.daypart==dp)].dropna(subset=["upset"])
    p_up,lo,hi = wilson(int(gm.upset.sum()), len(gm)) if len(gm) else (np.nan,np.nan,np.nan)
    ang3[dp] = dict(n=len(g), mean_goals=round(g.total_goals.mean(),2),
                    mean_temp=round(g.temp_c.mean(),1), mean_humidity=round(g.humidity_pct.mean(),1),
                    upset_rate=round(p_up,3) if p_up==p_up else None, upset_ci=[round(lo,3),round(hi,3)] if p_up==p_up else None)
S["angle3_daypart"] = ang3

# ============ 角度④ 模型残差 vs 天气 ============
d4 = df.dropna(subset=["brier","p_fav","fav_won"]).copy()
d4["calib_resid"] = d4.fav_won - d4.p_fav   # >0: favorite 赢得比模型预期多
ang4 = {"brier_corr": {}, "calib_resid_corr": {}, "brier_buckets": {}}
for k in ["temp_c","humidity_pct","apparent_c"]:
    r,p,nn = perm_corr(d4[k], d4.brier, "spearman")
    ang4["brier_corr"][k] = dict(rho=round(r,3), p=round(p,4), n=nn)
    r2,p2,_ = perm_corr(d4[k], d4.calib_resid, "pearson")
    ang4["calib_resid_corr"][k] = dict(r=round(r2,3), p=round(p2,4), n=nn)
d4["temp_bucket"] = pd.cut(d4.temp_c, [-99,22,27,99], labels=["cool(<22)","mild(22-27)","hot(>=27)"])
for b,g in d4.groupby("temp_bucket", observed=True):
    ang4["brier_buckets"][str(b)] = dict(n=len(g), mean_brier=round(g.brier.mean(),3),
                                         mean_calib_resid=round(g.calib_resid.mean(),3))
S["angle4_model"] = ang4

# ============ 出图 ============
plt.rcParams.update({"figure.dpi":110, "font.size":10, "axes.grid":True, "grid.alpha":.3})

# fig1: 总进球 vs 温度散点+趋势
fig, ax = plt.subplots(figsize=(7,4.5))
ax.scatter(df.temp_c, df.total_goals, s=42, c="#c0392b", alpha=.75, edgecolor="w")
b = np.polyfit(df.temp_c, df.total_goals, 1); xs=np.linspace(df.temp_c.min(),df.temp_c.max(),50)
ax.plot(xs, np.polyval(b,xs), "--", c="#2c3e50", lw=1.8)
r,p,_ = perm_corr(df.temp_c, df.total_goals)
ax.set(title=f"Total goals vs kickoff temperature (Spearman rho={r:.2f}, p={p:.2f}, n={len(df)})",
       xlabel="Kickoff temperature (°C)", ylabel="Total goals")
fig.tight_layout(); fig.savefig(FIG/"fig1_goals_vs_temp.png"); plt.close(fig)

# fig2: 爆冷率 by 温度桶
fig, ax = plt.subplots(figsize=(7,4.5))
bs = ang1["buckets"]; labels=list(bs); rates=[bs[k]["upset_rate"] for k in labels]
err=[[rates[i]-bs[k]["ci"][0] for i,k in enumerate(labels)],[bs[k]["ci"][1]-rates[i] for i,k in enumerate(labels)]]
ax.bar(labels, rates, yerr=err, capsize=6, color="#e67e22", alpha=.85)
for i,k in enumerate(labels): ax.text(i, rates[i]+.02, f"n={bs[k]['n']}", ha="center", fontsize=9)
ax.axhline(S["overall_upset_rate"][0], ls=":", c="gray", label=f"overall {S['overall_upset_rate'][0]:.2f}")
ax.set(title="Upset rate by temperature bucket (95% Wilson CI)", ylabel="Upset rate (favorite fails to win)", ylim=(0,1)); ax.legend()
fig.tight_layout(); fig.savefig(FIG/"fig2_upset_by_temp.png"); plt.close(fig)

# fig3: 时段效应(进球+温度双轴)
fig, ax = plt.subplots(figsize=(7.5,4.5))
dps=[d for d in order if d in ang3]; goals=[ang3[d]["mean_goals"] for d in dps]; temps=[ang3[d]["mean_temp"] for d in dps]; ns=[ang3[d]["n"] for d in dps]
ax.bar(dps, goals, color="#2980b9", alpha=.8, label="mean goals")
for i,d in enumerate(dps): ax.text(i, goals[i]+.05, f"n={ns[i]}", ha="center", fontsize=9)
ax2=ax.twinx(); ax2.plot(dps, temps, "o-", c="#c0392b", lw=2, label="mean temp")
ax.set(title="Kickoff daypart: goals (bars) vs temperature (line)", ylabel="Mean total goals"); ax2.set_ylabel("Mean temp (°C)", color="#c0392b")
ax.set_xticks(range(len(dps))); ax.set_xticklabels(dps, rotation=15)
fig.tight_layout(); fig.savefig(FIG/"fig3_daypart.png"); plt.close(fig)

# fig4: 模型 brier vs 湿度
fig, ax = plt.subplots(figsize=(7,4.5))
ax.scatter(d4.humidity_pct, d4.brier, s=42, c="#8e44ad", alpha=.75, edgecolor="w")
b=np.polyfit(d4.humidity_pct,d4.brier,1); xs=np.linspace(d4.humidity_pct.min(),d4.humidity_pct.max(),50)
ax.plot(xs, np.polyval(b,xs), "--", c="#2c3e50", lw=1.8)
r,p,_=perm_corr(d4.humidity_pct,d4.brier)
ax.set(title=f"Model Brier vs humidity (Spearman rho={r:.2f}, p={p:.2f}, n={len(d4)})",
       xlabel="Relative humidity (%)", ylabel="Brier score (lower=better)")
fig.tight_layout(); fig.savefig(FIG/"fig4_brier_vs_humidity.png"); plt.close(fig)

json.dump(S, open(ROOT/"out/stats.json","w"), ensure_ascii=False, indent=2, default=np_json)
print(json.dumps(S, ensure_ascii=False, indent=2, default=np_json))
print("\nfigs:", [p.name for p in sorted(FIG.glob('*.png'))])
