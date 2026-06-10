/* WorldCup Oracle dashboard */
"use strict";

const ZH = {
  "Mexico": "墨西哥", "South Korea": "韩国", "Czech Republic": "捷克", "South Africa": "南非",
  "United States": "美国", "Turkey": "土耳其", "Australia": "澳大利亚", "Paraguay": "巴拉圭",
  "Canada": "加拿大", "Switzerland": "瑞士", "Bosnia and Herzegovina": "波黑", "Qatar": "卡塔尔",
  "Brazil": "巴西", "Morocco": "摩洛哥", "Scotland": "苏格兰", "Haiti": "海地",
  "Germany": "德国", "Ivory Coast": "科特迪瓦", "Ecuador": "厄瓜多尔", "Curaçao": "库拉索",
  "Netherlands": "荷兰", "Japan": "日本", "Sweden": "瑞典", "Tunisia": "突尼斯",
  "Belgium": "比利时", "Iran": "伊朗", "Egypt": "埃及", "New Zealand": "新西兰",
  "Spain": "西班牙", "Uruguay": "乌拉圭", "Saudi Arabia": "沙特阿拉伯", "Cape Verde": "佛得角",
  "Argentina": "阿根廷", "Algeria": "阿尔及利亚", "Austria": "奥地利", "Jordan": "约旦",
  "France": "法国", "Senegal": "塞内加尔", "Iraq": "伊拉克", "Norway": "挪威",
  "Portugal": "葡萄牙", "Colombia": "哥伦比亚", "Uzbekistan": "乌兹别克斯坦", "DR Congo": "刚果(金)",
  "England": "英格兰", "Croatia": "克罗地亚", "Ghana": "加纳", "Panama": "巴拿马",
};
const FLAG = {
  "Mexico": "🇲🇽", "South Korea": "🇰🇷", "Czech Republic": "🇨🇿", "South Africa": "🇿🇦",
  "United States": "🇺🇸", "Turkey": "🇹🇷", "Australia": "🇦🇺", "Paraguay": "🇵🇾",
  "Canada": "🇨🇦", "Switzerland": "🇨🇭", "Bosnia and Herzegovina": "🇧🇦", "Qatar": "🇶🇦",
  "Brazil": "🇧🇷", "Morocco": "🇲🇦", "Scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "Haiti": "🇭🇹",
  "Germany": "🇩🇪", "Ivory Coast": "🇨🇮", "Ecuador": "🇪🇨", "Curaçao": "🇨🇼",
  "Netherlands": "🇳🇱", "Japan": "🇯🇵", "Sweden": "🇸🇪", "Tunisia": "🇹🇳",
  "Belgium": "🇧🇪", "Iran": "🇮🇷", "Egypt": "🇪🇬", "New Zealand": "🇳🇿",
  "Spain": "🇪🇸", "Uruguay": "🇺🇾", "Saudi Arabia": "🇸🇦", "Cape Verde": "🇨🇻",
  "Argentina": "🇦🇷", "Algeria": "🇩🇿", "Austria": "🇦🇹", "Jordan": "🇯🇴",
  "France": "🇫🇷", "Senegal": "🇸🇳", "Iraq": "🇮🇶", "Norway": "🇳🇴",
  "Portugal": "🇵🇹", "Colombia": "🇨🇴", "Uzbekistan": "🇺🇿", "DR Congo": "🇨🇩",
  "England": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "Croatia": "🇭🇷", "Ghana": "🇬🇭", "Panama": "🇵🇦",
};
const STAGE_ZH = {
  group: "小组赛", r32: "32 强", r16: "16 强", qf: "1/4 决赛",
  sf: "半决赛", third: "季军赛", final: "决赛",
};
const KO_STAGES = new Set(["r32", "r16", "qf", "sf", "third", "final"]);
const MODEL_SHORT = { "Chronos-2": "Chronos", "TimesFM-2.5": "TimesFM", "FlowState": "FlowState", "Actual-Elo": "Elo" };
const ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=";

let DATA = null;
let live = {};            // espn_id -> {state, status, home_score, away_score, clock, completed, winner_home}
let filter = "upcoming";
let search = "";

const $ = (sel) => document.querySelector(sel);

