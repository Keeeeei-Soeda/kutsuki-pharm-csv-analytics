/** サイドバーのフィルタ UI と前提値パネル。 */

import { loadExploreData } from "./data.js";
import {
  getAssumptions,
  getFilters,
  hydrate,
  resetAssumptions,
  resetFilters,
  setAssumptions,
  setFilters,
  subscribe,
} from "./store.js";
import { monthsBetween, periodBounds } from "./aggregate.js";

const AXIS_LABEL = { 門前型: "門前型", 非門前型: "非門前型", 不明: "不明" };

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function optionList(values, selected) {
  return values
    .map((v) => `<option value="${escapeAttr(v)}"${v === selected ? " selected" : ""}>${escapeHtml(v)}</option>`)
    .join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, "&quot;");
}

function chipGroup(name, items, selected, labels) {
  return items
    .map((v) => {
      const on = selected.includes(v);
      const lab = (labels && labels[v]) || v;
      return `<label class="sb-chip${on ? " is-on" : ""}"><input type="checkbox" data-filter="${name}" value="${escapeAttr(v)}"${on ? " checked" : ""}/>${escapeHtml(lab)}</label>`;
    })
    .join("");
}

function monthsOf(dims) {
  const { min, max } = periodBounds(dims);
  return monthsBetween(min, max);
}

function fillRoot(dims, params) {
  const root = document.getElementById("sb-filters-root");
  const assume = document.getElementById("sb-assumptions");
  if (!root) return;
  const f = getFilters();
  const a = getAssumptions();
  const months = monthsOf(dims);
  const depts = dims.dept_order || [];
  const dists = dims.dist_order || [];
  const distLabels = dims.dist_labels || {};
  const clinics = dims.clinic_order || [];

  root.innerHTML = "";
  root.appendChild(
    el(`<div class="sb-filter-block">
      <p class="sb-filter-label">期間</p>
      <div class="sb-filter-row">
        <select data-role="from" aria-label="開始月">${optionList(months, f.from)}</select>
        <span>〜</span>
        <select data-role="to" aria-label="終了月">${optionList(months, f.to)}</select>
      </div>
      <div class="sb-presets" role="group" aria-label="期間プリセット">
        <button type="button" data-preset="3">直近3か月</button>
        <button type="button" data-preset="6">直近6か月</button>
        <button type="button" data-preset="12">直近12か月</button>
        <button type="button" data-preset="all">全期間</button>
      </div>
    </div>`)
  );
  root.appendChild(
    el(`<div class="sb-filter-block">
      <p class="sb-filter-label">区分</p>
      <div class="sb-chip-row">${chipGroup("axis", dims.axes || ["門前型", "非門前型", "不明"], f.axis, AXIS_LABEL)}</div>
    </div>`)
  );
  root.appendChild(
    el(`<div class="sb-filter-block">
      <p class="sb-filter-label">診療科</p>
      <div class="sb-chip-row sb-chip-row-wrap">${chipGroup("dept", depts, f.dept)}</div>
    </div>`)
  );
  const clinicOpts = clinics
    .map((id) => {
      const name = dims.clinics?.[id]?.name || id;
      const on = f.clinic.includes(id);
      return `<label class="sb-check"><input type="checkbox" data-filter="clinic" value="${escapeAttr(id)}"${on ? " checked" : ""}/><span>${escapeHtml(name)}</span></label>`;
    })
    .join("");
  root.appendChild(
    el(`<div class="sb-filter-block">
      <p class="sb-filter-label">クリニック</p>
      <input type="search" data-role="clinic-search" placeholder="名称で検索" aria-label="クリニックを検索"/>
      <div class="sb-clinic-list">${clinicOpts}</div>
    </div>`)
  );
  root.appendChild(
    el(`<div class="sb-filter-block">
      <p class="sb-filter-label">距離帯</p>
      <div class="sb-chip-row">${chipGroup("dist", dists, f.dist, distLabels)}</div>
    </div>`)
  );
  root.appendChild(
    el(`<div class="sb-filter-block">
      <p class="sb-filter-label">初回 / 再来</p>
      <div class="sb-radio-row">
        ${["all", "初回", "再来"]
          .map((v) => {
            const lab = v === "all" ? "全て" : v;
            return `<label class="sb-chip${f.visitType === v ? " is-on" : ""}"><input type="radio" name="visitType" value="${v}"${f.visitType === v ? " checked" : ""}/>${lab}</label>`;
          })
          .join("")}
      </div>
    </div>`)
  );
  root.appendChild(
    el(`<div class="sb-filter-block sb-compare-block">
      <label class="sb-toggle"><input type="checkbox" data-role="compare"${f.compare ? " checked" : ""}/>比較する</label>
      <div class="sb-filter-row" data-role="compare-range"${f.compare ? "" : " hidden"}>
        <select data-role="fromB" aria-label="比較開始月">${optionList(months, f.fromB || months[0])}</select>
        <span>〜</span>
        <select data-role="toB" aria-label="比較終了月">${optionList(months, f.toB || months[Math.max(0, months.length - 4)])}</select>
      </div>
    </div>`)
  );
  root.appendChild(el(`<button type="button" class="sb-reset" data-role="reset">リセット</button>`));

  if (assume) {
    assume.innerHTML = `<p class="sb-heading">前提値</p>
      <label class="sb-field">目標枚数 / 月
        <input type="number" min="1" step="50" data-assume="targetMonthly" value="${a.targetMonthly}"/>
      </label>
      <label class="sb-field">現状の直近月数
        <input type="number" min="1" max="6" step="1" data-assume="recentMonths" value="${a.recentMonths}"/>
      </label>
      <label class="sb-field">1受診あたり粗利（円）
        <input type="number" min="0" step="100" data-assume="marginYen" value="${a.marginYen}"/>
      </label>
      <button type="button" class="sb-reset" data-role="reset-assume">既定に戻す</button>`;
  }

  bind(root, assume, dims, params);
  renderStatus(dims);
}

