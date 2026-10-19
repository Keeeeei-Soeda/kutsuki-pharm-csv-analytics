/** フィルタ・前提値の状態。URL クエリと localStorage で全ページ共有。 */

const FILTER_KEY = "kutsuki-explore-filters";
const ASSUMPTION_KEY = "kutsuki-explore-assumptions";

export function emptyFilters() {
  return {
    from: "",
    to: "",
    axis: [],
    dept: [],
    clinic: [],
    dist: [],
    visitType: "all",
    compare: false,
    fromB: "",
    toB: "",
  };
}

export function defaultAssumptions() {
  return { targetMonthly: 3000, recentMonths: 3, marginYen: 2000 };
}

const listeners = new Set();
let filters = emptyFilters();
let assumptions = defaultAssumptions();
let ready = false;

export function getFilters() {
  return filters;
}

export function getAssumptions() {
  return assumptions;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function emit() {
  listeners.forEach((fn) => fn({ filters, assumptions }));
}

function csv(v) {
  return Array.isArray(v) ? v.filter(Boolean).join(",") : "";
}

function split(v) {
  if (!v) return [];
  return String(v)
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

export function filtersToQuery(f) {
  const q = new URLSearchParams();
  if (f.from) q.set("from", f.from);
  if (f.to) q.set("to", f.to);
  if (f.axis && f.axis.length) q.set("axis", csv(f.axis));
  if (f.dept && f.dept.length) q.set("dept", csv(f.dept));
  if (f.clinic && f.clinic.length) q.set("clinic", csv(f.clinic));
  if (f.dist && f.dist.length) q.set("dist", csv(f.dist));
  if (f.visitType && f.visitType !== "all") q.set("visit", f.visitType);
  if (f.compare) {
    q.set("compare", "1");
    if (f.fromB) q.set("fromB", f.fromB);
    if (f.toB) q.set("toB", f.toB);
  }
  return q;
}

export function queryToFilters(search) {
  const q = new URLSearchParams(search.replace(/^\?/, ""));
  const f = emptyFilters();
  if (q.has("from")) f.from = q.get("from") || "";
  if (q.has("to")) f.to = q.get("to") || "";
  if (q.has("axis")) f.axis = split(q.get("axis"));
  if (q.has("dept")) f.dept = split(q.get("dept"));
  if (q.has("clinic")) f.clinic = split(q.get("clinic"));
  if (q.has("dist")) f.dist = split(q.get("dist"));
  if (q.has("visit")) f.visitType = q.get("visit") || "all";
  f.compare = q.get("compare") === "1";
  if (q.has("fromB")) f.fromB = q.get("fromB") || "";
  if (q.has("toB")) f.toB = q.get("toB") || "";
  return f;
}

function readStorage(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    return { ...fallback, ...JSON.parse(raw) };
  } catch (_e) {
    return fallback;
  }
}

function writeStorage(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (_e) {
    /* ignore quota / private mode */
  }
}

function hasQuery(search) {
  const q = new URLSearchParams(search.replace(/^\?/, ""));
  return [...q.keys()].some((k) =>
    ["from", "to", "axis", "dept", "clinic", "dist", "visit", "compare", "fromB", "toB"].includes(k)
  );
}

export function writeUrl(f = filters) {
  if (typeof history === "undefined" || typeof location === "undefined") return;
  const q = filtersToQuery(f).toString();
  const url = q ? `${location.pathname}?${q}${location.hash}` : `${location.pathname}${location.hash}`;
  history.replaceState(null, "", url);
}

export function setFilters(partial, opts = {}) {
  const persist = opts.persist !== false;
  const pushUrl = opts.pushUrl !== false;
  filters = { ...filters, ...partial };
  if (persist) writeStorage(FILTER_KEY, filters);
  if (pushUrl) writeUrl(filters);
  emit();
}

export function resetFilters(period = {}) {
  setFilters({ ...emptyFilters(), ...period });
}

export function setAssumptions(partial) {
  assumptions = { ...assumptions, ...partial };
  writeStorage(ASSUMPTION_KEY, assumptions);
  emit();
}

export function resetAssumptions(defaults) {
  assumptions = { ...defaultAssumptions(), ...(defaults || {}) };
  writeStorage(ASSUMPTION_KEY, assumptions);
  emit();
}

export function hydrate({ dims, params } = {}) {
  if (ready) {
    emit();
    return;
  }
  const periodMin = dims?.period?.min?.slice(0, 7) || "";
  const periodMax = dims?.period?.max?.slice(0, 7) || "";
  const stored = readStorage(FILTER_KEY, emptyFilters());
  const fromQuery = typeof location !== "undefined" && hasQuery(location.search);
  filters = fromQuery ? queryToFilters(location.search) : stored;
  if (!filters.from) filters.from = periodMin;
  if (!filters.to) filters.to = periodMax;
  const storedA = readStorage(ASSUMPTION_KEY, defaultAssumptions());
  assumptions = {
    targetMonthly: Number(storedA.targetMonthly) || params?.target_monthly || 3000,
    recentMonths: Number(storedA.recentMonths) || params?.recent_months || 3,
    marginYen: Number(storedA.marginYen) || params?.gross_margin_yen || 2000,
  };
  if (!fromQuery) writeUrl(filters);
  writeStorage(FILTER_KEY, filters);
  ready = true;
  emit();
}

export function isReady() {
  return ready;
}
