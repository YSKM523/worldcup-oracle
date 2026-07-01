"""
03_fetch_halftime.py — 抓 ESPN 每场进球时间, 拆上/下半场, 验证"下半场体能崩盘"假设。

ESPN summary keyEvents: type.id=='70' 为进球, period.number (1上/2下/>=3加时),
clock.displayValue 分钟, shootout=True 为点球大战(剔除)。

输出:
  out/halftime_goals.csv        每场 h1/h2/et 进球 + 校验
  out/matches_weather_halves.csv 天气底表 join 半场数据
"""
import re, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
import requests

ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={}"

base = pd.read_csv(ROOT / "out/matches_weather.csv")
base["espn_id"] = base["espn_id"].astype(str)

def parse_minute(dv):
    if not dv: return None
    m = re.match(r"(\d+)", str(dv).strip())
    return int(m.group(1)) if m else None

def fetch_one(eid):
    try:
        j = requests.get(SUMMARY.format(eid), timeout=30).json()
    except Exception as e:
        return {"espn_id": eid, "error": str(e)}
    ke = j.get("keyEvents") or []
    h1 = h2 = et = late2h = 0            # late2h = 下半场 75'+ 进球
    for e in ke:
        # 进球有多种 type id(70/137/98/173...), 统一用 scoringPlay 标记; 剔除点球大战
        if not e.get("scoringPlay") or e.get("shootout"):
            continue
        per = (e.get("period") or {}).get("number")
        mn = parse_minute((e.get("clock") or {}).get("displayValue"))
        if per == 1:   h1 += 1
        elif per == 2:
            h2 += 1
            if mn is not None and mn >= 75: late2h += 1
        elif per and per >= 3: et += 1
    # linescores 交叉校验(权威): 每 competitor 每半场净进球
    h1_ls = h2_ls = None
    try:
        comp = (j.get("header", {}).get("competitions") or [{}])[0]
        ls = [[int(x.get("displayValue", 0)) for x in (c.get("linescores") or [])]
              for c in comp.get("competitors", [])]
        if all(len(x) >= 2 for x in ls):
            h1_ls = sum(x[0] for x in ls)
            h2_ls = sum(x[1] for x in ls)
    except Exception:
        pass
    return {"espn_id": eid, "h1_goals": h1, "h2_goals": h2, "et_goals": et,
            "late2h_goals": late2h, "h1_ls": h1_ls, "h2_ls": h2_ls,
            "n_keyevents": len(ke), "error": ""}

print(f"抓取 {len(base)} 场 ESPN summary ...")
with ThreadPoolExecutor(max_workers=6) as ex:
    recs = list(ex.map(fetch_one, base.espn_id.tolist()))
h = pd.DataFrame(recs)

merged = base.merge(h, on="espn_id", how="left")
# 校验: 常规时间进球(h1+h2+et) 应等于终场总进球
merged["reg_goals"] = merged.h1_goals + merged.h2_goals + merged.et_goals
merged["goal_check_ok"] = merged.reg_goals == merged.total_goals
bad = merged[~merged.goal_check_ok]
print(f"进球数校验: {merged.goal_check_ok.sum()}/{len(merged)} 一致")
if len(bad):
    print("  不一致场次(可能含乌龙/数据缺口):")
    print(bad[["home_team","away_team","total_goals","h1_goals","h2_goals","et_goals","error"]].to_string())

h.to_csv(ROOT / "out/halftime_goals.csv", index=False)
merged.to_csv(ROOT / "out/matches_weather_halves.csv", index=False)
print(f"\n[done] -> out/matches_weather_halves.csv  ({len(merged)} 行)")
print(merged[["home_team","away_team","total_goals","h1_goals","h2_goals","et_goals","temp_c"]].head(8).to_string())
