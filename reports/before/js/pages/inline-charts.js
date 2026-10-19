/** 既存ページの data-chart と Phase 3 シミュレーターを描画する。 */

import { loadExploreData } from "../data.js";
import { getAssumptions, getFilters, setFilters, subscribe } from "../store.js";
import { clinicRanking, distanceBreakdown, kpis, monthlyStacked, rankedList, retentionRate } from "../aggregate.js";
import {
  axisColor,
  eventMarks,
  isNarrow,
  maxWithTarget,
  renderChart,
  renderEventList,
  savePng,
  themeColors,
} from "../charts.js";
import { simulateLevers, simulateScenarios } from "../simulator.js";

const AXIS_PLAIN = { 門前型: "門前", 非門前型: "門前以外", 不明: "不明" };

let DATA = null;

function fmt(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("ja-JP", { maximumFractionDigits: 0 });
}

function parseSpec(node) {
  try {
    return JSON.parse(node.getAttribute("data-chart") || "{}");
  } catch (_e) {
    return { id: node.id, kind: node.getAttribute("data-kind") };
  }
}

function ensureToolbar(wrap, canvas, filename) {
  if (wrap.querySelector(".chart-save")) return;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "chart-save";
  btn.textContent = "画像として保存";
  btn.addEventListener("click", () => savePng(canvas, filename));
  wrap.insertBefore(btn, canvas);
}

function drawMonthly(canvas, spec) {
  const f = getFilters();
  const a = getAssumptions();
  const stacked = monthlyStacked(DATA, f, spec.by || "axis");
  const keys = DATA.dims.axes || [];
  const colors = themeColors();
  const series = keys.map((key) => ({
    name: AXIS_PLAIN[key] || key,
    type: spec.kind === "line" ? "line" : "bar",
    stack: spec.kind === "line" ? undefined : "a",
    itemStyle: { color: axisColor(key) },
    data: stacked.months.map((ym) => stacked.series.get(ym)?.get(key) || 0),
  }));
  const marks = eventMarks(DATA.events.events || [], stacked.months);
  if (series[0]) {
    series[0].markLine = {
      symbol: "none",
      data: [
        {
          yAxis: a.targetMonthly,
          name: "目標",
          lineStyle: { color: colors.target, type: "dashed" },
          label: {
            formatter: `目標 ${fmt(a.targetMonthly)}枚`,
            position: "insideStartTop",
            color: colors.target,
            fontWeight: 700,
          },
        },
        ...(marks.markLine.data || []),
      ],
    };
    series[0].markArea = marks.markArea;
  }
  renderChart(canvas, {
    legend: { bottom: 0, textStyle: { color: colors.muted } },
    grid: { left: 8, right: 16, top: 40, bottom: 36, containLabel: true },
    xAxis: { type: "category", data: stacked.months, axisLabel: { rotate: 45 } },
    yAxis: {
      type: "value",
      name: "枚",
      max: maxWithTarget(a.targetMonthly),
      interval: a.targetMonthly > 2000 ? Math.ceil((a.targetMonthly * 1.04) / 7 / 500) * 500 : undefined,
    },
    series,
  });
  renderEventList(canvas, marks.list);
}

function drawClinics(canvas, spec) {
  const f = getFilters();
  const { map } = clinicRanking(DATA, f);
  const total = [...map.values()].reduce((x, y) => x + y, 0);
  const narrow = isNarrow(canvas);
  const n = spec.top || 10;
  const rows = rankedList(map, DATA.dims.clinic_order).slice(0, n).reverse();
  const chart = renderChart(canvas, {
    grid: { left: 8, right: narrow ? 52 : 64, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "value", name: "枚", splitNumber: narrow ? 3 : 5 },
    yAxis: {
      type: "category",
      data: rows.map((r) => DATA.dims.clinics?.[r.key]?.name || r.key),
      axisLabel: { width: narrow ? 110 : 230, overflow: "truncate" },
    },
    series: [
      {
        type: "bar",
        data: rows.map((r) => ({
          value: r.n,
          clinicId: r.key,
          itemStyle: { color: DATA.dims.clinics?.[r.key]?.gate ? themeColors().gate : themeColors().nongate },
        })),
        label: {
          show: true,
          position: "right",
          formatter: (p) => `${total ? Math.round((p.value / total) * 100) : 0}%`,
        },
      },
    ],
    tooltip: {
      trigger: "item",
      formatter: (p) => {
        const name = DATA.dims.clinics?.[p.data?.clinicId]?.name || p.name;
        const pctShare = total ? ((p.value / total) * 100).toFixed(1) : "0";
        return `${name}<br/>${fmt(p.value)}枚（全体の${pctShare}%）`;
      },
    },
  });
  if (chart) {
    chart.off("click");
    chart.on("click", (p) => {
      const id = p.data && p.data.clinicId;
      if (id) setFilters({ clinic: [id] });
    });
  }
}

