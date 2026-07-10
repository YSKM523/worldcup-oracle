# MATCH DETAIL 多市场共识盘口设计

## 背景

WorldCup Oracle 的主要使用场景是在 27–32 寸桌面显示器上持续监控比赛、模型预测和市场变化。当前 MATCH DETAIL 将实时统计放在预测主区下方，盘口只展示 Polymarket。用户希望把 LIVE STATS 恢复为左侧固定边栏，并增加 Kalshi，使盘口首先呈现跨交易所共识，同时保留单一市场的微观结构。

仓库已经包含 `collector/kalshi.py`，能够把 `KXWCGAME` 世界杯常规时间胜平负市场解析为 home/draw/away，并以一秒周期抓取 bid、ask 和 mid。Kalshi 官方 WebSocket 在握手阶段必须使用 API Key 与 RSA-PSS 签名；当前项目没有 Kalshi 账户凭证，因此本阶段使用无需认证的公开 REST 行情，并通过稳定接口边界保留以后切换 WebSocket 的能力。

## 目标

- 在 1280px 及以上将 MATCH DETAIL 改为稳定的三栏监控布局。
- 左栏固定展示赛前遥测或开赛后的 LIVE STATS，不因状态变化改变栏宽。
- 右栏首先展示 Polymarket 与 Kalshi 的胜平负共识概率和来源分歧。
- Kalshi 在弹窗打开时约每秒更新，失败时不影响 Polymarket 或预测主区。
- 保留 Polymarket 概率曲线、深度梯和逐笔成交，并明确标注其单一来源。
- 不伪造缺失市场、不把不同交易所的订单簿深度直接相加。

## 非目标

- 不创建 Kalshi 账户、交易凭证或下单能力。
- 不绕过 Kalshi WebSocket 认证，也不在浏览器中存放私钥。
- 不把 Kalshi 与 Polymarket 合成为可执行的跨交易所订单簿。
- 不改变 AI 模型、比赛数据接口、历史评分或现有 Polymarket 订阅逻辑。

## 桌面布局

### 1280px 及以上

MATCH DETAIL 使用三栏：

1. **LIVE STATS / TELEMETRY：270px**
2. **比赛预测主区：`minmax(0, 1fr)`**
3. **MARKET CONSENSUS：约 500px，最低 440px**

弹窗继续使用内容驱动高度并限制在视口约 90% 内。三栏从顶部对齐，各栏仅在内容超过可用高度时独立滚动。

### 低于 1280px

使用单列顺序：比赛预测 → LIVE STATS / TELEMETRY → MARKET CONSENSUS。弹窗整体滚动，不隐藏关键数据。

## 左侧 LIVE STATS / TELEMETRY

左栏宽度始终固定，避免开赛时页面横向跳动。

### 赛前

显示：

- 开球时间与倒计时
- 阶段、场地、城市
- 温度、湿度和天气标签（有数据时）
- ESPN 比赛数据状态
- Polymarket 状态与更新时间
- Kalshi REST 状态与更新时间
- 提示“控球 / 射门 / 角球 / 牌将在开赛后更新”

### 进行中或完场

原位切换为现有 LIVE STATS 指标：控球、射门、射正、角球、犯规、越位、牌、扑救、传球成功率和 ESPN 来源页脚。保持单列统计，适配 270px 窄栏。

## Kalshi 数据服务

### Pages Function

新增 `GET /api/kalshi/match?home=<team>&away=<team>&kickoff=<ISO8601>` Cloudflare Pages Function，并用 `_routes.json` 将 Function 范围限制在 `/api/*`。静态页面和静态资源不进入 Function。

前端请求以比赛的主队、客队和开球时间为输入。Function：

1. 验证输入长度和字符范围。
2. 获取 `KXWCGAME` 当前开放赛事。
3. 以标准化后的主客队名称和比赛日期定位唯一 event。
4. 批量读取该 event 的三个 market。
5. 将 `Reg Time: <team>` 与 `Reg Time: Tie` 映射为 home/draw/away。
6. 返回统一行情结构。

响应契约：

```ts
type KalshiQuote = {
  status: "live" | "unavailable" | "error";
  source: "kalshi-rest";
  eventTicker: string | null;
  updatedAt: number;
  outcomes: Partial<Record<"home" | "draw" | "away", {
    ticker: string;
    bid: number | null;
    ask: number | null;
    mid: number | null;
    last: number | null;
    volume: number | null;
  }>>;
};
```

