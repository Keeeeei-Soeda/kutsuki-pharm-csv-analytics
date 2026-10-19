/** データ探索ページ。フィルタ変更で全ブロックを更新する。 */

import { loadExploreData } from "../data.js";
import { getAssumptions, getFilters, setFilters, subscribe } from "../store.js";
import {
  clinicRanking,
  deptRanking,
  distanceBreakdown,
  eventWindows,
  kpis,
  monthlyStacked,
  rankedList,
} from "../aggregate.js";
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

const AXIS_PLAIN = { 隣の2院: "隣の2院", それ以外: "それ以外の医院", 不明: "不明", 門前型: "隣の2院", 非門前型: "それ以外の医院" };

let DATA = null;
let stackBy = "axis";
let rankN = 10;
let tableSort = { key: "n", dir: -1 };
let eventId = "";
let eventWeeks = 8;

function fmt(n, digits = 0) {
  if (n == null || Number.isNaN(n)) return "—";
  return Number(n).toLocaleString("ja-JP", { maximumFractionDigits: digits });
}

function pct(n) {
  if (n == null || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(0)}%`;
}

function note(suppressed) {
  return suppressed ? "一部5件未満を除く" : "";
}

function bindSave(btn, canvas, name) {
  if (!btn) return;
  btn.onclick = () => savePng(canvas, name);
}

function renderKpis() {
  const box = document.getElementById("explore-kpis");
  if (!box || !DATA) return;
  const f = getFilters();
  const a = getAssumptions();
  const k = kpis(DATA, f, a, DATA.dims);
  const cmp = k.compare;
  const cards = [
    {
      label: "期間内の処方箋",
      value: `${fmt(k.sum)}枚`,
      sub: `月平均 ${fmt(k.mean, 0)}枚（${k.months}か月）`,
      compare: cmp ? `比較期間 ${fmt(cmp.sum)}枚。${cmp.sumText}` : "",
      tone: "neutral",
    },
    {
      label: "現状（直近の平均）",
      value: `${fmt(k.recentMean, 0)}枚/月`,
      sub: `直近${a.recentMonths}か月`,
      compare: `目標まで ${k.gap > 0 ? "あと" : ""}${fmt(Math.abs(k.gap), 0)}枚`,
      tone: k.gap > 0 ? "bad" : "good",
    },
    {
      label: "初回の割合",
      value: pct(k.firstShare),
      sub: "期間内の受診のうち、その患者の初回",
      compare: "",
      tone: "neutral",
    },
    {
      label: "90日再来率",
      value: pct(k.retention),
      sub: k.ignoredClinicForRetention ? "クリニック条件は再来率に含めていません" : "初回から90日以内にもう一度来た人",
      compare: "",
      tone: "neutral",
    },
    {
      label: "上位2院の割合",
      value: pct(k.top2),
      sub: "期間内の処方箋に占める上位2院",
      compare: "",
      tone: k.top2 && k.top2 > 0.5 ? "bad" : "neutral",
    },
  ];
  if (cmp) {
    cards.push({
      label: "比較期間の月平均",
      value: `${fmt(cmp.mean, 0)}枚/月`,
      sub: `${f.fromB}〜${f.toB}`,
      compare: `この期間の月平均は${cmp.meanText}`,
      tone: "neutral",
    });
  }
  box.innerHTML = cards
    .map(
      (c) =>
        `<div class="card span-4 kpi tone-${c.tone}"><div class="label">${c.label}</div><div class="value">${c.value}</div><div class="sub">${c.sub}</div>${c.compare ? `<div class="compare">${c.compare}</div>` : ""}</div>`
    )
    .join("");
  const n = document.getElementById("explore-suppress-note");
  if (n) n.hidden = !k.suppressed;
  if (n && k.suppressed) n.textContent = "人数が5人未満の組み合わせは、個人を特定できないよう表示していません。";
}

let eventsVisible = true;

function renderMonthly() {
  const canvas = document.getElementById("chart-monthly");
  if (!canvas) return;
  const f = getFilters();
  const a = getAssumptions();
  const stacked = monthlyStacked(DATA, f, stackBy);
  const keys = new Set();
  stacked.series.forEach((inner) => inner.forEach((_n, k) => keys.add(k)));
  const order = stackBy === "axis" ? DATA.dims.axes : DATA.dims.dept_order;
  const seriesKeys = (order || []).filter((k) => keys.has(k)).concat([...keys].filter((k) => !(order || []).includes(k)));
  const colors = themeColors();
  const series = seriesKeys.map((key, i) => ({
    name: AXIS_PLAIN[key] || key,
    type: "bar",
    stack: "a",
    itemStyle: { color: stackBy === "axis" ? axisColor(key) : colors.depts[i % colors.depts.length] },
    data: stacked.months.map((ym) => stacked.series.get(ym)?.get(key) || 0),
  }));
  const marks = eventsVisible
    ? eventMarks(DATA.events.events || [], stacked.months)
    : { markLine: { data: [] }, markArea: { data: [] }, list: [] };
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
    renderEventList(canvas, marks.list);
  } else {
    renderEventList(canvas, []);
  }
  if (f.compare && f.fromB && f.toB) {
    const b = monthlyStacked(DATA, { ...f, from: f.fromB, to: f.toB }, stackBy);
    const bTotal = stacked.months.map((ym) => {
      const inner = b.series.get(ym);
      if (!inner) return null;
      let s = 0;
      inner.forEach((n) => {
        s += n;
      });
      return s;
    });
    series.push({
      name: `比較期間 ${f.fromB}〜${f.toB}`,
      type: "line",
      data: bTotal,
      itemStyle: { color: colors.ink },
      lineStyle: { type: "dotted", width: 2 },
    });
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
  const cap = document.getElementById("monthly-note");
  if (cap) cap.textContent = note(stacked.suppressed);
}

function renderRank() {
  const canvas = document.getElementById("chart-clinics");
  if (!canvas) return;
  const f = getFilters();
  const { map, suppressed } = clinicRanking(DATA, f);
  const total = [...map.values()].reduce((x, y) => x + y, 0);
  const narrow = isNarrow(canvas);
  const rows = rankedList(map, DATA.dims.clinic_order).slice(0, rankN).reverse();
  const names = rows.map((r) => DATA.dims.clinics?.[r.key]?.name || r.key);
  const chart = renderChart(canvas, {
    grid: { left: 8, right: narrow ? 84 : 110, top: 16, bottom: 8, containLabel: true },
    xAxis: { type: "value", name: "枚", splitNumber: narrow ? 3 : 5 },
    yAxis: { type: "category", data: names, axisLabel: { width: narrow ? 110 : 230, overflow: "truncate" } },
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
          formatter: (p) => `${fmt(p.value)}（${total ? Math.round((p.value / total) * 100) : 0}%）`,
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
      if (!id) return;
      setFilters({ clinic: [id] });
    });
  }
  const cap = document.getElementById("clinic-note");
  if (cap) cap.textContent = note(suppressed);
}

function renderDepts() {
  const canvas = document.getElementById("chart-depts");
  if (!canvas) return;
  const f = getFilters();
  const { map, suppressed } = deptRanking(DATA, f);
  const narrow = isNarrow(canvas);
  const rows = rankedList(map, DATA.dims.dept_order).reverse();
  const chart = renderChart(canvas, {
    grid: { left: 8, right: 64, top: 16, bottom: 8, containLabel: true },
    xAxis: { type: "value", name: "枚", splitNumber: narrow ? 3 : 5 },
    yAxis: { type: "category", data: rows.map((r) => r.key) },
    series: [
      {
        type: "bar",
        data: rows.map((r) => ({ value: r.n, dept: r.key, itemStyle: { color: themeColors().accent } })),
        label: { show: true, position: "right", formatter: (p) => fmt(p.value) },
      },
    ],
    tooltip: { trigger: "item" },
  });
  if (chart) {
    chart.off("click");
    chart.on("click", (p) => {
      const dept = p.data && p.data.dept;
      if (!dept) return;
      setFilters({ dept: [dept] });
    });
  }
  const cap = document.getElementById("dept-note");
  if (cap) cap.textContent = note(suppressed);
}

function renderDistance() {
  const canvas = document.getElementById("chart-distance");
  if (!canvas) return;
  const f = getFilters();
  const { rows, suppressed } = distanceBreakdown(DATA, f, DATA.retention, DATA.dims);
  const labels = rows.map((r) => DATA.dims.dist_labels?.[r.dist] || r.dist);
  renderChart(canvas, {
    legend: { bottom: 0, data: ["枚数", "90日再来率"] },
    grid: { left: 8, right: 8, top: 40, bottom: 36, containLabel: true },
    xAxis: { type: "category", data: labels },
    yAxis: [
      { type: "value", name: "枚" },
      { type: "value", name: "再来率", min: 0, max: 1, axisLabel: { formatter: (v) => `${Math.round(v * 100)}%` } },
    ],
    series: [
      { name: "枚数", type: "bar", data: rows.map((r) => r.n), itemStyle: { color: themeColors().nongate } },
      { name: "90日再来率", type: "line", yAxisIndex: 1, data: rows.map((r) => r.rate), itemStyle: { color: themeColors().gate } },
    ],
    tooltip: {
      trigger: "axis",
      formatter: (params) => {
        const lines = (Array.isArray(params) ? params : [params]).map((p) => {
          if (p.seriesName === "90日再来率") {
            return `${p.marker}${p.seriesName}: ${p.value == null ? "—" : `${Math.round(p.value * 100)}%`}`;
          }
          return `${p.marker}${p.seriesName}: ${fmt(p.value)}枚`;
        });
        const title = (Array.isArray(params) ? params[0] : params)?.axisValueLabel || "";
        return `${title}<br/>${lines.join("<br/>")}`;
      },
    },
  });
  const cap = document.getElementById("dist-note");
  if (cap) cap.textContent = note(suppressed);
}

function renderTable() {
  const wrap = document.getElementById("explore-table");
  if (!wrap) return;
  const f = getFilters();
  const { map } = clinicRanking(DATA, f);
  const depts = deptRanking(DATA, f).map;
  const rows = rankedList(map, DATA.dims.clinic_order).map((r) => {
    const meta = DATA.dims.clinics?.[r.key] || {};
    return { id: r.key, name: meta.name || r.key, dept: meta.dept || "—", n: r.n };
  });
  rows.sort((a, b) => {
    const va = a[tableSort.key];
    const vb = b[tableSort.key];
    if (va < vb) return -1 * tableSort.dir;
    if (va > vb) return 1 * tableSort.dir;
    return 0;
  });
  wrap.innerHTML = `<table><thead><tr>
    <th data-sort="name">クリニック</th>
    <th data-sort="dept">主科</th>
    <th class="num" data-sort="n">処方箋（枚）</th>
  </tr></thead><tbody>${rows
    .map((r) => `<tr><td>${r.name}</td><td>${r.dept || "—"}</td><td class="num">${fmt(r.n)}</td></tr>`)
    .join("")}</tbody></table>`;
  wrap.querySelectorAll("th[data-sort]").forEach((th) => {
    th.style.cursor = "pointer";
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-sort");
      tableSort = { key, dir: tableSort.key === key ? -tableSort.dir : -1 };
      renderTable();
    });
  });
  const dl = document.getElementById("explore-csv");
  if (dl) {
    dl.onclick = () => {
      const header = "クリニック,主科,処方箋枚数\n";
      const body = rows.map((r) => `${csvCell(r.name)},${csvCell(r.dept)},${r.n}`).join("\n");
      const blob = new Blob([header + body], { type: "text/csv;charset=utf-8" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "explore.csv";
      a.click();
    };
  }
  void depts;
}

function csvCell(v) {
  const s = String(v ?? "");
  if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

function renderEvents() {
  const sel = document.getElementById("event-select");
  const out = document.getElementById("event-compare");
  if (!sel || !out) return;
  const events = DATA.events.events || [];
  if (!sel.dataset.ready) {
    sel.innerHTML = `<option value="">施策を選ぶ</option>` + events.map((e) => `<option value="${e.id}">${e.name}</option>`).join("");
    sel.dataset.ready = "1";
    sel.addEventListener("change", () => {
      eventId = sel.value;
      renderEvents();
    });
    document.querySelectorAll("[data-event-weeks]").forEach((btn) => {
      btn.addEventListener("click", () => {
        eventWeeks = Number(btn.getAttribute("data-event-weeks"));
        renderEvents();
      });
    });
  }
  const ev = events.find((e) => e.id === eventId);
  if (!ev) {
    out.innerHTML = "<p>施策を選ぶと、開始前と開始後の週あたり枚数を並べます。前後を並べただけで、効いたかどうかの判定ではありません（判定は Phase 5）。</p>";
    return;
  }
  const f = getFilters();
  const w = eventWindows(DATA.weekly, ev, eventWeeks, f.axis);
  const hasEst = ev.design === "flyer_did" || ev.design === "its";
  const link = hasEst ? `<p><a href="phase5_causal.html">Phase 5 の推定結果を見る</a></p>` : "";
  const delta =
    w && w.delta != null
      ? w.delta > 0
        ? `開始後のほうが週あたり ${fmt(Math.abs(w.delta), 1)}枚 多い`
        : w.delta < 0
          ? `開始後のほうが週あたり ${fmt(Math.abs(w.delta), 1)}枚 少ない`
          : "開始前後で同じ"
      : "前後の週が足りず比べられない";
  out.innerHTML = `<p><strong>${ev.name}</strong>（${ev.start}${ev.end ? "〜" + ev.end : ""}）</p>
    <p>開始前${eventWeeks}週の週あたり ${w?.beforeMean != null ? fmt(w.beforeMean, 1) : "—"}枚 ／ 開始後${eventWeeks}週の週あたり ${w?.afterMean != null ? fmt(w.afterMean, 1) : "—"}枚。</p>
    <p>${delta}。</p>${link}
    <p class="caption">前後を並べただけで、効いたかどうかの判定ではありません（判定は Phase 5）。</p>`;
}

function renderAll() {
  if (!DATA) return;
  renderKpis();
  renderMonthly();
  renderRank();
  renderDepts();
  renderDistance();
  renderTable();
  renderEvents();
}

function wireControls() {
  document.querySelectorAll("[data-stack]").forEach((btn) => {
    btn.addEventListener("click", () => {
      stackBy = btn.getAttribute("data-stack");
      renderMonthly();
    });
  });
  const slider = document.getElementById("rank-n");
  if (slider) {
    slider.addEventListener("input", () => {
      rankN = Number(slider.value);
      const lab = document.getElementById("rank-n-label");
      if (lab) lab.textContent = String(rankN);
      renderRank();
    });
  }
  document.getElementById("toggle-events")?.addEventListener("click", () => {
    eventsVisible = !eventsVisible;
    renderMonthly();
  });
  bindSave(document.getElementById("save-monthly"), document.getElementById("chart-monthly"), "monthly.png");
  bindSave(document.getElementById("save-clinics"), document.getElementById("chart-clinics"), "clinics.png");
  bindSave(document.getElementById("save-depts"), document.getElementById("chart-depts"), "depts.png");
  bindSave(document.getElementById("save-distance"), document.getElementById("chart-distance"), "distance.png");
  document.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const kind = btn.getAttribute("data-preset");
      const max = DATA?.dims?.period?.max?.slice(0, 7) || "";
      const min = DATA?.dims?.period?.min?.slice(0, 7) || "";
      let from6 = min;
      if (max) {
        const y = Number(max.slice(0, 4));
        const m = Number(max.slice(5, 7));
        const d = new Date(y, m - 6, 1);
        from6 = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      }
      if (kind === "other") setFilters({ axis: ["それ以外"], dept: [], clinic: [], visitType: "all", from: min, to: max });
      if (kind === "intern") setFilters({ axis: [], dept: ["内科"], clinic: [], visitType: "all", from: min, to: max });
      if (kind === "first6") setFilters({ axis: [], dept: [], clinic: [], visitType: "初回", from: from6, to: max });
    });
  });
}

async function boot() {
  if (!document.body.hasAttribute("data-explore")) return;
  DATA = await loadExploreData();
  wireControls();
  subscribe(renderAll);
  renderAll();
}

boot();
