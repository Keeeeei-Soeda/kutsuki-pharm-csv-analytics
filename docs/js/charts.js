/** ECharts テーマと共通ラッパ。 */

const instances = new Map();

export function cssVar(name, fallback) {
  if (typeof getComputedStyle === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function themeColors() {
  return {
    gate: cssVar("--gate", "#c45c26"),
    nongate: cssVar("--nongate", "#2f6f9f"),
    accent: cssVar("--accent", "#0f7c74"),
    ink: cssVar("--ink", "#1b2430"),
    muted: cssVar("--muted", "#5b6776"),
    line: cssVar("--line", "#e1e6eb"),
    target: cssVar("--warn", "#b4540a"),
    surface: cssVar("--surface", "#ffffff"),
    unknown: "#9aa5b1",
    depts: ["#2f6f9f", "#6aa84f", "#c45c26", "#b5651d", "#7b5ea7", "#0f8a8a", "#8a6d3b", "#c0587e", "#5c6675", "#3f7d6d", "#9a8f7c", "#88a0b5", "#b9b1a2"],
  };
}

export function axisColor(axis) {
  const c = themeColors();
  if (axis === "門前型") return c.gate;
  if (axis === "非門前型") return c.nongate;
  return c.unknown;
}

function applyTheme(option) {
  const c = themeColors();
  const base = {
    textStyle: { color: c.ink, fontFamily: cssVar("--sans", "sans-serif") },
    grid: { left: 48, right: 24, top: 32, bottom: 48, containLabel: true },
    tooltip: { trigger: "axis", backgroundColor: c.surface, borderColor: c.line, textStyle: { color: c.ink } },
    legend: { top: 0, textStyle: { color: c.muted } },
  };
  return { ...base, ...option, textStyle: { ...base.textStyle, ...(option.textStyle || {}) } };
}

export function getChart(el) {
  if (!el) return null;
  if (typeof echarts === "undefined") return null;
  if (!instances.has(el)) {
    const chart = echarts.init(el);
    instances.set(el, chart);
  }
  return instances.get(el);
}

export function renderChart(el, option) {
  const chart = getChart(el);
  if (!chart) return null;
  chart.setOption(applyTheme(option), true);
  return chart;
}

export function resizeAll() {
  instances.forEach((c) => c.resize());
}

export function savePng(el, filename) {
  const chart = getChart(el);
  if (!chart) return;
  const url = chart.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#ffffff" });
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "chart.png";
  a.click();
}

if (typeof window !== "undefined") {
  window.addEventListener("resize", () => resizeAll());
}
