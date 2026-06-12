import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WorldCup Oracle · 2026 世界杯 AI 预测",
  description:
    "三个时序基础模型 + Elo + 5 万次蒙特卡洛：逐场预测 2026 世界杯胜平负与比分，并对比 Polymarket 市场赔率。",
  icons: {
    icon: "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><rect width='24' height='24' rx='5' fill='%2309090b'/><circle cx='12' cy='12' r='7.25' fill='none' stroke='%2334d399' stroke-width='1.6'/><path d='M12 7.6l3 2.2-1.15 3.5h-3.7L9 9.8z' fill='%2334d399'/></svg>",
  },
};

export const viewport: Viewport = {
  themeColor: "#09090b",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="bg-zinc-950 text-zinc-100 antialiased">{children}</body>
    </html>
  );
}
