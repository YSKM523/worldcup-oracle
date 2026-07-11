// Run while `npm run dev -- --port 3002` is active:
// playwright-cli -s=task4-review open http://localhost:3002
// playwright-cli -s=task4-review run-code --filename=tests/task4-layout.playwright.js
// eslint-disable-next-line @typescript-eslint/no-unused-expressions -- run-code consumes this function expression
async page => {
  let completedFixture = false;
  const fixtureResponse = await page.request.get("http://localhost:3002/data.json");
  const fixture = await fixtureResponse.json();
  await page.context().route("**/data.json*", async route => {
    const data = JSON.parse(JSON.stringify(fixture));
    const match = data.matches.find(item => item.home === "Norway" && item.away === "England");
    if (completedFixture) {
      match.completed = true;
      match.status = "STATUS_FINAL";
    }
    await route.fulfill({ contentType: "application/json", body: JSON.stringify(data) });
  });
  await page.context().route("**/api/kalshi/match**", route => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({ status: "unavailable", source: "kalshi-rest", eventTicker: null, updatedAt: Date.now(), outcomes: {} }),
  }));
  await page.context().route("**/gamma-api.polymarket.com/**", route => {
    const url = route.request().url();
    const gamma = url.includes("fifwc-nor-eng-2026-07-11") ? [{
      title: "Norway vs. England",
      endDate: "2026-07-11T21:00:00+00:00",
      markets: [
        { question: "Will Norway win?", outcomePrices: "[\"0.10\",\"0.90\"]", clobTokenIds: "[\"nor\"]" },
        { question: "Will there be a draw?", outcomePrices: "[\"0.20\",\"0.80\"]", clobTokenIds: "[\"draw\"]" },
        { question: "Will England win?", outcomePrices: "[\"0.70\",\"0.30\"]", clobTokenIds: "[\"eng\"]" },
      ],
    }] : [];
    return route.fulfill({ contentType: "application/json", body: JSON.stringify(gamma) });
  });
  await page.context().route("**/clob.polymarket.com/**", route => route.fulfill({ contentType: "application/json", body: "{}" }));
  await page.context().route("**/data-api.polymarket.com/**", route => route.fulfill({ contentType: "application/json", body: "[]" }));
  await page.context().route("**/site.api.espn.com/**", route => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      header: { competitions: [{ status: { type: { state: "post", detail: "FT" } }, competitors: [{ homeAway: "home", team: { id: "h" } }, { homeAway: "away", team: { id: "a" } }] }] },
      boxscore: { teams: [{ team: { id: "h" }, statistics: [{ name: "totalShots", displayValue: "10" }] }, { team: { id: "a" }, statistics: [{ name: "totalShots", displayValue: "8" }] }] },
    }),
  }));

  const open = async () => {
    await page.getByRole("button").filter({ hasText: "挪威" }).filter({ hasText: "英格兰" }).first().click();
    await page.locator("[data-match-modal-grid]").waitFor();
  };
  const closeEscape = async () => {
    await page.keyboard.press("Escape");
    if (await page.locator("[data-match-modal-grid]").count()) throw new Error("Escape did not close dialog");
  };
  const assertForecastTabs = async width => {
    const tabs = page.locator("[data-forecast-tabs]");
    if (await tabs.count() !== 1) throw new Error(`${width}: expected one forecast tab set`);
    const tabIds = ["value", "scripts", "scores", "watch"];
    const controls = [];
    for (const tabId of tabIds) {
      const tab = tabs.locator(`[data-forecast-tab=${tabId}]`);
      if (await tab.count() !== 1 || await tab.getAttribute("role") !== "tab") throw new Error(`${width}: ${tabId} is not a semantic tab button`);
      controls.push(await tab.getAttribute("aria-controls"));
    }
    if (new Set(controls).size !== tabIds.length) throw new Error(`${width}: forecast tabs do not control distinct panels`);
    const scores = tabs.locator("[data-forecast-tab=scores]");
    if (await scores.getAttribute("aria-selected") !== "true" || !(await scores.isVisible())) throw new Error(`${width}: scores is not visibly selected by default`);
    const scorePanel = tabs.locator(`[id=\"${controls[2]}\"]`);
    if (!(await scorePanel.isVisible()) || !(await scorePanel.textContent()).includes("比分分布")) throw new Error(`${width}: scores panel is not visibly rendered by default`);
    const scoreSides = [
      ["home", "bg-emerald"],
      ["draw", "bg-zinc"],
      ["away", "bg-rose"],
    ];
    for (const [side, color] of scoreSides) {
      const cell = scorePanel.locator(`[data-forecast-score-side=${side}]`).first();
      if (!(await cell.isVisible()) || !(await cell.getAttribute("class")).includes(color)) throw new Error(`${width}: ${side} score encoding missing`);
    }
    for (let index = 0; index < tabIds.length; index += 1) {
      const tab = tabs.locator(`[data-forecast-tab=${tabIds[index]}]`);
      await tab.click();
      const panel = tabs.locator(`[id=\"${controls[index]}\"]`);
      if (await tab.getAttribute("aria-selected") !== "true" || !(await panel.isVisible())) throw new Error(`${width}: ${tabIds[index]} did not switch to its panel`);
    }
    const watchPanel = tabs.locator(`[id=\"${controls[3]}\"]`);
    const source = watchPanel.locator("[data-forecast-watch=pm]");
    await source.filter({ hasText: "PM REST/GAMMA · FRESH" }).waitFor();
    if (!(await watchPanel.locator("[data-forecast-divergence-alert=critical]").isVisible())) throw new Error(`${width}: missing critical AI/PM divergence alert`);
    const watch = await watchPanel.evaluate((panel) => ({
      clientHeight: panel.clientHeight,
      scrollHeight: panel.scrollHeight,
      visibleItems: panel.querySelectorAll("li").length,
    }));
    if (watch.clientHeight < 160) throw new Error(`${width}: watch panel is too short (${watch.clientHeight}px)`);
    if (watch.visibleItems < 5) throw new Error(`${width}: watch items are clipped (${watch.visibleItems})`);
    if (watch.scrollHeight < watch.clientHeight) throw new Error(`${width}: watch panel reports invalid scroll bounds`);
  };

  await page.goto("http://localhost:3002");
  const matrix = [];
  for (const [width, height] of [[1920, 1080], [2560, 1440], [3440, 1440], [1366, 768], [1024, 768], [390, 844]]) {
    await page.setViewportSize({ width, height });
    await open();
    const box = async name => page.locator(`[data-match-column=${name}]`).boundingBox();
    const stats = await box("stats");
    const prediction = await box("prediction");
    const market = await box("market");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow !== 0) throw new Error(`${width}: horizontal overflow ${overflow}`);
    if (width >= 1280) {
      if (!(stats.x < prediction.x && prediction.x < market.x)) throw new Error(`${width}: desktop visual order`);
      if (stats.width < 260 || stats.width > 280 || market.width < 440) throw new Error(`${width}: rail widths`);
      if (![prediction, market].every(item => Math.abs(item.y - stats.y) < 1 && Math.abs(item.height - stats.height) < 1)) throw new Error(`${width}: desktop alignment`);
      const scroll = await page.locator("[data-match-column]").evaluateAll(items => items.map(item => getComputedStyle(item).overflowY));
      if (scroll.some(value => value !== "auto")) throw new Error(`${width}: independent scroll ${scroll}`);
      if ([1920, 2560].includes(width)) {
        await assertForecastTabs(width);
        const surface = await page.locator("[data-console-surface=prediction]").boundingBox();
        if (Math.abs((surface.y + surface.height) - (market.y + market.height - 12)) > 1) throw new Error(`${width}: prediction surface misses market 12px bottom inset`);
      }
    } else if (!(prediction.y < stats.y && stats.y < market.y && prediction.y + prediction.height <= stats.y + 1 && stats.y + stats.height <= market.y + 1)) {
      throw new Error(`${width}: expected prediction→stats→market without overlap`);
    }
    const close = await page.getByRole("button", { name: "关闭" }).boundingBox();
    if (close.width < 44 || close.height < 44) throw new Error(`${width}: close target ${close.width}x${close.height}`);
    const dialog = page.getByRole("dialog", { name: /MATCH DETAIL/ });
    if (await dialog.getAttribute("aria-modal") !== "true") throw new Error(`${width}: dialog semantics`);
    if ([1920, 2560, 1366, 1024].includes(width)) await page.screenshot({ path: `../.superpowers/sdd/task-4-review-${width}x${height}.png` });
    matrix.push({ viewport: `${width}x${height}`, overflow, stats: stats.width, market: market.width });
    await closeEscape();
  }

  await page.setViewportSize({ width: 1920, height: 1080 });
  await open();
  await assertForecastTabs(1920);
  await page.getByRole("button", { name: "关闭" }).click();
  if (await page.locator("[data-match-modal-grid]").count()) throw new Error("icon did not close dialog");
  await open();
  if (await page.locator("[data-forecast-tab=scores]").getAttribute("aria-selected") !== "true") throw new Error("1920: reopening did not reset forecast tabs to scores");
  await page.mouse.click(2, 2);
  if (await page.locator("[data-match-modal-grid]").count()) throw new Error("backdrop did not close dialog");

  completedFixture = true;
  await page.reload();
  await open();
  const statsRail = page.locator("[data-match-column=stats]");
  const completed = { liveStats: await statsRail.locator("[data-live-stats-mode]").count(), telemetry: await statsRail.locator("[data-match-telemetry]").count() };
  if (completed.liveStats !== 1 || completed.telemetry !== 0) throw new Error(`completed state ${JSON.stringify(completed)}`);
  await closeEscape();

  return { matrix, completed };
}