function syncForm(dims) {
  const root = document.getElementById("sb-filters-root");
  const assume = document.getElementById("sb-assumptions");
  if (!root) return;
  const f = getFilters();
  const a = getAssumptions();
  const setVal = (sel, v) => {
    const node = root.querySelector(sel);
    if (node && v && node.value !== v) node.value = v;
  };
  setVal('[data-role="from"]', f.from);
  setVal('[data-role="to"]', f.to);
  setVal('[data-role="fromB"]', f.fromB);
  setVal('[data-role="toB"]', f.toB);
  const cmp = root.querySelector('[data-role="compare"]');
  const range = root.querySelector('[data-role="compare-range"]');
  if (cmp) cmp.checked = !!f.compare;
  if (range) range.hidden = !f.compare;
  root.querySelectorAll("input[data-filter]").forEach((input) => {
    const name = input.getAttribute("data-filter");
    const selected = f[name] || [];
    input.checked = selected.includes(input.value);
    input.closest(".sb-chip")?.classList.toggle("is-on", input.checked);
  });
  root.querySelectorAll('input[name="visitType"]').forEach((input) => {
    input.checked = input.value === f.visitType;
    input.closest(".sb-chip")?.classList.toggle("is-on", input.checked);
  });
  if (assume) {
    assume.querySelectorAll("[data-assume]").forEach((input) => {
      const key = input.getAttribute("data-assume");
      if (document.activeElement !== input) input.value = a[key];
    });
  }
  renderStatus(dims);
}

function lastN(dims, n) {
  const months = monthsOf(dims);
  const slice = months.slice(-n);
  return { from: slice[0], to: slice[slice.length - 1] };
}

function bind(root, assume, dims, params) {
  root.querySelector('[data-role="from"]').addEventListener("change", (e) => setFilters({ from: e.target.value }));
  root.querySelector('[data-role="to"]').addEventListener("change", (e) => setFilters({ to: e.target.value }));
  root.querySelectorAll("[data-preset]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const p = btn.getAttribute("data-preset");
      const { min, max } = periodBounds(dims);
      if (p === "all") setFilters({ from: min, to: max });
      else setFilters(lastN(dims, Number(p)));
    });
  });
  root.querySelectorAll("input[data-filter]").forEach((input) => {
    input.addEventListener("change", () => {
      const name = input.getAttribute("data-filter");
      const values = [...root.querySelectorAll(`input[data-filter="${name}"]:checked`)].map((i) => i.value);
      setFilters({ [name]: values });
    });
  });
  root.querySelectorAll('input[name="visitType"]').forEach((input) => {
    input.addEventListener("change", () => setFilters({ visitType: input.value }));
  });
  const search = root.querySelector('[data-role="clinic-search"]');
  if (search) {
    search.addEventListener("input", () => {
      const q = search.value.trim();
      root.querySelectorAll(".sb-clinic-list .sb-check").forEach((lab) => {
        lab.hidden = q && !lab.textContent.includes(q);
      });
    });
  }
  const cmp = root.querySelector('[data-role="compare"]');
  const range = root.querySelector('[data-role="compare-range"]');
  cmp.addEventListener("change", () => {
    range.hidden = !cmp.checked;
    setFilters({ compare: cmp.checked });
  });
  root.querySelector('[data-role="fromB"]').addEventListener("change", (e) => setFilters({ fromB: e.target.value }));
  root.querySelector('[data-role="toB"]').addEventListener("change", (e) => setFilters({ toB: e.target.value }));
  root.querySelector('[data-role="reset"]').addEventListener("click", () => {
    const { min, max } = periodBounds(dims);
    resetFilters({ from: min, to: max });
  });
  if (assume) {
    assume.querySelectorAll("[data-assume]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.getAttribute("data-assume");
        setAssumptions({ [key]: Number(input.value) });
      });
    });
    assume.querySelector('[data-role="reset-assume"]').addEventListener("click", () => {
      resetAssumptions({
        targetMonthly: params.target_monthly,
        recentMonths: params.recent_months,
        marginYen: params.gross_margin_yen,
      });
    });
  }
}

