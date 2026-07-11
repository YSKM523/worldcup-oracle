import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WorldCup Oracle · 2026 世界杯盘口分析",
  description:
    "Polymarket 实时盘口去 vig + xG 条件化泊松：逐场给出 2026 世界杯市场隐含的胜平负与比分，并与三时序模型 + Elo + 5 万次蒙特卡洛的 AI 预测对照。",
};

export const viewport: Viewport = {
  themeColor: "#09090b",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
