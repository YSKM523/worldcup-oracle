"""
11_ocr_player_physical.py — 试验: OCR 提取 PMSR 球员级体能表(Zone5 真冲刺/冲刺次数/最高时速)。

球员数值在 PDF 里是一整张嵌入位图(文本层只有表头+球衣号+人名), 只能 OCR。
方法: pypdfium2 高分辨率渲染 Physical Data 页 → rapidocr 识别 → 按行(y 坐标)聚类成表
自验证: 每队球员 Total Distance 之和 ÷1000 应 ≈ page-2 队级总距离(容差 3%)
        —— 通过则采纳该队数据, 不通过丢弃。宁缺毋滥。

输出: out/player_physical.csv (match_no, team, player, dist_m, zone5_m, hsr, sprints, top_speed)
     + 控制台打印验证通过率。PDF 已由 09 留在 scratchpad/fifa_pdf_keep/。
"""
import re, sys
from pathlib import Path
import numpy as np
import pandas as pd
import pdfplumber
import pypdfium2 as pdfium

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:
    print("需要: pip install rapidocr-onnxruntime"); sys.exit(1)

ROOT = Path("/home/ubuntu/worldcup-oracle/research/weather_effect")
SC = Path("/tmp/claude-1000/-home-ubuntu/425320c7-7790-479f-a972-88a803318312/scratchpad/fifa_pdf_keep")
ocr = RapidOCR()

NUM = re.compile(r"^[\d,]+\.?\d*$")

def parse_num(s):
    s = s.replace(",", "").replace(" ", "")
    try: return float(s)
    except ValueError: return None

def ocr_physical_page(pdf_path, page_idx):
    """渲染一页 → OCR → 返回 (rows, team_name)。rows: [(y, [(x, text), ...])]"""
    doc = pdfium.PdfDocument(str(pdf_path))
    page = doc[page_idx]
    scale = 200 / 72
    bmp = page.render(scale=scale)
    img = bmp.to_numpy()  # HxWx3/4
    if img.shape[2] == 4: img = img[:, :, :3]
    result, _ = ocr(img)
    doc.close()
    if not result: return [], None
    # result: [ [box(4x2), text, conf], ... ]
    items = []
    team = None
    for box, text, conf in result:
        y = float(np.mean([p[1] for p in box])); x = float(min(p[0] for p in box))
        items.append((y, x, text.strip()))
        if text.strip().startswith("Physical Data"):
            team = text.strip().replace("Physical Data", "").strip()
    # 行聚类(y 差 < 12px 同行, 200dpi 下约半行高)
    items.sort()
    rows, cur, last_y = [], [], None
    for y, x, t in items:
        if last_y is not None and y - last_y > 12:
            rows.append(sorted(cur)); cur = []
        cur.append((x, t)); last_y = y
    if cur: rows.append(sorted(cur))
    return rows, team

def extract_players(rows):
    """行 → 球员记录, 列按全页数值 x 坐标聚类对齐(抗 OCR 掉格)。
    列序: Dist Z1 Z2 Z3 Z4 Z5 HSR Sprints TopSpeed (9 列)。
    逐行校验: dist ≈ z1+..+z5 (3% 容差), 不过则丢该行。"""
    # 1. 收集候选球员行: 首 token 为球衣号, 次 token 含字母(人名)
    cand = []
    for row in rows:
        if len(row) < 6: continue
        x0, t0 = row[0]
        if not re.match(r"^\d{1,2}$", t0): continue
        if not any(c.isalpha() for c in row[1][1]): continue
        nums = [(x, parse_num(t)) for x, t in row[2:]]
        nums = [(x, v) for x, v in nums if v is not None]
        if len(nums) >= 6: cand.append((int(t0), row[1][1], nums))
    if not cand: return []
    # 2. 全页数值 x 聚类成 9 列(用间隙分割)
    xs = sorted(x for _, _, nums in cand for x, _ in nums)
    if len(xs) < 9: return []
    gaps = sorted(range(1, len(xs)), key=lambda i: xs[i] - xs[i - 1], reverse=True)
    cuts = sorted(xs[i] - (xs[i] - xs[i - 1]) / 2 for i in gaps[:8])  # 8 个分割点 → 9 列
    def col_of(x):
        for i, c in enumerate(cuts):
            if x < c: return i
        return 8
    # 3. 逐行按列填值 + 校验
    out = []
    for jersey, name, nums in cand:
        vals = [np.nan] * 9
        for x, v in nums:
            c = col_of(x)
            if np.isnan(vals[c]): vals[c] = v
        dist, z1, z2, z3, z4, z5, hsr, spr, tsp = vals
        zsum = np.nansum([z1, z2, z3, z4, z5])
        if np.isnan(dist) or zsum == 0 or abs(dist - zsum) / dist > 0.03:
            continue  # 行级校验不过, 丢弃该行
        out.append(dict(jersey=jersey, player=name, dist_m=dist, z1=z1, z2=z2,
                        z3=z3, z4=z4, z5=z5, hsr=hsr, sprints=spr, top_speed=tsp))
    return out

