"use client";

import type { WeatherData } from "@/lib/types";

/* ── 天气研究视图：六角度结论 + 图表 + 实验性修正说明 ───────────── */

function Stat({ label, value, sub, tone = "zinc" }: {
  label: string; value: string; sub?: string; tone?: "emerald" | "rose" | "amber" | "zinc";
}) {
  const toneCls = {
    emerald: "text-emerald-400", rose: "text-rose-400",
    amber: "text-amber-300", zinc: "text-zinc-200",
  }[tone];
  return (
    <div className="rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4">
      <div className="text-[11px] text-zinc-500">{label}</div>
      <div className={`mt-1 text-lg font-bold tabular-nums ${toneCls}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-4 text-zinc-500">{sub}</div>}
    </div>
  );
}

function Verdict({ ok, children }: { ok: boolean | null; children: React.ReactNode }) {
  const mark = ok === true ? "✅" : ok === false ? "❌" : "⚠️";
  return (
    <li className="flex gap-2 text-[13px] leading-6 text-zinc-300">
      <span className="shrink-0">{mark}</span>
      <span>{children}</span>
    </li>
  );
}

const FIGS: [string, string][] = [
  ["fig6_physical.png", "★ 双方合计跑动/低速冲刺 vs 开球气温（71 场小组赛，FIFA 官方数据）"],
  ["fig7_altitude_control.png", "海拔混杂复核：按海拔着色 + 城市固定效应残差"],
  ["fig2_upset_by_temp.png", "爆冷率按温度分桶（95% Wilson CI）——不显著"],
  ["fig1_goals_vs_temp.png", "总进球 vs 气温——零相关"],
  ["fig5_fatigue.png", "下半场进球占比 / 75'+ 进球 vs 温度——「体能崩盘」不成立"],
  ["fig3_daypart.png", "开球时段：进球与温度"],
  ["fig4_brier_vs_humidity.png", "模型 Brier vs 湿度——无关"],
];

export function WeatherLabView({ wx }: { wx: WeatherData }) {
  const s = wx.study;
  const a = wx.adjust;
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-bold">天气 × 世界杯：六角度研究</h2>
        <p className="mt-1 text-xs leading-5 text-zinc-500">
          基于 {s.n_matches} 场已完赛比赛 × Open-Meteo 逐小时天气 × FIFA 官方跑动数据（{s.n_physical} 场小组赛）。
          置换检验 + Wilson CI，固定种子可复现。
        </p>
      </div>

      {/* 核心发现 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="★ 体感温度 → 合计跑动" tone="emerald"
          value={`ρ=${s.dist_vs_apparent.rho}`}
          sub={`p=${s.dist_vs_apparent.p} · 47 个检验中唯一过 Bonferroni 校正`} />
        <Stat label="每 +1°C 双方合计少跑" tone="emerald"
          value={`${Math.abs(s.slope_km_per_degC).toFixed(1)} km`}
          sub="16→33°C 约少跑 10 km；扣比赛节奏后仍显著" />
        <Stat label="低速冲刺 (Zone 4) vs 气温" tone="zinc"
          value={`ρ=${s.sprint_vs_temp.rho}`}
          sub={`p=${s.sprint_vs_temp.p}——耐力掉、高速输出保住`} />
        <Stat label="酷热场 (≥27°C) 爆冷率" tone="amber"
          value={`${Math.round((s.upset_buckets["hot(>=27)"]?.upset_rate ?? 0) * 100)}%`}
          sub={`vs 其余约 33%，但 p=${s.upset_partial.p}——不显著`} />
      </div>

      {/* 一句话结论 */}
      <div className="rounded-r-xl border-l-2 border-emerald-500/70 bg-zinc-900/80 p-4 text-[13px] leading-6 text-zinc-300">
        <b>高温对球员身体有真实、可测量的影响，但这份「体能税」在抵达记分牌之前就被吸收掉了。</b>
        两队在同样的高温里一起变慢——比赛对称降速，强弱关系和进球结构基本不动。
        天气因此<b className="text-amber-300">不构成可用的预测因子</b>，官方预测不含天气修正。
      </div>

      {/* 六角度判词 */}
      <ul className="space-y-1.5 rounded-2xl border border-zinc-800/80 bg-zinc-900/40 p-4">
        <Verdict ok={true}>
          <b>体能层（角度⑥）</b>：体感温度 ↑ → 合计跑动显著 ↓（ρ={s.dist_vs_apparent.rho}, p={s.dist_vs_apparent.p}）；
          海拔混杂已复核——控海拔偏相关 r={s.altitude_partial.r}（p={s.altitude_partial.p}），
          剔除墨西哥城/瓜达拉哈拉后反而更强（r={s.altitude_excl_high.r}）
        </Verdict>
        <Verdict ok={null}>
          <b>爆冷（角度①④）</b>：酷热场爆冷偏多、favorite 略被高估，但扣实力后
          r={s.upset_partial.r}（p={s.upset_partial.p}）——只是方向线索，不显著
        </Verdict>
        <Verdict ok={false}>
          <b>进球数（角度②）</b>：与气温零相关（ρ={s.goals_vs_temp.rho}, p={s.goals_vs_temp.p}）
        </Verdict>
        <Verdict ok={false}>
          <b>下半场崩盘（角度⑤）</b>：进球时间未被高温推向下半场（ρ={s.h2_share_vs_temp.stat},
          p={s.h2_share_vs_temp.p}），凉爽场反而更「后置」
        </Verdict>
        <Verdict ok={false}>
          <b>开球时段 / 湿度（角度③）</b>：无信号
        </Verdict>
      </ul>

      {/* 实验性修正说明 */}
      <div className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-4">
        <div className="text-[13px] font-bold text-amber-300">🌡️ 天气实验室（实验性，不计入官方预测）</div>
        <p className="mt-1.5 text-xs leading-5 text-zinc-400">
          赛程卡片上的「天气实验室」行展示一个<b>实验性</b> favorite 概率修正：
          取角度④「favorite 校准残差 ~ 温度」的回归斜率（{a.slope_pp_per_degC} pp/°C，t={a.t_stat}，n={a.n}），
          经正部 James-Stein 收缩（×{a.shrink_factor}）后为 <b className="text-zinc-200">{a.slope_shrunk_pp_per_degC} pp/°C</b>，
          按开球温度偏离样本均温（{a.ref_temp_c}°C）计算，封顶 ±{a.cap_pp}pp。
          该效应<b>未达显著</b>（研究报告原文），收缩因子会随样本更新自动调整——若信号消失（|t|&lt;1），修正自动归零。
        </p>
      </div>

      {/* 图表 */}
      <div className="space-y-4">
        {FIGS.map(([f, cap]) => (
          <figure key={f} className="overflow-hidden rounded-2xl border border-zinc-800/80 bg-white">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/research/${f}`} alt={cap} className="w-full" loading="lazy" />
            <figcaption className="border-t border-zinc-200 bg-zinc-50 px-3 py-2 text-[11px] text-zinc-600">
              {cap}
            </figcaption>
          </figure>
        ))}
      </div>

      <p className="text-[11px] leading-5 text-zinc-600">
        完整方法、口径敏感性与局限见{" "}
        <a
          href="https://github.com/YSKM523/worldcup-oracle/blob/main/research/weather_effect/REPORT.md"
          target="_blank" rel="noopener noreferrer"
          className="text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
        >
          research/weather_effect/REPORT.md
        </a>
        。天气数据 Open-Meteo；跑动数据 FIFA Training Centre 官方赛后报告。探索性相关，非因果，不构成投注建议。
      </p>
    </div>
  );
}
