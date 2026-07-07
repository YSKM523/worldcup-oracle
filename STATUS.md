# worldcup (Oracle) — STATUS

> 世界杯 AI vs Polymarket 预测看板。Python pipeline + CF Pages 看板。
> 目录 `~/worldcup-oracle` · 线上 `worldcup-oracle.pages.dev`
> 部署：`python visualization/dashboard.py`（内部 `wrangler pages deploy`）
> 自动化 cron：每日 08:00 UTC `pipeline/daily_run.py`（Phase A）；赛日 06:00 UTC `pipeline/matchday_run.py`（6/11–30、7/1–20）

_最后更新：2026-07-06_

## 当前状态
- **2026-07-06 前端大改版（未 commit / 未部署）：移动优先窄栏 tab 站 → 单屏「控制室」看板（Mission Control）**。为 27/32 寸大屏设计，**一屏铺满不滚动**（实测 2560×1440 / 3840×2160 / 1920×1080 / 1440×900 均 0px 滚动溢出）；手机 <1280px 自动降级成可滚动单列堆叠。视觉=数据终端风（等宽 tabular 数字、发丝网格边框、角落 registration marks、01/02/03 分区索引、单一实时脉冲=WS 绿点+走时 UTC 时钟；**纯色无渐变**）。
  - 三栏布局：左 `01 AI PERFORMANCE`（KPI+近期战绩格+校准）· 中 `02 MATCHDAY` 焦点 hero 卡（概率条/比分候选/xG/模型分歧/盘口+edge/H2H/AI 短评）+ NEXT UP 后续淘汰赛 · 右 `03 CHAMPION RACE`（AI绿 vs 市场琥珀双条+edge 旗标）。深度内容（完整战绩/小组积分/天气研究/夺冠全表/单场详情）收进 **overlay drawer**（Esc/背景关，复用既有 Views/MatchCards/WeatherLab，故主屏永不滚动）。
  - 新增 `web/components/Dashboard.tsx`；改写 `web/app/page.tsx`（只留数据 hook + `<Dashboard>`）、`web/app/globals.css`（终端设计系统 tokens）、`web/app/layout.tsx`（去掉 zinc bg）。旧 `Views.tsx`/`MatchCards.tsx`/`MatchDetail.tsx` 保留（drawer 复用）。`npm run build` ✅ + Playwright 无头多分辨率实测 ✅（0 console error）。
  - **已部署生产**（`wrangler pages deploy web/out --branch main`，多次迭代，最新 deploy `9c3b6e55`）。线上 worldcup-oracle.pages.dev 已是新看板；Playwright 直连生产实测 0px 滚动。
  - **单场 MatchModal（放大三栏）**：点比赛卡/后续赛程行 → 大号 modal（max-w 1440 / 90vh，非原 720 Drawer）。**三栏**：左栏 `04 LIVE STATS` 实时数据 · 中栏预测详情（复用 `FocusCard`，`hideBook` 隐藏内联"盘口▾"，`lg:my-auto` 居中）· 右栏 `05 LIVE 盘口·ORDER BOOK`（`MatchDetail`：CLOB 逐笔直连概率曲线/深度梯/成交带）。三栏 grid `[minmax(258,300)_1fr_minmax(400,460)]`，各自内含滚动，modal 不超视口——2560 与 1080p 实测页面 0 滚动、三栏全见；<lg 堆叠可滚动。
  - **概率曲线线端标签**（`MatchDetail` ProbChart）：右侧留白 PAD.r=70，每条线末端直接标注 主队/平局/客队（颜色对应 emerald/gray/rose，带引线圆点 + 防重叠下推），一眼分清哪条线。
  - **LiveStats 实时比赛数据**（`components/LiveStats.tsx` + `lib/useMatchStats.ts`）：直连 ESPN summary（CORS 开放），header competitors 的 homeAway 按 team.id 映射到 boxscore.teams；取 控球/射门/射正/角球/犯规/越位/黄红牌/扑救/传球成功率，对比条展示；进行中每 25s 轮询，赛前显示"开赛后更新"占位。解析已用真实完赛场（760505 墨西哥3-2英格兰，28 项统计）复核数值正确（passPct×100、home/away 映射准）。
  - **字糊修复**：`globals.css` body 补 `-webkit-font-smoothing:antialiased`+`text-rendering:optimizeLegibility`；`.lbl` 10px→11px、字距 0.14em→0.06em（中文小字发虚的主因）；`.reveal` 动画去掉 transform 改纯 opacity（避免文字被提升到 GPU 层软化）。
  - **Logo 换世界杯奖杯**：`components/icons.tsx` `LogoMark` 足球→奖杯 SVG（杯身+双耳+底座，emerald）。
  - **Favicon**：删掉旧 `app/favicon.ico`（Next16 自动识别的足球图，会压过 metadata），改用 `app/icon.svg`（奖杯，Next 约定路由）；layout.tsx 移除重复 metadata.icons。线上 favicon 现为 `image/svg+xml` 奖杯。