function drawDistance(canvas) {
  const f = getFilters();
  const { rows } = distanceBreakdown(DATA, f, DATA.retention, DATA.dims);
  renderChart(canvas, {
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: rows.map((r) => DATA.dims.dist_labels?.[r.dist] || r.dist) },
    yAxis: { type: "value", name: "枚" },
    series: [{ type: "bar", data: rows.map((r) => r.n), itemStyle: { color: themeColors().nongate } }],
  });
}

function drawRetention(canvas) {
  const f = getFilters();
  const axes = DATA.dims.axes || [];
  const rates = axes.map((axis) => retentionRate(DATA.retention, { ...f, axis: [axis] }, DATA.dims).rate);
  renderChart(canvas, {
    xAxis: { type: "category", data: axes.map((a) => AXIS_PLAIN[a] || a) },
    yAxis: { type: "value", min: 0, max: 1, axisLabel: { formatter: (v) => `${Math.round(v * 100)}%` } },
    series: [{ type: "bar", data: rates, itemStyle: { color: themeColors().accent } }],
  });
}

/** Phase 5 推移図。フィルタは無視し、全期間の totals から描く。 */
function drawTimeline(canvas) {
  const totals = DATA.totals;
  const colors = themeColors();
  const months = [...new Set(totals.by_axis.map((r) => r[0]))].sort();
  const totalByMonth = new Map();
  for (const [ym, _axis, n] of totals.by_axis) {
    totalByMonth.set(ym, (totalByMonth.get(ym) || 0) + Number(n));
  }
  const clinicTotals = new Map();
  for (const [_ym, id, n] of totals.by_clinic) {
    if (id === "OTHER") continue;
    clinicTotals.set(id, (clinicTotals.get(id) || 0) + Number(n));
  }
  const top2 = [...clinicTotals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 2).map(([id]) => id);
  const top2Names = top2.map((id) => DATA.dims.clinics?.[id]?.name || id);
  const top2ByMonth = new Map();
  for (const [ym, id, n] of totals.by_clinic) {
    if (!top2.includes(id)) continue;
    top2ByMonth.set(ym, (top2ByMonth.get(ym) || 0) + Number(n));
  }
  const firstByMonth = new Map();
  for (const [ym, vt, n] of totals.by_visit_type) {
    if (vt !== "初回") continue;
    firstByMonth.set(ym, Number(n));
  }
  const all = months.map((ym) => totalByMonth.get(ym) || 0);
  const top2Series = months.map((ym) => top2ByMonth.get(ym) || 0);
  const otherSeries = months.map((ym, i) => Math.max(0, all[i] - top2Series[i]));
  const firstSeries = months.map((ym) => firstByMonth.get(ym) || 0);
  const marks = eventMarks(DATA.events.events || [], months);
  const series = [
    {
      name: "処方箋（全体）",
      type: "line",
      data: all,
      itemStyle: { color: colors.ink },
      lineStyle: { width: 2.5 },
      markLine: marks.markLine,
      markArea: marks.markArea,
    },
    {
      name: `上位2院（${top2Names.join("・")}）`,
      type: "line",
      data: top2Series,
      itemStyle: { color: colors.gate },
    },
    {
      name: "上位2院以外",
      type: "line",
      data: otherSeries,
      itemStyle: { color: colors.nongate },
    },
    {
      name: "新患（初めて来局した人）",
      type: "line",
      data: firstSeries,
      itemStyle: { color: colors.accent },
      lineStyle: { type: "dashed", width: 1.6 },
    },
  ];
  const narrow = isNarrow(canvas);
  renderChart(canvas, {
    legend: { bottom: 0, textStyle: { color: colors.muted } },
    grid: { left: 8, right: 16, top: 40, bottom: narrow ? 64 : 40, containLabel: true },
    xAxis: { type: "category", data: months, axisLabel: { rotate: 45 } },
    yAxis: { type: "value", name: "件／月" },
    series,
  });
  renderEventList(canvas, marks.list);
}

function drawAll() {
  if (!DATA || document.body.hasAttribute("data-explore")) return;
  document.querySelectorAll("[data-chart]").forEach((node) => {
    const spec = parseSpec(node);
    let canvas = node.querySelector(".chart-canvas");
    if (!canvas) {
      canvas = document.createElement("div");
      canvas.className = "chart-canvas";
      canvas.style.height = "360px";
      node.appendChild(canvas);
    }
    ensureToolbar(node, canvas, `${spec.id || spec.kind || "chart"}.png`);
    const kind = spec.kind || "";
    if (kind === "monthly" || kind === "monthly_axis" || kind === "line") drawMonthly(canvas, spec);
    else if (kind === "clinic_rank") drawClinics(canvas, spec);
    else if (kind === "distance") drawDistance(canvas);
    else if (kind === "retention" || kind === "retention90") drawRetention(canvas);
    else if (kind === "timeline") drawTimeline(canvas);
  });
}