function chipLabel(key, value, dims) {
  if (key === "axis") return value;
  if (key === "dept") return value;
  if (key === "dist") return dims.dist_labels?.[value] || value;
  if (key === "clinic") return dims.clinics?.[value]?.name || value;
  if (key === "visitType") return value;
  if (key === "period") return `${value.from}〜${value.to}`;
  if (key === "compare") return `比較 ${value.fromB}〜${value.toB}`;
  return String(value);
}

function renderStatus(dims) {
  let bar = document.getElementById("explore-status");
  if (!bar) {
    const main = document.getElementById("main");
    if (!main) return;
    bar = document.createElement("div");
    bar.id = "explore-status";
    bar.className = "explore-status";
    const hero = main.querySelector(".hero");
    if (hero && hero.nextSibling) main.insertBefore(bar, hero.nextSibling);
    else main.prepend(bar);
  }
  const f = getFilters();
  const { min, max } = periodBounds(dims);
  const chips = [];
  if (f.from && f.to && (f.from !== min || f.to !== max)) {
    chips.push({ key: "period", label: chipLabel("period", f, dims) });
  }
  (f.axis || []).forEach((v) => chips.push({ key: "axis", value: v, label: chipLabel("axis", v, dims) }));
  (f.dept || []).forEach((v) => chips.push({ key: "dept", value: v, label: chipLabel("dept", v, dims) }));
  (f.clinic || []).forEach((v) => chips.push({ key: "clinic", value: v, label: chipLabel("clinic", v, dims) }));
  (f.dist || []).forEach((v) => chips.push({ key: "dist", value: v, label: chipLabel("dist", v, dims) }));
  if (f.visitType && f.visitType !== "all") {
    chips.push({ key: "visitType", value: f.visitType, label: chipLabel("visitType", f.visitType, dims) });
  }
  if (f.compare) chips.push({ key: "compare", label: chipLabel("compare", f, dims) });

  const interactive = document.querySelector("[data-chart], [data-explore]");
  const note = interactive
    ? ""
    : `<p class="explore-model-note">このページの図は全期間の分析です。フィルタはデータ探索ページの図に効きます。</p>`;
  const chipHtml = chips
    .map(
      (c) =>
        `<button type="button" class="explore-chip" data-chip-key="${escapeAttr(c.key)}" data-chip-value="${escapeAttr(c.value || "")}">${escapeHtml(c.label)} <span aria-hidden="true">×</span></button>`
    )
    .join("");
  bar.innerHTML = `${note}<div class="explore-chip-row">${chipHtml}</div>`;
  bar.querySelectorAll(".explore-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.getAttribute("data-chip-key");
      const value = btn.getAttribute("data-chip-value");
      if (key === "period") {
        setFilters({ from: min, to: max });
      } else if (key === "compare") {
        setFilters({ compare: false });
      } else if (key === "visitType") {
        setFilters({ visitType: "all" });
      } else {
        const cur = getFilters()[key] || [];
        setFilters({ [key]: cur.filter((x) => x !== value) });
      }
    });
  });
}

async function boot() {
  if (!document.getElementById("sb-filters-root")) return;
  try {
    const data = await loadExploreData();
    hydrate({ dims: data.dims, params: data.params });
    fillRoot(data.dims, data.params);
    subscribe(() => syncForm(data.dims));
  } catch (err) {
    const root = document.getElementById("sb-filters-root");
    if (root) root.innerHTML = `<p class="sb-filter-error">集計データを読めませんでした。</p>`;
    console.error(err);
  }
}

boot();
