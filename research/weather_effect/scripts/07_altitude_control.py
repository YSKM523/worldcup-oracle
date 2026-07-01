"""
07_altitude_control.py — 角度⑥稳健性: 拆解"高温↓跑动"里的海拔混杂。

墨西哥城(~2200m)/瓜达拉哈拉(~1560m)既高海拔又热, 高原本身压跑动 -> 温度效应可能是伪相关。
四种互补方法验证 combined_dist ~ temp 是否在扣掉城市/海拔后仍成立:
  A. 控制海拔的偏相关 (residualize on altitude)
  B. 城市固定效应: 按城市去均值后, 只用"城内温度波动"识别 (gold standard)
  C. 剔除高海拔城市(>1000m)后重跑简单相关
  D. 多元回归 dist ~ temp + altitude 的标准化系数
海拔经 Open-Meteo elevation API 取(可复现)。置换检验给 p。
"""
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
import requests
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.linear_model import LinearRegression

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from _stats_utils import perm_corr, residualize, wilson, ci_mean, demean_by, np_json, RS
ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
FIG = ROOT / "figs"
m = pd.read_csv(ROOT / "out/matches_weather_physical.csv")
d = m.dropna(subset=["combined_dist_km"]).copy()

# --- 海拔: 每城一次 elevation API (用已有 lat/lon) ---
cities = d[["venue_city","lat","lon"]].drop_duplicates("venue_city")
elev = {}
for _, r in cities.iterrows():
    try:
        j = requests.get("https://api.open-meteo.com/v1/elevation",
                         params=dict(latitude=r.lat, longitude=r.lon), timeout=30).json()
        elev[r.venue_city] = float(j["elevation"][0])
    except Exception as e:
        print("elev err", r.venue_city, e); elev[r.venue_city] = np.nan
d["altitude_m"] = d.venue_city.map(elev)
print("城市海拔(m):")
for c, e in sorted(elev.items(), key=lambda kv: -kv[1]):
    print(f"  {c:32s} {e:6.0f}")

S = {"n": len(d)}

# 混杂强度: 温度 vs 海拔
r,p,_ = perm_corr(d.temp_c, d.altitude_m, "spearman")
S["temp_vs_altitude"] = dict(rho=round(r,3), p=round(p,4),
    note="正相关=高原偏热, 混杂存在" )
# 海拔 vs 跑动(混杂的另一条腿)
r,p,_ = perm_corr(d.altitude_m, d.combined_dist_km, "spearman")
S["altitude_vs_dist"] = dict(rho=round(r,3), p=round(p,4))

# baseline (未控制)
r0,p0,_ = perm_corr(d.temp_c, d.combined_dist_km, "spearman")
S["A_baseline_temp_vs_dist"] = dict(rho=round(r0,3), p=round(p0,4), n=len(d))

# A. 控制海拔的偏相关
ry = residualize(d.combined_dist_km, d.altitude_m)
rt = residualize(d.temp_c, d.altitude_m)
r,p,nn = perm_corr(rt, ry, "pearson")
S["A_partial_controlling_altitude"] = dict(r=round(r,3), p=round(p,4), n=nn)

# B. 城市固定效应: 城内去均值
d["dist_fe"] = demean_by(d, "combined_dist_km", "venue_city")
d["temp_fe"] = demean_by(d, "temp_c", "venue_city")
r,p,nn = perm_corr(d.temp_fe, d.dist_fe, "pearson")
# 城内温度波动还剩多少(FE 检验力的关键)
within_sd = d.groupby("venue_city").temp_c.std().mean()
S["B_city_fixed_effects"] = dict(r=round(r,3), p=round(p,4), n=nn,
    mean_within_city_temp_sd=round(within_sd,2),
    note="只用城内温度波动识别; 城内温差有限->检验力偏低")

# C. 剔除高海拔城市(>1000m)
hi = d[d.altitude_m > 1000].venue_city.unique().tolist()
low = d[d.altitude_m <= 1000]
r,p,nn = perm_corr(low.temp_c, low.combined_dist_km, "spearman")
S["C_exclude_high_altitude"] = dict(excluded_cities=hi, r=round(r,3), p=round(p,4), n=nn)

# D. 多元回归 dist ~ temp + altitude (标准化系数)
X = d[["temp_c","altitude_m"]].copy()
Xz = (X - X.mean())/X.std(); yz = (d.combined_dist_km - d.combined_dist_km.mean())/d.combined_dist_km.std()
lr = LinearRegression().fit(Xz, yz)
S["D_multiple_regression_std_beta"] = dict(
    beta_temp=round(lr.coef_[0],3), beta_altitude=round(lr.coef_[1],3), r2=round(lr.score(Xz,yz),3),
    note="标准化系数, 同尺度可比谁贡献大")
# 未标准化: 每 +1°C 的 km 斜率(控制海拔后)
lr2 = LinearRegression().fit(d[["temp_c","altitude_m"]], d.combined_dist_km)
S["D_slope_temp_km_per_degC_controlling_alt"] = round(lr2.coef_[0],3)
S["D_slope_alt_km_per_100m"] = round(lr2.coef_[1]*100,3)

# ---- 图: dist vs temp, 按海拔上色; 叠加低海拔子集趋势 ----
plt.rcParams.update({"figure.dpi":110,"font.size":10,"axes.grid":True,"grid.alpha":.3})
fig, ax = plt.subplots(1,2,figsize=(12,4.7))
sc=ax[0].scatter(d.temp_c, d.combined_dist_km, c=d.altitude_m, cmap="viridis", s=55, edgecolor="w")
xs=np.linspace(d.temp_c.min(),d.temp_c.max(),50)
ax[0].plot(xs,np.polyval(np.polyfit(d.temp_c,d.combined_dist_km,1),xs),"--",c="#c0392b",lw=2,label="all (n=%d)"%len(d))
ax[0].plot(xs,np.polyval(np.polyfit(low.temp_c,low.combined_dist_km,1),xs),":",c="#2c3e50",lw=2,label="low-alt only (n=%d)"%len(low))
plt.colorbar(sc,ax=ax[0],label="Altitude (m)")
ax[0].set(title="Distance vs temp, colored by altitude", xlabel="Temp (°C)", ylabel="Combined distance (km)"); ax[0].legend()
# 城市FE 残差图
ax[1].scatter(d.temp_fe, d.dist_fe, s=48, c="#16a085", alpha=.75, edgecolor="w")
xs2=np.linspace(d.temp_fe.min(),d.temp_fe.max(),50)
ax[1].plot(xs2,np.polyval(np.polyfit(d.temp_fe,d.dist_fe,1),xs2),"--",c="#2c3e50",lw=2)
rr=S["B_city_fixed_effects"]
ax[1].axhline(0,c="gray",lw=.6); ax[1].axvline(0,c="gray",lw=.6)
ax[1].set(title=f"Within-city (FE): dist vs temp (r={rr['r']}, p={rr['p']})",
          xlabel="Temp − city mean (°C)", ylabel="Distance − city mean (km)")
fig.tight_layout(); fig.savefig(FIG/"fig7_altitude_control.png"); plt.close(fig)

json.dump(S,open(ROOT/"out/stats_altitude.json","w"),ensure_ascii=False,indent=2,
          default=np_json)
print(json.dumps(S,ensure_ascii=False,indent=2,
      default=np_json))
print("\nfig -> fig7_altitude_control.png")
