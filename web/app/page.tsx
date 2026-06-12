"use client";

import { useEffect, useState } from "react";
import { LogoMark } from "@/components/icons";
import { ChampionsView, GroupsView, RecordView, ScheduleView } from "@/components/Views";
import type { Data } from "@/lib/types";
import { useLive } from "@/lib/useLive";
import { usePolymarket } from "@/lib/usePolymarket";

const TABS = [
  ["matches", "赛程预测"],
  ["groups", "小组积分"],
  ["champions", "夺冠概率"],
  ["record", "AI 战绩"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function Home() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState(false);
  const [tab, setTab] = useState<Tab>("matches");
  const live = useLive();
  const poly = usePolymarket(data?.matches ?? []);

  useEffect(() => {
    fetch(`/data.json?v=${Math.floor(Date.now() / 3600e3)}`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => setError(true));
  }, []);

  return (
    <div className="mx-auto min-h-dvh max-w-3xl px-4">
      <header className="sticky top-0 z-40 -mx-4 border-b border-zinc-800/70 bg-zinc-950/85 px-4 pt-5 backdrop-blur-md">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-bold tracking-tight">
              <LogoMark className="h-5 w-5 text-emerald-400" />
              WorldCup Oracle
            </h1>
            <p className="mt-0.5 text-xs text-zinc-500">2026 世界杯 · AI 预测 vs Polymarket</p>
          </div>
          {data && (
            <div className="hidden text-right text-[11px] leading-5 text-zinc-500 sm:block">
              预测更新{" "}
              {new Date(data.meta.generated_at).toLocaleString("zh-CN", {
                month: "numeric",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
              })}
              <br />
              已赛 {data.meta.n_completed}/{data.meta.n_matches} 场
              {data.meta.volume ? (
                <>
                  {" "}
                  · 市场 <span className="text-amber-300">
                    ${(data.meta.volume / 1e9).toFixed(2)}B
                  </span>
                </>
              ) : null}
            </div>
          )}
        </div>
        <nav className="mt-4 flex gap-1 overflow-x-auto pb-3">
          {TABS.map(([key, label]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`whitespace-nowrap rounded-full px-4 py-1.5 text-sm font-medium transition-colors ${
                tab === key
                  ? "bg-zinc-100 text-zinc-950"
                  : "text-zinc-500 hover:text-zinc-200"
              }`}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      <main className="py-6">
        {error ? (
          <p className="py-20 text-center text-sm text-zinc-600">数据加载失败，请稍后刷新重试</p>
        ) : !data ? (
          <p className="py-20 text-center text-sm text-zinc-600">加载中…</p>
        ) : tab === "matches" ? (
          <ScheduleView data={data} live={live} poly={poly} />
        ) : tab === "groups" ? (
          <GroupsView data={data} />
        ) : tab === "champions" ? (
          <ChampionsView data={data} poly={poly} />
        ) : (
          <RecordView data={data} />
        )}
      </main>

      <footer className="space-y-2 border-t border-zinc-800/70 py-6 text-[11px] leading-5 text-zinc-600">
        <p>
          模型：Chronos-2 / TimesFM-2.5 / FlowState 三个时序基础模型预测球队 Elo 走势 →
          Bradley-Terry(Davidson) 胜平负 → 50,000 次蒙特卡洛（已赛结果实时注入，只模拟剩余赛程）。
          比分为 Elo→泊松模型最可能比分。
        </p>
        <p>实时比分来自 ESPN 公开接口；市场概率来自 Polymarket。仅供研究娱乐，不构成任何投注建议。</p>
        <p>
          <a
            href="https://github.com/YSKM523/worldcup-oracle"
            target="_blank"
            rel="noopener noreferrer"
            className="text-zinc-500 underline-offset-2 hover:text-zinc-300 hover:underline"
          >
            GitHub · YSKM523/worldcup-oracle
          </a>
        </p>
      </footer>
    </div>
  );
}