function zh(name) {
  if (ZH[name]) return ZH[name];
  let m;
  if ((m = name.match(/^Group ([A-L]) Winner$/))) return `${m[1]} 组第一`;
  if ((m = name.match(/^Group ([A-L]) 2nd Place$/))) return `${m[1]} 组第二`;
  if ((m = name.match(/^Third Place Group (.+)$/))) return `小组第三 (${m[1]})`;
  if ((m = name.match(/^Round of 32 (\d+) Winner$/))) return `32 强第 ${m[1]} 场胜者`;
  if ((m = name.match(/^Round of 16 (\d+) Winner$/))) return `16 强第 ${m[1]} 场胜者`;
  if ((m = name.match(/^Quarterfinal (\d+) Winner$/))) return `1/4 决赛第 ${m[1]} 场胜者`;
  if ((m = name.match(/^Semifinal (\d+) Winner$/))) return `半决赛第 ${m[1]} 场胜者`;
  if ((m = name.match(/^Semifinal (\d+) Loser$/))) return `半决赛第 ${m[1]} 场负者`;
  return name;
}
const flag = (name) => FLAG[name] || "🔘";
const pct = (p, d = 0) => (p * 100).toFixed(d) + "%";

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
function localDateKey(iso) {
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function fmtDayHeader(key) {
  const [y, mo, da] = key.split("-").map(Number);
  const d = new Date(y, mo - 1, da);
  const wd = "日一二三四五六"[d.getDay()];
  return `${mo} 月 ${da} 日 · 周${wd}`;
}
const todayKey = () => localDateKey(new Date().toISOString());

/* ── Rendering: matches ─────────────────────────────────────────── */
function teamHTML(name, side, loser) {
  return `<div class="team ${side}${loser ? " loser" : ""}">
    <span class="flag">${flag(name)}</span><span class="name">${zh(name)}</span></div>`;
}

function midHTML(m) {
  const lv = live[m.espn_id];
  if (lv && lv.state === "in") {
    return `<div class="score-mid">
      <div class="big">${lv.home_score} - ${lv.away_score}</div>
      <div class="live-now"><span class="live-dot"></span>${lv.clock || "进行中"}</div></div>`;
  }
  const fin = m.completed ? m : (lv && lv.completed ? lv : null);
  if (fin) {
    return `<div class="score-mid"><div class="big">${fin.home_score} - ${fin.away_score}</div>
      <div class="pred-tag">完场</div></div>`;
  }
  const score = m.pred ? `<div class="pred-tag">预测 ${m.pred.scoreline.most_likely}</div>` : "";
  return `<div class="score-mid"><div class="ko-time">${fmtTime(m.kickoff_utc)}</div>${score}</div>`;
}

function probBarHTML(p) {
  const seg = (cls, v, label) =>
    `<div class="seg ${cls}" style="width:${(v * 100).toFixed(1)}%">${v >= 0.12 ? label : ""}</div>`;
  return `<div class="prob-bar">
      ${seg("h", p.p_home, "胜 " + pct(p.p_home))}
      ${seg("d", p.p_draw, "平 " + pct(p.p_draw))}
      ${seg("a", p.p_away, "负 " + pct(p.p_away))}
    </div>
    <div class="prob-labels"><span>主胜 ${pct(p.p_home)}</span><span>平 ${pct(p.p_draw)}</span><span>客胜 ${pct(p.p_away)}</span></div>`;
}

function advBarHTML(p) {
  return `<div class="prob-bar">
      <div class="seg h" style="width:${(p.p_adv_home * 100).toFixed(1)}%">晋级 ${pct(p.p_adv_home)}</div>
      <div class="seg a" style="width:${(p.p_adv_away * 100).toFixed(1)}%">晋级 ${pct(p.p_adv_away)}</div>
    </div>
    <div class="prob-labels"><span>90 分钟：胜 ${pct(p.p_home)} / 平 ${pct(p.p_draw)} / 负 ${pct(p.p_away)}</span></div>`;
}

function predBlockHTML(m) {
  const p = m.pred;
  if (!p) return "";
  const alts = p.scoreline.top_scores.slice(1, 4)
    .map((s) => `${s.score} ${pct(s.p)}`).join(" · ");
  const models = DATA.meta.models.map((name, i) =>
    `${MODEL_SHORT[name] || name} ${pct(p.per_model[i].p_home)}`).join(" · ");
  return `${KO_STAGES.has(m.stage) ? advBarHTML(p) : probBarHTML(p)}
    <div class="score-pred">比分预测：<b>${p.scoreline.most_likely}</b>（${pct(p.scoreline.most_likely_p, 1)}）　其他：${alts}</div>
    <div class="model-row">主胜率分歧 — ${models}　|　Elo ${p.elo_home} vs ${p.elo_away}</div>`;
}

function resultBlockHTML(m) {
  const lk = m.locked;
  if (!lk) return `<div class="tbd-note">该场无赛前预测存档</div>`;
  let outcome, hit;
  if (KO_STAGES.has(m.stage)) {
    const side = lk.p_home >= lk.p_away ? m.home : m.away;
    outcome = `赛前预测晋级方：${zh(side)}（${pct(Math.max(lk.p_home, lk.p_away))}）`;
    hit = m.winner === side;
  } else {
    const probs = [["主胜", lk.p_home, m.home_score > m.away_score],
                   ["平局", lk.p_draw, m.home_score === m.away_score],
                   ["客胜", lk.p_away, m.home_score < m.away_score]];
    probs.sort((a, b) => b[1] - a[1]);
    outcome = `赛前预测：${probs[0][0]}（${pct(probs[0][1])}）`;
    hit = probs[0][2];
  }
  const scorePart = lk.pred_score
    ? `　比分预测 ${lk.pred_score} <span class="${lk.pred_score === m.home_score + "-" + m.away_score ? "hit" : "miss"}">${lk.pred_score === m.home_score + "-" + m.away_score ? "命中 ✓" : "未中"}</span>`
    : "";
  const brier = lk.brier != null ? `　Brier ${lk.brier.toFixed(3)}` : "";
  return `<div class="result-line">${outcome} <span class="${hit ? "hit" : "miss"}">${hit ? "判对 ✓" : "判错 ✗"}</span>${scorePart}${brier}</div>`;
}

function matchCardHTML(m) {
  const stageLabel = m.stage === "group" && m.group
    ? `小组赛 · ${m.group} 组` : (STAGE_ZH[m.stage] || m.stage);
  const venue = [m.venue, m.city].filter(Boolean).join(" · ");
  const fin = m.completed || (live[m.espn_id] && live[m.espn_id].completed);
  const lv = live[m.espn_id];
  let homeLoser = false, awayLoser = false;
  if (m.completed && m.home_score !== m.away_score) {
    homeLoser = m.home_score < m.away_score;
    awayLoser = !homeLoser;
  } else if (m.completed && m.winner) {
    homeLoser = m.winner !== m.home; awayLoser = m.winner === m.home;
  }
  let body;
  if (m.tbd) body = `<div class="tbd-note">对阵待定 — 等待前序比赛结果</div>`;
  else if (m.completed) body = resultBlockHTML(m);
  else if (fin && lv) body = m.pred ? predBlockHTML(m) + `<div class="tbd-note">刚刚完场 — 明早 06:00 UTC 跑批后计入战绩</div>` : "";
  else body = predBlockHTML(m);
  return `<div class="match-card" data-id="${m.espn_id}">
    <div class="match-top"><span class="stage-badge">${stageLabel}</span><span class="venue">${venue}</span></div>
    <div class="match-teams">
      ${teamHTML(m.home, "home", homeLoser)}
      ${midHTML(m)}
      ${teamHTML(m.away, "away", awayLoser)}
    </div>
    ${body}</div>`;
}

function matchVisible(m) {
  if (search) {
    const hay = `${m.home} ${m.away} ${zh(m.home)} ${zh(m.away)}`.toLowerCase();
    if (!hay.includes(search)) return false;
  }
  const lv = live[m.espn_id];
  const finished = m.completed || (lv && lv.completed);
  switch (filter) {
    case "upcoming": return !finished;
    case "today": return localDateKey(m.kickoff_utc) === todayKey();
    case "group": return m.stage === "group";
    case "ko": return KO_STAGES.has(m.stage);
    case "done": return finished;
    default: return true;
  }
}

function renderMatches() {
  const list = $("#match-list");
  const visible = DATA.matches.filter(matchVisible);
  if (!visible.length) {
    list.innerHTML = `<div class="empty-note">没有符合条件的比赛</div>`;
    return;
  }
  let html = "", lastDay = "";
  for (const m of visible) {
    const day = localDateKey(m.kickoff_utc);
    if (day !== lastDay) {
      const isToday = day === todayKey();
      html += `<div class="day-header${isToday ? " today" : ""}">${fmtDayHeader(day)}${isToday ? "（今天）" : ""}</div>`;
      lastDay = day;
    }
    html += matchCardHTML(m);
  }
  list.innerHTML = html;
}

/* ── Groups ─────────────────────────────────────────────────────── */
function renderGroups() {
  const grid = $("#group-grid");
  grid.innerHTML = Object.entries(DATA.groups).map(([g, rows]) => `
    <div class="group-card"><h3>${g} 组</h3>
    <table><tr><th>球队</th><th>赛</th><th>胜平负</th><th>净</th><th>分</th><th>出线%</th></tr>
    ${rows.map((r) => `<tr>
      <td class="t">${flag(r.team)} ${zh(r.team)}</td>
      <td>${r.played}</td><td>${r.w}-${r.d}-${r.l}</td>
      <td>${r.gd > 0 ? "+" : ""}${r.gd}</td><td><b>${r.pts}</b></td>
      <td class="${r.p_advance >= 0.5 ? "adv" : ""}">${pct(r.p_advance)}</td></tr>`).join("")}
    </table></div>`).join("");
}

/* ── Champions ──────────────────────────────────────────────────── */
let champExpanded = false;
function renderChampions() {
  const meta = DATA.meta;
  $("#champ-legend").innerHTML =
    `<span style="color:var(--home)">■</span> AI 集成概率　<span style="color:var(--draw)">■</span> Polymarket 市场` +
    (meta.volume ? `（总量 $${(meta.volume / 1e9).toFixed(2)}B）` : "") +
    `　·　点击行展开模型明细`;
  const rows = DATA.champions.filter((c) => c.ai > 0.0005 || c.market > 0.0005);
  const shown = champExpanded ? rows : rows.slice(0, 20);
  const maxP = Math.max(shown[0]?.ai || 0.01, shown[0]?.market || 0.01);
  $("#champ-list").innerHTML = shown.map((c, i) => {
    const e = c.edge;
    const badge = e
      ? `<span class="edge-badge ${e.direction === "BUY" ? "buy" : "sell"}">${e.strength === "STRONG EDGE" ? "★" : ""}${e.direction === "BUY" ? "低估" : "高估"} ${e.edge_pct > 0 ? "+" : ""}${e.edge_pct.toFixed(1)}</span>`
      : "";
    const models = Object.entries(c.per_model)
      .map(([mn, p]) => `${MODEL_SHORT[mn] || mn} ${pct(p, 1)}`).join(" · ");
    const stages = c.stages;
    return `<div class="champ-row" data-i="${i}">
      <div class="champ-main">
        <span class="champ-rank">${i + 1}</span>
        <span class="champ-team">${flag(c.team)} ${zh(c.team)}${badge}</span>
        <span class="champ-nums"><span class="ai-n">${pct(c.ai, 1)}</span> / <span class="mkt-n">${pct(c.market, 1)}</span></span>
      </div>
      <div class="champ-bars">
        <div class="champ-bar-bg"><div class="fill-ai" style="width:${Math.min(100, c.ai / maxP * 100)}%"></div></div>
        <div class="champ-bar-bg"><div class="fill-mkt" style="width:${Math.min(100, c.market / maxP * 100)}%"></div></div>
      </div>
      <div class="champ-detail" hidden>
        各模型夺冠概率：${models || "—"}
        <div class="stage-probs">
          <span>出线 ${pct(stages.advance)}</span><span>16 强 ${pct(stages.r16)}</span>
          <span>8 强 ${pct(stages.qf)}</span><span>4 强 ${pct(stages.sf)}</span>
          <span>决赛 ${pct(stages.final)}</span><span>夺冠 ${pct(stages.champion, 1)}</span>
        </div>
        ${e ? `<div style="margin-top:6px">vs 市场：${e.direction === "BUY" ? "AI 认为被低估" : "AI 认为被高估"} ${Math.abs(e.edge_pct).toFixed(1)} 个百分点（${e.models_agree}/${DATA.meta.models.length} 模型同向${e.half_kelly > 0 ? `，半凯利仓位 ${pct(e.half_kelly, 1)}` : ""}）</div>` : ""}
      </div></div>`;
  }).join("") + (rows.length > 20 && !champExpanded
    ? `<button class="chip" id="champ-more" style="margin:6px auto;display:block">显示全部 ${rows.length} 队</button>` : "");

  document.querySelectorAll(".champ-row").forEach((el) =>
    el.addEventListener("click", () => {
      const d = el.querySelector(".champ-detail");
      d.hidden = !d.hidden;
    }));
  const more = $("#champ-more");
  if (more) more.addEventListener("click", (ev) => {
    ev.stopPropagation(); champExpanded = true; renderChampions();
  });
}

/* ── Record ─────────────────────────────────────────────────────── */
function renderRecord() {
  const p = DATA.performance;
  const cards = [];
  if (p.details.length) {
    cards.push([`${(p.winner_hit_rate * 100).toFixed(0)}%`, `胜平负判对率（${p.details.length} 场）`]);
    if (p.n_score_preds > 0)
      cards.push([`${p.score_hits}/${p.n_score_preds}`, "精确比分命中"]);
    if (p.mean_brier != null)
      cards.push([p.mean_brier.toFixed(3), "平均 Brier（瞎猜 ≈ 0.667）"]);
  }
  if (p.scoreboard) {
    const s = p.scoreboard;
    cards.push([s.leader === "AI" ? "AI 领先" : "市场领先",
      `冠军盘 Brier：AI ${s.ai_brier} vs 市场 ${s.pm_brier}（${s.n_teams} 队已淘汰）`]);
  }
  $("#record-summary").innerHTML = cards.length
    ? cards.map(([v, l], i) => `<div class="sum-card${i === cards.length - 1 && p.scoreboard ? " lead-ai" : ""}"><div class="val">${v}</div><div class="lbl">${l}</div></div>`).join("")
    : "";
  $("#record-details").innerHTML = p.details.length
    ? `<table class="record-table"><tr><th>对阵</th><th>比分</th><th>预测</th><th>判定</th><th>Brier</th></tr>
      ${p.details.map((d) => {
        const pm = [["主胜", d.p_home], ["平", d.p_draw], ["客胜", d.p_away]].sort((a, b) => b[1] - a[1])[0];
        return `<tr><td>${flag(d.home)} ${zh(d.home)} vs ${zh(d.away)} ${flag(d.away)}</td>
        <td><b>${d.score}</b></td>
        <td>${pm[0]} ${pct(pm[1])}${d.pred_score ? `<br>比分 ${d.pred_score}` : ""}</td>
        <td class="${d.winner_hit ? "hit" : "miss"}">${d.winner_hit ? "✓" : "✗"}${d.score_hit ? " 比分✓" : ""}</td>
        <td>${d.brier != null ? d.brier.toFixed(3) : "—"}</td></tr>`;
      }).join("")}</table>`
    : `<div class="empty-note">还没有已完赛的预测 — 等第一场比赛打完就有了 ⚽</div>`;
}

/* ── Live scores (client-side ESPN, CORS-open) ──────────────────── */
async function refreshLive() {
  const now = new Date();
  const dates = [0, -1].map((off) => {
    const d = new Date(now.getTime() + off * 86400e3);
    return d.toISOString().slice(0, 10).replace(/-/g, "");
  });
  let anyLive = false;
  try {
    const results = await Promise.all(dates.map((d) =>
      fetch(ESPN_URL + d).then((r) => r.json()).catch(() => null)));
    for (const res of results) {
      if (!res || !res.events) continue;
      for (const ev of res.events) {
        const comp = ev.competitions && ev.competitions[0];
        if (!comp) continue;
        const home = comp.competitors.find((c) => c.homeAway === "home") || comp.competitors[0];
        const away = comp.competitors.find((c) => c.homeAway === "away") || comp.competitors[1];
        const state = ev.status.type.state; // pre | in | post
        live[String(ev.id)] = {
          state,
          completed: !!ev.status.type.completed,
          home_score: Number(home.score || 0),
          away_score: Number(away.score || 0),
          clock: state === "in" ? (ev.status.displayClock || "") : "",
        };
        if (state === "in") anyLive = true;
      }
    }
  } catch (e) { /* offline — keep static data */ }
  if (!$("#tab-matches").hidden) renderMatches();
  setTimeout(refreshLive, anyLive ? 60e3 : 5 * 60e3);
}

/* ── Meta + tabs + boot ─────────────────────────────────────────── */
function renderMeta() {
  const m = DATA.meta;
  const t = new Date(m.generated_at).toLocaleString("zh-CN", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
  $("#meta-box").innerHTML =
    `预测更新：${t}<br>已赛 ${m.n_completed}/${m.n_matches} 场` +
    (m.volume ? `<br>市场总量 <span class="vol">$${(m.volume / 1e9).toFixed(2)}B</span>` : "");
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".tab-panel").forEach((p) => (p.hidden = true));
      $(`#tab-${btn.dataset.tab}`).hidden = false;
    }));
  document.querySelectorAll("#stage-chips .chip").forEach((chip) =>
    chip.addEventListener("click", () => {
      document.querySelectorAll("#stage-chips .chip").forEach((c) => c.classList.toggle("active", c === chip));
      filter = chip.dataset.filter;
      renderMatches();
    }));
  $("#team-search").addEventListener("input", (e) => {
    search = e.target.value.trim().toLowerCase();
    renderMatches();
  });
}

async function boot() {
  const res = await fetch(`data.json?v=${Math.floor(Date.now() / 3600e3)}`);
  DATA = await res.json();
  renderMeta();
  setupTabs();
  renderMatches();
  renderGroups();
  renderChampions();
  renderRecord();
  refreshLive();
}
boot();
