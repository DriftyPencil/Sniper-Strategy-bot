import fs from "node:fs/promises";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const DATA_PATH = "/Users/rahulbabu/Documents/SideProjects/Sniper Strategy bot/backtest-results/usdjpy-2025-full-5m-bear60-split-80-20/training_diagnostics.json";
const FINAL_PPTX = "/Users/rahulbabu/Documents/SideProjects/Sniper Strategy bot/backtest-results/usdjpy-2025-full-5m-bear60-split-80-20/usdjpy-2025-training-diagnostics.pptx";
const OUT_DIR = "/Users/rahulbabu/Documents/SideProjects/Sniper Strategy bot/build/pptx-yearly-diagnostics/rendered";

const raw = JSON.parse(await fs.readFile(DATA_PATH, "utf8"));

const W = 1280;
const H = 720;
const ink = "#000000";
const muted = "#555B64";
const panel = "#EDEDED";
const rule = "#B8BCC4";
const blue = "#3D8DFF";
const sky = "#6DCBF4";
const pale = "#D0EDFA";
const red = "#D14B4B";
const amber = "#D9942B";
const green = "#238B45";

const pres = Presentation.create({ slideSize: { width: W, height: H } });

function money(v) {
  const sign = v < 0 ? "-" : "";
  return `${sign}£${Math.abs(v).toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
}

function pct(v) {
  return `${Number(v).toFixed(1)}%`;
}

function addText(slide, text, left, top, width, height, size, opts = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    position: { left, top, width, height },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: size,
    bold: opts.bold ?? false,
    color: opts.color ?? ink,
    alignment: opts.alignment ?? "left",
  };
  return shape;
}

function addRule(slide, left, top, width) {
  slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height: 1 },
    fill: rule,
    line: { style: "solid", fill: rule, width: 0 },
  });
}

function addPanel(slide, left, top, width, height) {
  return slide.shapes.add({
    geometry: "rect",
    position: { left, top, width, height },
    fill: panel,
    line: { style: "solid", fill: rule, width: 1 },
  });
}

function addMetric(slide, label, value, left, top, width, color = ink) {
  addText(slide, value, left, top, width, 42, 30, { bold: true, color });
  addText(slide, label, left, top + 42, width, 28, 15, { color: muted });
}

function addNotes(slide, lines) {
  slide.speakerNotes.textFrame.setText([
    ...lines,
    "",
    "[Sources]",
    `Training diagnostics JSON: ${DATA_PATH}`,
    "Raw yearly data: Dukascopy-node USD/JPY bid OHLCV M5 CSV, converted to project schema and IG-style x100 price scale.",
    "IG Labs FAQ: 5-minute historical price availability is indicated as 360 days; this limited broker API access for January 2025 from the current date.",
    "Dukascopy-node docs: USD/JPY m5 history is available from May 2003 and was used as the alternate full-year source.",
  ]);
}

function titleSlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "USD/JPY 2025", 72, 92, 680, 74, 58, { bold: true });
  addText(slide, "KhanSaab Sniper training diagnostics", 72, 168, 720, 46, 30);
  addRule(slide, 72, 246, 760);
  addText(slide, "Chronological 80/20 split · 5m candles · entries 09:00-19:00 UK · £10/point", 72, 274, 880, 36, 19, { color: muted });
  addText(slide, "Full-year data changed the conclusion: the short early-year sample was not representative.", 72, 388, 900, 110, 34, { bold: true });
  addText(slide, "The training window loses heavily, and the final 20% deteriorates further. This deck focuses on diagnosing why.", 72, 518, 820, 56, 20, { color: muted });
  addText(slide, "2025 full-year diagnostic deck", 950, 640, 230, 28, 15, { color: muted, alignment: "right" });
  addNotes(slide, [
    "Purpose: diagnose the training split mechanics, not claim the strategy is ready.",
    "Key message: the full-year dataset reverses the earlier short-window optimism.",
  ]);
}

function dataSlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "The data now covers the 2025 trading year", 72, 50, 940, 50, 40, { bold: true });
  addText(slide, "Dukascopy-node filled the full-year gap that the raw BI5 route and IG API could not reliably cover from this environment.", 72, 108, 1040, 40, 18, { color: muted });
  addPanel(slide, 72, 185, 1100, 138);
  addMetric(slide, "5m rows", raw.data_source.rows.toLocaleString("en-GB"), 108, 218, 180, blue);
  addMetric(slide, "First candle", "1 Jan 22:00", 330, 218, 190);
  addMetric(slide, "Last candle", "31 Dec 21:55", 552, 218, 190);
  addMetric(slide, "Train split end", "21 Oct 05:25", 774, 218, 210);
  addMetric(slide, "Data type", "Bid OHLCV", 1010, 218, 150);
  addText(slide, "Important limitation", 72, 386, 300, 32, 26, { bold: true });
  addText(slide, "This is broker-style bid OHLCV from Dukascopy-node, converted into the existing project schema and x100 price scale. It is not IG bid/ask spread history, so spread costs are not included in this deck.", 72, 430, 1040, 74, 22, { color: ink });
  addText(slide, "That makes this useful for strategy logic diagnostics, but not a final production-grade spread-bet P&L audit.", 72, 530, 1000, 42, 22, { color: muted });
  addNotes(slide, [
    "The raw Dukascopy BI5 route timed out or rate-limited from this environment.",
    "IG demo credentials worked for recent USD/JPY data, but January 2025 M5 history was unavailable via the current IG endpoint from today's date.",
  ]);
}

function headlineSlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "The full-year split fails both in training and test", 72, 50, 1020, 50, 39, { bold: true });
  addText(slide, "The earlier positive short slice does not survive chronological validation across 2025.", 72, 108, 900, 36, 18, { color: muted });
  addPanel(slide, 72, 170, 520, 350);
  addText(slide, "Training · first 80%", 104, 198, 360, 32, 28, { bold: true });
  addMetric(slide, "Trades", raw.train.trades.toString(), 104, 254, 145);
  addMetric(slide, "Net P&L", money(raw.train.net_cash), 300, 254, 230, red);
  addMetric(slide, "Profit %", pct(raw.train.profit_pct), 104, 354, 170, red);
  addMetric(slide, "SL before TP1", pct(raw.train.sl_before_tp1_rate), 300, 354, 190);
  addText(slide, `Max drawdown: ${money(raw.train.max_dd)}`, 104, 466, 360, 30, 20, { color: muted });
  addPanel(slide, 652, 170, 520, 350);
  addText(slide, "Test · final 20%", 684, 198, 360, 32, 28, { bold: true });
  addMetric(slide, "Trades", raw.test.trades.toString(), 684, 254, 145);
  addMetric(slide, "Net P&L", money(raw.test.net_cash), 880, 254, 230, red);
  addMetric(slide, "Profit %", pct(raw.test.profit_pct), 684, 354, 170, red);
  addMetric(slide, "SL before TP1", pct(raw.test.sl_before_tp1_rate), 880, 354, 190);
  addText(slide, `Max drawdown: ${money(raw.test.max_dd)}`, 684, 466, 360, 30, 20, { color: muted });
  addText(slide, "Diagnostic implication: do not tune against the final 20%; use it only as the out-of-sample check.", 72, 588, 1040, 38, 22, { bold: true });
  addNotes(slide, [
    "Training and test use the same settings: M5, 09:00-19:00 Europe/London entries, BUY and SELL, Bull Score > 60 for long, Bear Score >= 60 and dominant for short.",
  ]);
}

function equitySlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "Training equity decays through the year", 72, 50, 920, 50, 39, { bold: true });
  addText(slide, "The cumulative line shows repeated drawdown regimes rather than one isolated failure.", 72, 108, 900, 36, 18, { color: muted });
  slide.charts.add("line", {
    position: { left: 76, top: 165, width: 1100, height: 410 },
    categories: raw.train_equity.map((d) => String(d.trade)),
    series: [
      { name: "Cumulative P&L", values: raw.train_equity.map((d) => d.equity), line: { style: "solid", fill: blue, width: 3 } },
      { name: "Drawdown", values: raw.train_equity.map((d) => d.drawdown), line: { style: "solid", fill: red, width: 2 } },
    ],
    hasLegend: true,
    legend: { position: "bottom", overlay: false, textStyle: { fontSize: 14, fill: muted } },
    yAxis: { title: "Cash P&L (£)", numberFormatCode: "£#,##0;[Red]-£#,##0", majorGridlines: { style: "solid", fill: "#E6E6E6", width: 1 } },
    xAxis: { title: "Trade number", textStyle: { fontSize: 11, fill: muted } },
  });
  addText(slide, `Training net: ${money(raw.train.net_cash)} · max drawdown: ${money(raw.train.max_dd)}`, 72, 620, 1020, 34, 22, { bold: true });
  addNotes(slide, [
    "Equity series is sampled every five trades for readability; totals are calculated from every training trade.",
  ]);
}

function exitsSlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "Most training exits are still stop-led", 72, 50, 960, 50, 39, { bold: true });
  addText(slide, "The failure problem is not just cosmetic labelling: nearly half of all training trades stop before TP1.", 72, 108, 1000, 36, 18, { color: muted });
  slide.charts.add("bar", {
    position: { left: 72, top: 170, width: 550, height: 390 },
    categories: raw.train_exits.map((d) => d.reason),
    series: [{ name: "Trades", values: raw.train_exits.map((d) => d.trades), fill: blue }],
    hasLegend: false,
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 42 },
    dataLabels: { showValue: true, position: "outEnd", textStyle: { fontSize: 13, fill: ink, bold: true } },
    xAxis: { visible: false, majorGridlines: null },
    yAxis: { textStyle: { fontSize: 12, fill: muted } },
  });
  slide.charts.add("bar", {
    position: { left: 690, top: 170, width: 480, height: 390 },
    categories: raw.train_exits.map((d) => d.reason),
    series: [{ name: "P&L", values: raw.train_exits.map((d) => d.pnl), fill: red }],
    hasLegend: false,
    barOptions: { direction: "bar", grouping: "clustered", gapWidth: 42 },
    yAxis: { numberFormatCode: "£#,##0;[Red]-£#,##0", majorGridlines: { style: "solid", fill: "#E6E6E6", width: 1 } },
    xAxis: { textStyle: { fontSize: 12, fill: muted } },
  });
  addText(slide, `SL exits: ${pct(raw.train.sl_rate)} · SL before TP1: ${pct(raw.train.sl_before_tp1_rate)} · TP3 complete: ${pct(raw.train.tp3_rate)}`, 72, 620, 1040, 32, 22, { bold: true });
  addNotes(slide, [
    "Exit reason counts come from train_trades.csv. SL before TP1 is separately calculated to distinguish final SL labels from genuinely failed-before-first-target trades.",
  ]);
}

function hourlySlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "Time of day explains a lot of the damage", 72, 50, 980, 50, 39, { bold: true });
  addText(slide, "The training split has specific UK entry hours where losses cluster and SL-before-TP1 is elevated.", 72, 108, 1040, 36, 18, { color: muted });
  slide.charts.add("bar", {
    position: { left: 72, top: 170, width: 520, height: 390 },
    categories: raw.train_hourly.map((d) => d.hour),
    series: [{ name: "Net P&L", values: raw.train_hourly.map((d) => d.pnl), fill: blue }],
    hasLegend: false,
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 55 },
    yAxis: { title: "Net P&L (£)", numberFormatCode: "£#,##0;[Red]-£#,##0", majorGridlines: { style: "solid", fill: "#E6E6E6", width: 1 } },
    xAxis: { title: "Entry hour UK", textStyle: { fontSize: 12, fill: muted } },
  });
  slide.charts.add("bar", {
    position: { left: 650, top: 170, width: 520, height: 390 },
    categories: raw.train_hourly.map((d) => d.hour),
    series: [{ name: "SL before TP1", values: raw.train_hourly.map((d) => d.sl_before_tp1_rate / 100), fill: amber }],
    hasLegend: false,
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 55 },
    yAxis: { title: "SL before TP1 (%)", numberFormatCode: "0%", majorGridlines: { style: "solid", fill: "#E6E6E6", width: 1 } },
    xAxis: { title: "Entry hour UK", textStyle: { fontSize: 12, fill: muted } },
  });
  addText(slide, "Use this slide to diagnose session filters, but validate any change on the held-out 20%.", 72, 620, 1060, 32, 22, { bold: true });
  addNotes(slide, [
    "Hourly buckets are based on trade entry time converted to Europe/London.",
  ]);
}

function scoreSlide() {
  const slide = pres.slides.add();
  slide.background.fill = "#FFFFFF";
  addText(slide, "Higher score is not enough by itself", 72, 50, 980, 50, 39, { bold: true });
  addText(slide, "Training losses remain visible across score buckets and both directions, so the next work should focus on exit logic and time/session rules.", 72, 108, 1080, 42, 18, { color: muted });
  slide.charts.add("bar", {
    position: { left: 72, top: 178, width: 520, height: 360 },
    categories: raw.train_score.map((d) => d.bucket),
    series: [
      { name: "P&L", values: raw.train_score.map((d) => d.pnl), fill: blue },
    ],
    hasLegend: false,
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 55 },
    yAxis: { title: "Net P&L (£)", numberFormatCode: "£#,##0;[Red]-£#,##0", majorGridlines: { style: "solid", fill: "#E6E6E6", width: 1 } },
    xAxis: { title: "Entry score bucket" },
  });
  slide.charts.add("bar", {
    position: { left: 650, top: 178, width: 520, height: 360 },
    categories: raw.train_direction.map((d) => d.direction),
    series: [
      { name: "SL before TP1", values: raw.train_direction.map((d) => d.sl_before_tp1_rate / 100), fill: amber },
    ],
    hasLegend: false,
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 65 },
    yAxis: { title: "SL before TP1 (%)", numberFormatCode: "0%", majorGridlines: { style: "solid", fill: "#E6E6E6", width: 1 } },
    xAxis: { title: "Direction" },
  });
  addText(slide, "Recommended next pass: test wider ATR stops and session filters on training only, then preserve the final 20% as the validation gate.", 72, 604, 1080, 56, 23, { bold: true });
  addNotes(slide, [
    "Score bucket uses Bull Score for BUY and Bear Score for SELL.",
    "The direction chart shows SL-before-TP1 by direction; cash P&L by direction is available in training_diagnostics.json.",
  ]);
}

titleSlide();
dataSlide();
headlineSlide();
equitySlide();
exitsSlide();
hourlySlide();
scoreSlide();

await fs.mkdir(OUT_DIR, { recursive: true });
for (const [index, slide] of pres.slides.items.entries()) {
  const stem = `slide-${String(index + 1).padStart(2, "0")}`;
  const png = await pres.export({ slide, format: "png", scale: 1 });
  await fs.writeFile(`${OUT_DIR}/${stem}.png`, new Uint8Array(await png.arrayBuffer()));
  const layout = await slide.export({ format: "layout" });
  await fs.writeFile(`${OUT_DIR}/${stem}.layout.json`, await layout.text());
}
const montage = await pres.export({ format: "webp", montage: true, scale: 1 });
await fs.writeFile(`${OUT_DIR}/montage.webp`, new Uint8Array(await montage.arrayBuffer()));
const pptx = await PresentationFile.exportPptx(pres);
await pptx.save(FINAL_PPTX);
