/** 既存ページの data-chart と Phase 3 シミュレーターを描画する。 */

import { loadExploreData } from "../data.js";
import { getAssumptions, getFilters, setFilters, subscribe } from "../store.js";
import { clinicRanking, distanceBreakdown, kpis, monthlyStacked, rankedList, retentionRate } from "../aggregate.js";
import { axisColor, renderChart, savePng, themeColors } from "../charts.js";
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
  if (series[0]) {
    series[0].markLine = {
      symbol: "none",
      data: [{ yAxis: a.targetMonthly, name: "目標", lineStyle: { color: colors.target, type: "dashed" }, label: { formatter: "目標" } }],
    };
  }
  renderChart(canvas, {
    xAxis: { type: "category", data: stacked.months, axisLabel: { rotate: 45 } },
    yAxis: { type: "value", name: "枚" },
    series,
  });
}

function drawClinics(canvas, spec) {
  const f = getFilters();
  const { map } = clinicRanking(DATA, f);
  const n = spec.top || 10;
  const rows = rankedList(map, DATA.dims.clinic_order).slice(0, n).reverse();
  const chart = renderChart(canvas, {
    grid: { left: 140, right: 48, top: 8, bottom: 24 },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: rows.map((r) => DATA.dims.clinics?.[r.key]?.name || r.key) },
    series: [
      {
        type: "bar",
        data: rows.map((r) => ({
          value: r.n,
          clinicId: r.key,
          itemStyle: { color: DATA.dims.clinics?.[r.key]?.gate ? themeColors().gate : themeColors().nongate },
        })),
      },
    ],
    tooltip: { trigger: "item" },
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
        <label>門前の増加率 <input type="range" min="0" max="50" value="0" data-sim="gateGrowth"/><span data-out="gateGrowth">0%</span></label>
        <label>非門前の倍率 <input type="range" min="10" max="50" value="10" data-sim="nongateMult"/><span data-out="nongateMult">×1.0</span></label>
        <label>来局頻度の増加率 <input type="range" min="0" max="50" value="0" data-sim="freqGrowth"/><span data-out="freqGrowth">0%</span></label>
        <label>活動患者の増加率 <input type="range" min="0" max="50" value="0" data-sim="stockGrowth"/><span data-out="stockGrowth">0%</span></label>
      </div>
      <div class="sim-out">
        <div class="chart-canvas" id="sim-gauge" style="height:220px"></div>
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
  const colors = themeColors();
  const pct = Math.min(100, Math.max(0, out.reachRatio * 100));
  renderChart(document.getElementById("sim-gauge"), {
    series: [
      {
        type: "gauge",
        min: 0,
        max: 100,
        axisLine: { lineStyle: { width: 14, color: [[0.7, colors.muted], [1, colors.accent]] } },
        pointer: { width: 4 },
        detail: { formatter: () => `${fmt(out.visits)}枚`, fontSize: 18 },
        data: [{ value: pct, name: "目標比" }],
      },
    ],
  });
  const need = document.getElementById("sim-need");
  if (need) {
    need.textContent = `非門前だけで目標に届くには ×${out.needNongateMult.toFixed(1)} が必要です。達成率 ${Math.round(out.reachRatio * 100)}%。`;
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
