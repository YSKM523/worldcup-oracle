"""
05_fetch_fifa_physical.py — 抓 FIFA Training Centre 赛后报告(PMSR PDF)的球队级体能数据。

数据源: https://www.fifatrainingcentre.com/.../PMSR-Mxx ... .pdf  (每场一份, 仅 72 场小组赛已发布)
提取(page 2 Key Statistics, 文本层可读):
  - Total Distance Covered (km)  home / away
  - Zone 4 – Low Speed Sprinting 20-25 km/h (km)  home / away   (队级唯一稳定的冲刺代理)
队名: pages 含 'Physical Data <Team>' (先主后客) 精确识别, 再按球队集合 join 天气表。

输出: out/fifa_physical.csv, out/matches_weather_physical.csv
PDF 下载到 scratchpad, 解析后即删(省磁盘)。
"""
import re, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests, pdfplumber
import pandas as pd

ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
SC = Path("/tmp/claude-1000/-home-ubuntu/425320c7-7790-479f-a972-88a803318312/scratchpad/fifa_pdf")
SC.mkdir(parents=True, exist_ok=True)
BASE = "https://www.fifatrainingcentre.com"
HUB = BASE + "/en/fifa-world-cup-2026/match-report-hub.php"
UA = {"User-Agent": "Mozilla/5.0"}

# 1. 抓 PDF 链接
html = requests.get(HUB, headers=UA, timeout=60).text
hrefs = sorted(set(re.findall(r'href="(/media/native/tournaments/fifa-world-cup/2026/[^"]+\.pdf)"', html)))
print(f"发现 {len(hrefs)} 份 PMSR PDF")

DIST = re.compile(r"([\d.]+)\s*km\s*Total Distance Covered\s*([\d.]+)\s*km")
ZONE4 = re.compile(r"([\d.]+)\s*km\s*Zone 4[^\n]*?([\d.]+)\s*km")
FNPAIR = re.compile(r"M\d+[ _-]+([A-Z]{3})[ _-]+[Vv][ _-]+([A-Z]{3})")  # 分隔符 V/v 皆可
# FIFA 三字码 -> 本项目 df 队名(48 队)
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

def process(href):
    fname = href.split("/")[-1]
    mno = re.search(r"M(\d+)", fname); mno = int(mno.group(1)) if mno else None
    pair = FNPAIR.search(fname)
    home = CODE2NAME.get(pair.group(1)) if pair else None
    away = CODE2NAME.get(pair.group(2)) if pair else None
    fn = SC / fname.replace(" ", "_")
    try:
        if not fn.exists() or fn.stat().st_size < 10000:
            r = requests.get(BASE + href.replace(" ", "%20"), headers=UA, timeout=120)
            r.raise_for_status()
            fn.write_bytes(r.content)
        with pdfplumber.open(fn) as pdf:      # 只读 page 2, 快
            p2 = pdf.pages[2].extract_text() or ""
        d = DIST.search(p2); z = ZONE4.search(p2)
        rec = {"match_no": mno, "file": fname, "home_pdf": home, "away_pdf": away,
               "home_dist_km": float(d.group(1)) if d else None,
               "away_dist_km": float(d.group(2)) if d else None,
               "home_sprint_km": float(z.group(1)) if z else None,
               "away_sprint_km": float(z.group(2)) if z else None, "err": ""}
    except Exception as e:
        rec = {"match_no": mno, "file": fname, "home_pdf": home, "away_pdf": away, "err": str(e)}
    finally:
        try: fn.unlink()
        except Exception: pass
    return rec

print("下载+解析中(72 份, 每份~5MB)...")
with ThreadPoolExecutor(max_workers=6) as ex:
    recs = list(ex.map(process, hrefs))
phys = pd.DataFrame(recs).sort_values("match_no")
ok = phys.home_dist_km.notna().sum()
print(f"成功解析总距离: {ok}/{len(phys)}")
bad = phys[phys.home_dist_km.isna()]
if len(bad): print("解析失败:\n", bad[["match_no","file","err"]].to_string())
phys.to_csv(ROOT / "out/fifa_physical.csv", index=False)

# 2. join 天气表(按球队集合)。先做名称归一。
wx = pd.read_csv(ROOT / "out/matches_weather_halves.csv")
ALIAS = {"Korea Republic": "South Korea", "IR Iran": "Iran", "USA": "United States",
         "Côte d'Ivoire": "Ivory Coast", "Czechia": "Czech Republic",
         "Cape Verde Islands": "Cape Verde", "China PR": "China"}
def norm(n):
    if not isinstance(n, str): return n
    return ALIAS.get(n.strip(), n.strip())
phys["home_n"] = phys.home_pdf.map(norm); phys["away_n"] = phys.away_pdf.map(norm)
phys["teamset"] = phys.apply(lambda r: frozenset([r.home_n, r.away_n]) if r.home_n and r.away_n else None, axis=1)
wx["teamset"] = wx.apply(lambda r: frozenset([r.home_team, r.away_team]), axis=1)

# 合计双方: 总跑动 & 冲刺距离(队级最稳指标)
phys["combined_dist_km"] = phys.home_dist_km + phys.away_dist_km
phys["combined_sprint_km"] = phys.home_sprint_km + phys.away_sprint_km
m = wx.merge(phys[["teamset","match_no","home_dist_km","away_dist_km",
                   "combined_dist_km","combined_sprint_km","home_n","away_n"]],
             on="teamset", how="left")
matched = m.combined_dist_km.notna().sum()
print(f"\njoin 天气表: {matched}/{len(wx)} 场匹配上 FIFA 体能(仅小组赛有,预期~72)")
unmatched = phys[phys.teamset.notna() & ~phys.teamset.isin(wx.teamset)]
if len(unmatched): print("PDF 队名未匹配(可能需加 alias):\n", unmatched[["match_no","home_pdf","away_pdf"]].to_string())

m.to_csv(ROOT / "out/matches_weather_physical.csv", index=False)
print(f"[done] -> out/matches_weather_physical.csv")
print(m[m.combined_dist_km.notna()][["home_team","away_team","temp_c","combined_dist_km","combined_sprint_km"]].head(8).to_string())
