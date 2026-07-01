"""
06_analyze_physical.py — 角度⑥: 用 FIFA 官方跑动/冲刺数据检验"高温压低体能输出"。
这是全研究最灵敏的疲劳直接指标(进球是低频, 跑动是连续量)。

因变量: combined_dist_km(双方合计总跑动), combined_sprint_km(双方 Zone4 冲刺距离)
自变量: temp_c / humidity_pct / apparent_c / local_hour
方法: 置换检验相关; 扣掉比赛节奏(总进球)后的偏相关; 温度分桶均值±95%CI; 图。
仅 71 场小组赛(FIFA 已发布 PMSR 的场次)。
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _stats_utils import perm_corr, residualize, wilson, ci_mean, demean_by, np_json, RS
ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
FIG = ROOT / "figs"
m = pd.read_csv(ROOT / "out/matches_weather_physical.csv")
d = m.dropna(subset=["combined_dist_km"]).copy()

S={"n_matches": len(d), "note": "仅小组赛(FIFA PMSR 已发布), 双方合计"}
S["descriptive"]={k:dict(min=round(d[k].min(),1),max=round(d[k].max(),1),mean=round(d[k].mean(),1))
                  for k in ["combined_dist_km","combined_sprint_km","temp_c","humidity_pct"]}

# 主相关 + 扣节奏(总进球)偏相关
S["corr"]={}; S["partial_corr_controlling_goals"]={}
for yv in ["combined_dist_km","combined_sprint_km"]:
    S["corr"][yv]={}; S["partial_corr_controlling_goals"][yv]={}
    for k in ["temp_c","humidity_pct","apparent_c","local_hour"]:
        r,p,nn=perm_corr(d[k], d[yv]); S["corr"][yv][k]=dict(rho=round(r,3),p=round(p,4),n=nn)
    # 扣总进球(比赛越开放跑动越多)后, 温度的偏相关
    ry=residualize(d[yv], d.total_goals); rt=residualize(d.temp_c, d.total_goals)
    pr,pp,pn=perm_corr(rt, ry, "pearson")
    S["partial_corr_controlling_goals"][yv]["temp_c"]=dict(r=round(pr,3),p=round(pp,4),n=pn)

# 温度分桶
d["temp_bucket"]=pd.cut(d.temp_c,[-99,22,27,99],labels=["cool(<22)","mild(22-27)","hot(>=27)"])
S["temp_buckets"]={}
for b,g in d.groupby("temp_bucket",observed=True):
    md,lo,hi=ci_mean(g.combined_dist_km); ms,slo,shi=ci_mean(g.combined_sprint_km)
    S["temp_buckets"][str(b)]=dict(n=len(g),mean_temp=round(g.temp_c.mean(),1),
        mean_dist_km=round(md,1), dist_ci=[round(lo,1),round(hi,1)],
        mean_sprint_km=round(ms,2), sprint_ci=[round(slo,2),round(shi,2)])

# 每队级(样本翻倍, 但同场两队共享温度→非独立, 仅作稳健性参考)
tt=pd.concat([
    d[["temp_c","home_dist_km"]].rename(columns={"home_dist_km":"team_dist"}),
    d[["temp_c","away_dist_km"]].rename(columns={"away_dist_km":"team_dist"})])
r,p,nn=perm_corr(tt.temp_c, tt.team_dist)
S["team_level_dist_vs_temp"]=dict(rho=round(r,3),p=round(p,4),n=nn,
    caveat="同场两队共享温度, 观测非独立, p 偏乐观")

# 斜率(每 +1°C 合计跑动变化, km)
b=np.polyfit(d.temp_c, d.combined_dist_km, 1)
S["slope_dist_per_degC_km"]=round(b[0],3)

# ---- 图 ----
plt.rcParams.update({"figure.dpi":110,"font.size":10,"axes.grid":True,"grid.alpha":.3})
fig,ax=plt.subplots(1,2,figsize=(12,4.6))
ax[0].scatter(d.temp_c,d.combined_dist_km,s=44,c="#c0392b",alpha=.75,edgecolor="w")
xs=np.linspace(d.temp_c.min(),d.temp_c.max(),50); ax[0].plot(xs,np.polyval(b,xs),"--",c="#2c3e50",lw=2)
r,p,_=perm_corr(d.temp_c,d.combined_dist_km)
ax[0].set(title=f"Combined running distance vs temp (rho={r:.2f}, p={p:.3f}, n={len(d)})",
          xlabel="Kickoff temperature (°C)", ylabel="Both teams' total distance (km)")
r2,p2,_=perm_corr(d.temp_c,d.combined_sprint_km)
ax[1].scatter(d.temp_c,d.combined_sprint_km,s=44,c="#e67e22",alpha=.75,edgecolor="w")
b2=np.polyfit(d.temp_c,d.combined_sprint_km,1); ax[1].plot(xs,np.polyval(b2,xs),"--",c="#2c3e50",lw=2)
ax[1].set(title=f"Combined sprint distance vs temp (rho={r2:.2f}, p={p2:.3f}, n={len(d)})",
          xlabel="Kickoff temperature (°C)", ylabel="Both teams' Zone-4 sprint dist (km)")
fig.tight_layout(); fig.savefig(FIG/"fig6_physical.png"); plt.close(fig)

json.dump(S,open(ROOT/"out/stats_physical.json","w"),ensure_ascii=False,indent=2,
          default=np_json)
print(json.dumps(S,ensure_ascii=False,indent=2,
      default=np_json))
print("\nfig -> fig6_physical.png")
