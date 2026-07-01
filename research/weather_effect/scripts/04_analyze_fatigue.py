"""
04_analyze_fatigue.py — 验证"高温→下半场体能崩盘"假设。

疲劳崩盘的可观测信号(若为真, 应随温度上升):
  - h2_share      = 下半场进球 / (上+下半场进球)   进球是否被推向下半场
  - h2_minus_h1   = 下半场 − 上半场 进球
  - late_share    = 75'+ 进球 / 常规时间进球         终场阶段是否更易丢球
所有相关用置换检验(20000);比例给 Wilson 95%CI。仅用常规时间(排除加时)。
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _stats_utils import perm_corr, residualize, wilson, ci_mean, demean_by, np_json, RS
ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
m = pd.read_csv(ROOT / "out/matches_weather_halves.csv")
FIG = ROOT / "figs"

# 常规时间进球分母
m["reg2_goals"] = m.h1_goals + m.h2_goals            # 上+下(不含加时)
scored = m[m.reg2_goals > 0].copy()                  # 有进球的场次才能算占比
scored["h2_share"] = scored.h2_goals / scored.reg2_goals
scored["late_share"] = scored.late2h_goals / scored.reg2_goals
m["h2_minus_h1"] = m.h2_goals - m.h1_goals

S = {"n_total": len(m), "n_scored": len(scored)}
# 全赛事基线: 上下半场进球总量
S["baseline"] = dict(
    total_h1=int(m.h1_goals.sum()), total_h2=int(m.h2_goals.sum()), total_et=int(m.et_goals.sum()),
    h2_share_overall=round(m.h2_goals.sum()/(m.h1_goals.sum()+m.h2_goals.sum()),3),
    late2h_goals=int(m.late2h_goals.sum()),
    matches_with_late_goal=int((m.late2h_goals>0).sum()),
)

WX = ["temp_c","humidity_pct","apparent_c","heat_humidity_index"]
def corr_block(frame, col, method="spearman"):
    out={}
    for k in WX:
        r,p,nn=perm_corr(frame[k], frame[col], method)
        out[k]=dict(stat=round(r,3), p=round(p,4), n=nn)
    return out

S["h2_share_vs_weather"]   = corr_block(scored, "h2_share")
S["late_share_vs_weather"] = corr_block(scored, "late_share")
S["h2_minus_h1_vs_weather"]= corr_block(m, "h2_minus_h1")

# 温度分桶: h2_share / late_share / 崩盘率(有75'+丢球的比例)
m["temp_bucket"]=pd.cut(m.temp_c,[-99,22,27,99],labels=["cool(<22)","mild(22-27)","hot(>=27)"])
scored["temp_bucket"]=pd.cut(scored.temp_c,[-99,22,27,99],labels=["cool(<22)","mild(22-27)","hot(>=27)"])
buckets={}
for b in ["cool(<22)","mild(22-27)","hot(>=27)"]:
    g=scored[scored.temp_bucket==b]; gm=m[m.temp_bucket==b]
    p_late,lo,hi=wilson(int((gm.late2h_goals>0).sum()), len(gm))
    buckets[b]=dict(n_scored=len(g), n=len(gm),
                    mean_h2_share=round(g.h2_share.mean(),3),
                    mean_late_share=round(g.late_share.mean(),3),
                    mean_h2_minus_h1=round(gm.h2_minus_h1.mean(),2),
                    late_goal_match_rate=round(p_late,3), late_ci=[round(lo,3),round(hi,3)],
                    mean_temp=round(gm.temp_c.mean(),1))
S["temp_buckets"]=buckets

# ---- 图: h2_share vs 温度 + late_share by bucket ----
plt.rcParams.update({"figure.dpi":110,"font.size":10,"axes.grid":True,"grid.alpha":.3})
fig, ax = plt.subplots(1,2,figsize=(12,4.6))
ax[0].scatter(scored.temp_c, scored.h2_share, s=42, c="#16a085", alpha=.7, edgecolor="w")
b=np.polyfit(scored.temp_c,scored.h2_share,1); xs=np.linspace(scored.temp_c.min(),scored.temp_c.max(),50)
ax[0].plot(xs,np.polyval(b,xs),"--",c="#2c3e50",lw=1.8)
r,p,_=perm_corr(scored.temp_c,scored.h2_share)
ax[0].axhline(0.5,ls=":",c="gray")
ax[0].set(title=f"2nd-half goal share vs temp (rho={r:.2f}, p={p:.2f}, n={len(scored)})",
          xlabel="Kickoff temperature (°C)", ylabel="2nd-half share of goals")
labels=list(buckets); lr=[buckets[k]["late_goal_match_rate"] for k in labels]
err=[[lr[i]-buckets[k]["late_ci"][0] for i,k in enumerate(labels)],[buckets[k]["late_ci"][1]-lr[i] for i,k in enumerate(labels)]]
ax[1].bar(labels,lr,yerr=err,capsize=6,color="#27ae60",alpha=.85)
for i,k in enumerate(labels): ax[1].text(i,lr[i]+.02,f"n={buckets[k]['n']}",ha="center",fontsize=9)
ax[1].set(title="Share of matches with a 75'+ goal, by temp",ylabel="Match rate (75'+ goal)",ylim=(0,1))
fig.tight_layout(); fig.savefig(FIG/"fig5_fatigue.png"); plt.close(fig)

json.dump(S, open(ROOT/"out/stats_fatigue.json","w"), ensure_ascii=False, indent=2,
          default=np_json)
print(json.dumps(S, ensure_ascii=False, indent=2,
      default=np_json))
print("\nfig -> fig5_fatigue.png")