function currentInputs() {
  const a = getAssumptions();
  const c = DATA.params.current;
  return {
    monthly_visits: c.monthly_visits,
    target_monthly: a.targetMonthly,
    gate_share: c.gate_share,
    nongate_share: c.nongate_share,
  };
}

function mountSimulator() {
  const root = document.getElementById("growth-simulator");
  if (!root || !DATA) return;
  if (!root.dataset.ready) {
    root.dataset.ready = "1";
    root.innerHTML = `<h3>条件を動かして試す</h3>
      <p class="section-note">今の処方箋の内訳を、スライダーで変えたときの到達枚数です。施策の効果ではありません。</p>
      <div class="sim-sliders">
        <div class="sim-row">
          <span class="sim-label">門前の増加率</span>
          <input type="range" min="0" max="50" value="0" data-sim="gateGrowth" aria-label="門前の増加率"/>
          <span class="sim-val" data-out="gateGrowth">0%</span>
        </div>
        <div class="sim-row">
          <span class="sim-label">門前以外の倍率</span>
          <input type="range" min="10" max="50" value="10" data-sim="nongateMult" aria-label="門前以外の倍率"/>
          <span class="sim-val" data-out="nongateMult">×1.0</span>
        </div>
        <div class="sim-row">
          <span class="sim-label">来局頻度の増加率</span>
          <input type="range" min="0" max="50" value="0" data-sim="freqGrowth" aria-label="来局頻度の増加率"/>
          <span class="sim-val" data-out="freqGrowth">0%</span>
        </div>
        <div class="sim-row">
          <span class="sim-label">活動患者の増加率</span>
          <input type="range" min="0" max="50" value="0" data-sim="stockGrowth" aria-label="活動患者の増加率"/>
          <span class="sim-val" data-out="stockGrowth">0%</span>
        </div>
      </div>
      <div class="sim-out">
        <p class="sim-reach"><span id="sim-visits" class="sim-reach-num">—</span><span class="sim-reach-unit">枚/月</span></p>
        <p class="sim-reach-cap">スライダー条件での到達枚数</p>
        <div class="sim-progress" role="img" aria-label="目標に対する達成率">
          <div class="sim-progress-head">
            <span class="sim-progress-label">目標に対する達成率</span>
            <span class="sim-progress-pct" id="sim-pct">—%</span>
          </div>
          <div class="sim-progress-track">
            <div class="sim-progress-fill" id="sim-fill"></div>
            <div class="sim-progress-goal" title="目標 100%"></div>
          </div>
        </div>
        <p id="sim-need"></p>
      </div>`;
    root.querySelectorAll("[data-sim]").forEach((input) => {
      input.addEventListener("input", updateSimulator);
    });
  }
  updateSimulator();
}

function leversFromDom(root) {
  const gate = Number(root.querySelector('[data-sim="gateGrowth"]').value) / 100;
  const nongateMult = Number(root.querySelector('[data-sim="nongateMult"]').value) / 10;
  const freq = Number(root.querySelector('[data-sim="freqGrowth"]').value) / 100;
  const stock = Number(root.querySelector('[data-sim="stockGrowth"]').value) / 100;
  root.querySelector('[data-out="gateGrowth"]').textContent = `${Math.round(gate * 100)}%`;
  root.querySelector('[data-out="nongateMult"]').textContent = `×${nongateMult.toFixed(1)}`;
  root.querySelector('[data-out="freqGrowth"]').textContent = `${Math.round(freq * 100)}%`;
  root.querySelector('[data-out="stockGrowth"]').textContent = `${Math.round(stock * 100)}%`;
  return { gateGrowth: gate, nongateMult, freqGrowth: freq, stockGrowth: stock };
}

function updateSimulator() {
  const root = document.getElementById("growth-simulator");
  if (!root || !DATA) return;
  const inp = currentInputs();
  const levers = leversFromDom(root);
  const out = simulateLevers(inp, levers);
  const pct = Math.min(100, Math.max(0, out.reachRatio * 100));
  const visitsEl = document.getElementById("sim-visits");
  if (visitsEl) visitsEl.textContent = fmt(Math.round(out.visits));
  const pctEl = document.getElementById("sim-pct");
  if (pctEl) pctEl.textContent = `${Math.round(pct)}%`;
  const fill = document.getElementById("sim-fill");
  if (fill) {
    fill.style.width = `${pct}%`;
    fill.classList.toggle("is-ok", pct >= 100);
  }
  const need = document.getElementById("sim-need");
  if (need) {
    need.textContent = `門前以外だけで目標（${fmt(inp.target_monthly)}枚）に届くには ×${out.needNongateMult.toFixed(1)} が必要です。`;
  }
  void simulateScenarios(inp);
}

async function boot() {
  if (document.body.hasAttribute("data-explore")) return;
  try {
    DATA = await loadExploreData();
  } catch (err) {
    console.error(err);
    return;
  }
  subscribe(() => {
    drawAll();
    mountSimulator();
  });
  drawAll();
  mountSimulator();
  void kpis;
}

boot();