Function 使用约一秒边缘缓存，避免同一秒内多个浏览器请求重复击穿 Kalshi。响应包含 `Cache-Control`，错误响应使用短暂负缓存。

### 前端轮询

新增 Kalshi hook，仅在 MATCH DETAIL 打开且比赛存在明确主客队时运行：

- 正常状态每秒请求一次本站 Function。
- 关闭弹窗时立即取消请求和定时器。
- 连续失败采用 2s、5s、10s 的有限退避；成功后恢复 1s。
- 15 秒未收到有效三项行情即标记 stale，并退出双源共识。
- 网络错误不清空最后有效值，而是显示 stale 状态。

该 hook 的输出接口与传输方式解耦。将来获得只读 Kalshi API Key 后，可用 Cloudflare WebSocket 网关替换 REST transport，而无需改共识算法和 UI。

## 共识算法

每个交易所必须先独立归一化：

```text
normalized(source, outcome) = midpoint(outcome) / sum(source midpoints)
```

当 Polymarket 与 Kalshi 都提供三项有效且新鲜的 midpoint 时：

```text
consensus(outcome) = 0.5 × normalized_polymarket(outcome)
                   + 0.5 × normalized_kalshi(outcome)
```

同时计算：

```text
divergence(outcome) = abs(normalized_polymarket - normalized_kalshi)
```

- 分歧大于等于 5pp：琥珀提示。
- 分歧大于等于 10pp：红色警报。
- 两家均有效：状态 `2/2 LIVE`。
- 只有一家有效：显示该来源的归一化概率并标记 `1/2 · SINGLE SOURCE`，不使用“共识”文案。
- 两家均无效：显示 unavailable 状态，不回退到 AI 概率冒充市场。

成交量只作为来源信息展示，不用于加权，因为两家市场的成交量与合约单位不可直接比较。

## MARKET CONSENSUS 界面

右栏从上到下包含：

1. **状态行**：`PM WS · KAL REST 1S · 2/2 LIVE` 与最后更新时间。
2. **三项共识条**：主胜、平局、客胜的共识概率。
3. **来源矩阵**：每项显示共识/单源概率、Polymarket、Kalshi 和分歧 pp。
4. **报价明细**：Kalshi bid/ask/last/volume；Polymarket mid 与现有成交量。
5. **分歧警报**：只在达到阈值时出现，说明哪一来源更高。
6. **POLY MICROSTRUCTURE**：保留现有 Polymarket 概率曲线、结果切换、深度梯和逐笔成交，并明确标注该区域不是聚合深度。

界面使用现有 emerald / zinc / rose 结果色和 amber 分歧色，不增加渐变、发光或大型装饰指标。

## 错误与降级

- Kalshi event 无法匹配：显示 `KAL UNAVAILABLE`，Polymarket 正常运行。
- Kalshi 只返回部分赛果：整家来源不参与共识，避免不完整归一化。
- Pages Function 超时或 429：返回结构化错误并短暂缓存；前端保留最后值、标记 stale 并退避。
- Polymarket 缺失：Kalshi 作为单源显示。
- 两家合约名称或比赛日期无法唯一匹配：拒绝聚合并记录可诊断原因。
- 浏览器永远不直接请求 Kalshi，也不持有任何 Kalshi 认证信息。

## 测试与验收

### 数据与算法

- 使用固定 Kalshi event/market fixtures 验证主胜、平局、客胜映射。
- 验证反向主客队、日期不匹配、重复 event、缺少一项和 429/超时。
- 验证每家归一化后合计为 100%。
- 验证 50/50 共识、5pp/10pp 阈值、single-source 和 unavailable 状态。
- 验证一秒轮询、退避、stale 与关闭弹窗后的清理。

### 浏览器

- 1920×1080、2560×1440、3440×1440：三栏顶部对齐，无页面横向溢出，左栏约 270px，右栏不低于 440px。
- 1366×768：三栏仍可用，各栏独立滚动。
- 1024×768、390×844：单列顺序正确，无内容重叠和横向溢出。
- 赛前左栏显示完整遥测且无大片空白；进行中/完场显示单列 LIVE STATS。
- 双源、单源、stale、unavailable 四种盘口状态均可读。
- Polymarket 深度、成交、结果 tab、Escape、关闭按钮和遮罩关闭保持正常。

### 部署

- 本地用 `wrangler pages dev` 同时验证静态输出和 Function。
- `_routes.json` 只包含 `/api/*`，静态资源不触发 Function。
- 预览部署验证 `/api/kalshi` 响应、缓存头和真实 `KXWCGAME` 映射后再发布生产。
