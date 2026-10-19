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
  const out = { ...base, ...option, textStyle: { ...base.textStyle, ...(option.textStyle || {}) } };
  // 狭い画面でも目盛りの文字が重ならないよう、重なる目盛りは自動で間引く
  out.xAxis = withAxisDefaults(out.xAxis, c);
  out.yAxis = withAxisDefaults(out.yAxis, c);
  out.tooltip = { confine: true, ...(out.tooltip || {}) };
  return out;
}

function withAxisDefaults(axis, c) {
  if (!axis) return axis;
  const one = (a) => ({
    ...a,
    axisLabel: { hideOverlap: true, color: c.muted, ...(a.axisLabel || {}) },
    nameTextStyle: { color: c.muted, ...(a.nameTextStyle || {}) },
  });
  return Array.isArray(axis) ? axis.map(one) : one(axis);
}

/** 狭い画面（スマホ）かどうか。図の余白やラベル幅の切り替えに使う。 */
export function isNarrow(el) {
  const w = el && el.clientWidth ? el.clientWidth : typeof window !== "undefined" ? window.innerWidth : 1200;
  return w < 560;
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

/** 目標線が図の外に出て見えなくならないよう、縦軸の上限を目標値まで広げる。 */
export function maxWithTarget(target) {
  return (v) => {
    const top = Math.max(v.max, (target || 0) * 1.04);
    if (top > 2000) {
      // 目盛りの間隔（呼び出し側の interval と同じ式）の整数倍にして、最上段だけ半端な目盛りになるのを防ぐ
      const step = Math.ceil(((target || 0) * 1.04) / 7 / 500) * 500 || 500;
      return Math.ceil(top / step) * step;
    }
    const step = top > 200 ? 100 : 10;
    return Math.ceil(top / step) * step;
  };
}

const CIRCLED = ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩", "⑪", "⑫"];

/**
 * 施策イベントを番号付きの縦線・網掛けにする。
 * 図の上に施策名を直接書くと凡例や隣のラベルと重なるため、図には番号だけを出し、
 * 名前は図の下の一覧（renderEventList）に並べる。
 */
export function eventMarks(events, months) {
  const c = themeColors();
  const inRange = (ym) => !months || months.includes(ym);
  const line = [];
  const area = [];
  const list = [];
  (events || []).forEach((ev, i) => {
    const no = CIRCLED[i] || String(i + 1);
    const s = (ev.start || "").slice(0, 7);
    const e = (ev.end || "").slice(0, 7);
    if (!inRange(s)) return;
    list.push({ no, name: ev.name, start: ev.start, end: ev.end });
    const label = { show: true, formatter: no, color: c.target, fontWeight: 700, fontSize: 12 };
    if (e && e !== s && inRange(e)) {
      area.push([{ xAxis: s, name: no, label: { ...label, position: "insideTop" }, itemStyle: { color: "rgba(180,84,10,0.08)" } }, { xAxis: e }]);
    } else {
      line.push({ xAxis: s, name: ev.name, label: { ...label, position: "end" }, lineStyle: { color: c.target, type: "dashed", width: 1 } });
    }
  });
  return {
    markLine: { symbol: "none", silent: false, data: line },
    markArea: { silent: false, data: area },
    list,
  };
}

/** 図の下に「① 春ポスティング …」の一覧を出す（無ければ作る）。 */
export function renderEventList(canvas, list) {
  if (!canvas || !canvas.parentNode) return;
  let ul = canvas.parentNode.querySelector(":scope > .chart-events");
  if (!list || !list.length) {
    if (ul) ul.remove();
    return;
  }
  if (!ul) {
    ul = document.createElement("ul");
    ul.className = "chart-events";
    canvas.insertAdjacentElement("afterend", ul);
  }
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  ul.innerHTML = list
    .map((e) => `<li><b>${e.no}</b>${esc(e.name)}（${esc(e.start)}${e.end && e.end !== e.start ? "〜" + esc(e.end) : "〜"}）</li>`)
    .join("");
}

if (typeof window !== "undefined") {
  window.addEventListener("resize", () => resizeAll());
}