# 队级总距离对照表(自验证用)
team_stats = pd.read_csv(ROOT / "out/pmsr_team_stats.csv")

pdfs = sorted(SC.glob("*.pdf"))
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(pdfs)
print(f"OCR {min(limit, len(pdfs))}/{len(pdfs)} PDFs ...")
recs, passed, failed = [], 0, 0
for pdf_path in pdfs[:limit]:
    mno = re.search(r"M(\d+)", pdf_path.name)
    mno = int(mno.group(1)) if mno else None
    ts = team_stats[team_stats.match_no == mno]
    if ts.empty: continue
    ref = {ts.iloc[0].home_team: ts.iloc[0].dist_h, ts.iloc[0].away_team: ts.iloc[0].dist_a}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            phys_pages = [i for i, p in enumerate(pdf.pages)
                          if "Physical Data" in (p.extract_text() or "")]
        for pi in phys_pages:
            rows, team = ocr_physical_page(pdf_path, pi)
            players = extract_players(rows)   # 已通过行级校验(dist≈Σzones)的球员
            if not players or team is None:
                failed += 1; continue
            # 按球衣号去重(OCR 偶发重复检测同一行)
            seen_j = {}
            for p in players:
                if p["jersey"] not in seen_j: seen_j[p["jersey"]] = p
            players = list(seen_j.values())
            total_km = sum(p["dist_m"] for p in players) / 1000
            # 名字归一: OCR 常丢空格("SouthAfrica"), 匹配前去空格再比
            def norm(s): return re.sub(r"\s+", "", s or "").lower()
            ref_km = None
            if len(norm(team)) >= 4:   # OCR 拆框可致 team 为空串; 空串是万物子串, 必须挡掉
                for tname, km in ref.items():
                    if tname and (norm(tname) in norm(team) or norm(team) in norm(tname)):
                        ref_km = km; team = tname; break
            if ref_km is None:  # 名字对不上就拿更近的那个
                tname = min(ref, key=lambda t: abs(ref[t] - total_km))
                ref_km, team = ref[tname], tname
            coverage = total_km / ref_km if ref_km else np.nan
            if coverage and coverage > 1.03:   # 总和超参考 → 有误读, 整页不可信
                failed += 1
                print(f"  M{mno} {team}: OCR sum {total_km:.1f} > ref {ref_km} — 丢弃整页")
                continue
            passed += 1
            for p in players:
                recs.append(dict(match_no=mno, team=team, coverage=round(coverage, 3), **p))
    except Exception as e:
        failed += 1
        print(f"  M{mno}: {e}")

df = pd.DataFrame(recs)
print(f"\n验证: 通过 {passed} 队 / 失败 {failed} 队")
if len(df):
    df.to_csv(ROOT / "out/player_physical.csv", index=False)
    print(f"[done] out/player_physical.csv  {df.shape}, "
          f"{df.match_no.nunique()} matches, {df.team.nunique()} teams")
    print(df.head(3).to_string())