- 分支：`main`；最近提交 `2026-07-02 docs: README v2 refresh（天气深挖、errata、预测审计、staleness 标签）`。
- **2026-07-06 新增（已部署生产 deploy 09865499，未 commit）**：比赛卡片"盘口 ▾"实时盘口面板——`web/lib/useMatchMarket.ts`（面板级独立 CLOB WS + REST 回填）+ `web/components/MatchDetail.tsx`（场内概率曲线 / 深度梯 / 逐笔成交 / 跳变警报）+ `MatchCards.tsx` 接线。全部浏览器直连 Polymarket（gamma/clob/data-api CORS 均 `*`，无需认证），零后端。build ✅ + Playwright 无头实测 ✅。注意：**matchday cron（06:00 UTC）会自动 build+deploy 工作区**，明早自然上线；今晚要用需手动部署。
- 依据：YSKM523/polymarket-api-reverse 逆向文档（实测更正其 docs/14：CLOB market WS 无需认证，正确订阅格式 `{"assets_ids":[...],"type":"market"}`）。
- 工作区**大量改动（~127）**：主要是 `research/weather_effect/` 的 figs/CSV/stats 与看板重建产物——**多为 cron/pipeline 每日重跑生成的 artifact**。→ 进来先 `git status` 判断哪些是真源码改动、哪些是可丢的重算输出（考虑加/确认 `.gitignore`）。
- Polymarket 已上 CLOB WS 实时。

## 研究定论（memory `project_worldcup_oracle`）
- 仅 **Phase 1 校准**是真改善；edge 多为 Elo 压缩。
- 天气研究 v2：露天湿球 ρ−0.55 / 空调馆阴性对照 / 以传代跑，**不构成预测因子**（诚实结论，勿当 alpha）。

## 新方向（2026-07-06 定调：产品/作品集向）
- 用户四选全要：场内胜率模型 / edge·尖峰推送 / 赛后 post-mortem 页 / 盘口历史回放。
- **P0 盘口 tick 采集器已上线**：`collector/collector.py`（隔离 venv，仅 aiohttp——勿混共享 venv）+ `systemd --user worldcup-collector.service`（enabled+Restart=always）。按 data.json 赛程在 [开球−45m, +3.5h] 窗口自动连 CLOB WS，落 `collector/ticks.db`（raw_events 全量 WS 消息 / mids 1Hz / trades Yes口径 / history_px 回填）。**2026-07-06 18:56Z 起已在采葡萄牙vs西班牙（开球前4分钟接入）**；后续场次（美比、两场R16、QF、SF、决赛）随 data.json 更新自动纳入。内置尖峰检测（12s ≥4pp）→ NTFY_TOPIC env 可选推送（默认关，unit 里有注释行）。
- **场内胜率模型已上线**（codex xhigh 实现 + 人工验收，2026-07-06 晚部署 deploy `33b18578`）：`web/lib/inplay.ts`（双泊松剩余进球，logit 偏移校准——t=0/0-0 精确复现校准先验；`parseClock` 解析 ESPN "45'+3"/HT/FT）+ `web/lib/useInplayCurve.ts`（in-play 每 30s 采样）+ ProbChart 叠加 AI 虚线曲线（dasharray 4 3 + 小号 "AI" 端标）。sanity：1-0@85'→主 94.4%、0-0@88'→平 94.2%、和恒=1。**葡西之战 11' 实战验证**：3 条 AI 虚线 + 3 AI 端标 + LiveStats 控球 45/55 全部在线。注意 codex 发现 bt 面板 node18 会拒绝 `~/.bashrc` 的 NODE_OPTIONS `--disable-warning`（nvm node22 正常）。
- ntfy 尖峰推送已启用：topic `wc-oracle-458e50`（unit Environment 里），用户手机 ntfy app 订阅。**富格式**（2026-07-06 中场窗口热更）：标题 `⚡ 中文队名 比分 队名 · 比赛时钟`（ESPN summary 实时取），正文=事件解读（利好哪队/疑似进球红牌）+ 三方向 12s Δpp→当前概率 + 实时比分行；**事件级冷却 60s**（进球三线齐跳只推一条聚合，不再一次 3 推）；X-Title 走 RFC2047 UTF-8 编码（ntfy 非 ASCII 标题的正确姿势）。
- 待做：盘口历史回放页（采集数据积累中）、决赛后 post-mortem 页。

## 下一步
- 让每日重建产物不污染 `git status`（gitignore 或独立输出目录）；跟进赛日 Phase B 自动跑的健康度（log 在 `results/logs/`）。

## 坑
- ⚠️ 与 hypebot/fin-forecast **共享 venv**（`feedback_shared_venv_pip`）——勿在 cron 运行时动库依赖。
