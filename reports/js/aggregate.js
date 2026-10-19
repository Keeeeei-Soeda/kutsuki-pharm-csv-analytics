/** 絞り込み・集計・KPI。DOM に触らない純関数。 */

const CUBE = { ym: 0, axis: 1, clinic: 2, dept: 3, dist: 4, visitType: 5, n: 6 };

export function monthsBetween(from, to) {
  if (!from || !to || from > to) return [];
  const out = [];
  let y = Number(from.slice(0, 4));
  let m = Number(from.slice(5, 7));
  const y2 = Number(to.slice(0, 4));
  const m2 = Number(to.slice(5, 7));
  while (y < y2 || (y === y2 && m <= m2)) {
    out.push(`${y}-${String(m).padStart(2, "0")}`);
    m += 1;
    if (m > 12) {
      m = 1;
      y += 1;
    }
  }
  return out;
}

export function periodBounds(dims) {
  return {
    min: dims?.period?.min?.slice(0, 7) || "",
    max: dims?.period?.max?.slice(0, 7) || "",
  };
}

export function isFullPeriod(filters, dims) {
  const { min, max } = periodBounds(dims);
  return (!filters.from || filters.from <= min) && (!filters.to || filters.to >= max);
}

function active(list) {
  return list && list.length ? list : null;
}

export function cubeNeeded(filters) {
  const n = [filters.axis, filters.dept, filters.clinic, filters.dist].filter((x) => x && x.length).length;
  return n > 1 || (filters.dist && filters.dist.length > 0) || (filters.visitType && filters.visitType !== "all");
}

export function rowMatches(row, filters) {
  const ym = row[CUBE.ym];
  if (filters.from && ym < filters.from) return false;
  if (filters.to && ym > filters.to) return false;
  const axis = active(filters.axis);
  if (axis && !axis.includes(row[CUBE.axis])) return false;
  const clinic = active(filters.clinic);
  if (clinic && !clinic.includes(row[CUBE.clinic])) return false;
  const dept = active(filters.dept);
  if (dept && !dept.includes(row[CUBE.dept])) return false;
  const dist = active(filters.dist);
  if (dist && !dist.includes(row[CUBE.dist])) return false;
  if (filters.visitType && filters.visitType !== "all" && row[CUBE.visitType] !== filters.visitType) {
    return false;
  }
  return true;
}

function sumPairs(rows, from, to, allowed) {
  let sum = 0;
  for (const rec of rows) {
    const ym = rec[0];
    const dim = rec.length === 2 ? null : rec[1];
    const n = rec[rec.length - 1];
    if (from && ym < from) continue;
    if (to && ym > to) continue;
    if (allowed && dim != null && !allowed.includes(dim)) continue;
    sum += Number(n) || 0;
  }
  return sum;
}

function groupPairs(rows, from, to, allowed) {
  const map = new Map();
  for (const rec of rows) {
    const ym = rec[0];
    const dim = rec[1];
    const n = rec[2];
    if (from && ym < from) continue;
    if (to && ym > to) continue;
    if (allowed && !allowed.includes(dim)) continue;
    map.set(dim, (map.get(dim) || 0) + (Number(n) || 0));
  }
  return map;
}

function monthlyPairs(rows, from, to, allowed) {
  const map = new Map();
  for (const rec of rows) {
    const ym = rec[0];
    const dim = rec[1];
    const n = rec[2];
    if (from && ym < from) continue;
    if (to && ym > to) continue;
    if (allowed && !allowed.includes(dim)) continue;
    if (!map.has(ym)) map.set(ym, new Map());
    const inner = map.get(ym);
    inner.set(dim, (inner.get(dim) || 0) + (Number(n) || 0));
  }
  return map;
}

export function sumCube(facts, filters) {
  let sum = 0;
  let suppressed = false;
  for (const row of facts.rows) {
    if (!rowMatches(row, filters)) continue;
    const n = row[CUBE.n];
    if (n == null) {
      suppressed = true;
      continue;
    }
    sum += n;
  }
  return { sum, suppressed };
}

export function groupCube(facts, filters, dimIndex) {
  const map = new Map();
  let suppressed = false;
  for (const row of facts.rows) {
    if (!rowMatches(row, filters)) continue;
    const n = row[CUBE.n];
    if (n == null) {
      suppressed = true;
      continue;
    }
    const key = dimIndex === "ym" ? row[CUBE.ym] : row[dimIndex];
    if (dimIndex === "ym+axis") {
      const ym = row[CUBE.ym];
      const axis = row[CUBE.axis];
      if (!map.has(ym)) map.set(ym, new Map());
      const inner = map.get(ym);
      inner.set(axis, (inner.get(axis) || 0) + n);
    } else if (dimIndex === "ym+dept") {
      const ym = row[CUBE.ym];
      const dept = row[CUBE.dept];
      if (!map.has(ym)) map.set(ym, new Map());
      const inner = map.get(ym);
      inner.set(dept, (inner.get(dept) || 0) + n);
    } else {
      map.set(key, (map.get(key) || 0) + n);
    }
  }
  return { map, suppressed };
}

export function prescriptionTotal(data, filters) {
  const { facts, totals } = data;
  if (cubeNeeded(filters)) return sumCube(facts, filters);
  const { from, to } = filters;
  if (active(filters.dept)) return { sum: sumPairs(totals.by_dept, from, to, filters.dept), suppressed: false };
  if (active(filters.clinic)) return { sum: sumPairs(totals.by_clinic, from, to, filters.clinic), suppressed: false };
  if (active(filters.axis)) return { sum: sumPairs(totals.by_axis, from, to, filters.axis), suppressed: false };
  return { sum: sumPairs(totals.by_axis, from, to, null), suppressed: false };
}

export function monthlyAverage(total, filters) {
  const months = monthsBetween(filters.from, filters.to);
  const n = months.length || 1;
  return total / n;
}

export function recentMean(data, filters, recentMonths) {
  const months = monthsBetween(filters.from, filters.to);
  const last = months.slice(-Math.max(1, recentMonths || 3));
  if (!last.length) return { mean: 0, suppressed: false };
  const f = { ...filters, from: last[0], to: last[last.length - 1] };
  const { sum, suppressed } = prescriptionTotal(data, f);
  return { mean: sum / last.length, suppressed, months: last };
}

export function firstShare(data, filters) {
  if (filters.visitType === "初回") return { share: 1, suppressed: false };
  if (filters.visitType === "再来") return { share: 0, suppressed: false };
  if (cubeNeeded({ ...filters, visitType: "all" }) || active(filters.dist) || active(filters.dept) || active(filters.clinic) || active(filters.axis)) {
    const first = sumCube(data.facts, { ...filters, visitType: "初回" });
    const all = sumCube(data.facts, { ...filters, visitType: "all" });
    return {
      share: all.sum ? first.sum / all.sum : null,
      suppressed: first.suppressed || all.suppressed,
    };
  }
  const first = sumPairs(data.totals.by_visit_type, filters.from, filters.to, ["初回"]);
  const all = sumPairs(data.totals.by_visit_type, filters.from, filters.to, null);
  return { share: all ? first / all : null, suppressed: false };
}

export function retentionRate(retention, filters, dims) {
  const clinicOnly = active(filters.clinic);
  if (!cubeNeeded({ ...filters, visitType: "all", clinic: [] }) && isFullPeriod(filters, dims) && !clinicOnly && !active(filters.axis) && !active(filters.dept) && !active(filters.dist)) {
    const o = retention.overall;
    return { rate: o.first ? o.ret90 / o.first : null, first: o.first, ret90: o.ret90, suppressed: false, ignoredClinic: false };
  }
  let first = 0;
  let ret90 = 0;
  let suppressed = false;
  for (const r of retention.rows) {
    if (filters.from && r.ym < filters.from) continue;
    if (filters.to && r.ym > filters.to) continue;
    if (active(filters.axis) && !filters.axis.includes(r.axis)) continue;
    if (active(filters.dept) && !filters.dept.includes(r.dept)) continue;
    if (active(filters.dist) && !filters.dist.includes(r.dist)) continue;
    if (r.first == null || r.ret90 == null) {
      suppressed = true;
      continue;
    }
    first += r.first;
    ret90 += r.ret90;
  }
  return {
    rate: first ? ret90 / first : null,
    first,
    ret90,
    suppressed,
    ignoredClinic: Boolean(clinicOnly),
  };
}

export function monthlyStacked(data, filters, by = "axis") {
  const months = monthsBetween(filters.from, filters.to);
  if (cubeNeeded(filters) || by === "dept" && (active(filters.clinic) || active(filters.dist) || (filters.visitType && filters.visitType !== "all"))) {
    const key = by === "dept" ? "ym+dept" : "ym+axis";
    const { map, suppressed } = groupCube(data.facts, filters, key);
    return { months, series: map, suppressed };
  }
  const rows = by === "dept" ? data.totals.by_dept : data.totals.by_axis;
  const allowed = by === "dept" ? active(filters.dept) : active(filters.axis);
  return { months, series: monthlyPairs(rows, filters.from, filters.to, allowed), suppressed: false };
}

export function clinicRanking(data, filters) {
  if (cubeNeeded(filters) || active(filters.dept) || active(filters.dist) || (filters.visitType && filters.visitType !== "all") || active(filters.axis)) {
    return groupCube(data.facts, filters, CUBE.clinic);
  }
  const map = groupPairs(data.totals.by_clinic, filters.from, filters.to, null);
  return { map, suppressed: false };
}

export function deptRanking(data, filters) {
  if (cubeNeeded(filters) || active(filters.clinic) || active(filters.dist) || (filters.visitType && filters.visitType !== "all") || active(filters.axis)) {
    return groupCube(data.facts, filters, CUBE.dept);
  }
  const map = groupPairs(data.totals.by_dept, filters.from, filters.to, active(filters.dept));
  return { map, suppressed: false };
}

export function distanceBreakdown(data, filters, retention, dims) {
  const visits = cubeNeeded(filters) || active(filters.axis) || active(filters.dept) || active(filters.clinic) || (filters.visitType && filters.visitType !== "all")
    ? groupCube(data.facts, filters, CUBE.dist)
    : { map: groupPairs(data.totals.by_dist, filters.from, filters.to, active(filters.dist)), suppressed: false };
  const order = dims?.dist_order || ["0-0.5", "0.5-1", "1-2", "2+", "unknown"];
  const rows = order.map((band) => {
    const n = visits.map.get(band) || 0;
    const ret = retentionRate(retention, { ...filters, dist: [band] }, dims);
    return { dist: band, n, rate: ret.rate, retSuppressed: ret.suppressed };
  });
  return { rows, suppressed: visits.suppressed };
}

export function topShareFromMap(map, ids, total) {
  if (!total) return null;
  let n = 0;
  for (const id of ids) n += map.get(id) || 0;
  return n / total;
}

function deltaText(a, b) {
  if (a == null || b == null) return "";
  const d = a - b;
  if (d === 0) return "同じ";
  const word = d > 0 ? "増えた" : "減った";
  return `${word}（${Math.abs(d).toLocaleString("ja-JP")}）`;
}

export function kpis(data, filters, assumptions, dims) {
  const a = prescriptionTotal(data, filters);
  const months = monthsBetween(filters.from, filters.to);
  const mean = months.length ? a.sum / months.length : 0;
  const recent = recentMean(data, filters, assumptions.recentMonths);
  const first = firstShare(data, filters);
  const ret = retentionRate(data.retention, filters, dims);
  const rank = clinicRanking(data, filters);
  const top2 = topShareFromMap(rank.map, (dims?.clinic_order || []).slice(0, 2), a.sum);
  const gap = assumptions.targetMonthly - recent.mean;
  let compare = null;
  if (filters.compare && filters.fromB && filters.toB) {
    const bFilters = { ...filters, from: filters.fromB, to: filters.toB };
    const b = prescriptionTotal(data, bFilters);
    const bMonths = monthsBetween(filters.fromB, filters.toB);
    const bMean = bMonths.length ? b.sum / bMonths.length : 0;
    compare = {
      sum: b.sum,
      mean: bMean,
      sumText: deltaText(a.sum, b.sum),
      meanText: deltaText(mean, bMean),
      suppressed: b.suppressed,
    };
  }
  return {
    sum: a.sum,
    mean,
    months: months.length,
    recentMean: recent.mean,
    gap,
    firstShare: first.share,
    retention: ret.rate,
    top2,
    suppressed: a.suppressed || first.suppressed || ret.suppressed || rank.suppressed,
    ignoredClinicForRetention: ret.ignoredClinic,
    compare,
  };
}

export function rankedList(map, order) {
  const rows = [];
  if (order) {
    for (const key of order) {
      if (map.has(key)) rows.push({ key, n: map.get(key) });
    }
    for (const [key, n] of map.entries()) {
      if (!order.includes(key)) rows.push({ key, n });
    }
  } else {
    for (const [key, n] of map.entries()) rows.push({ key, n });
  }
  rows.sort((a, b) => b.n - a.n);
  return rows;
}

export function eventWindows(weekly, event, weeksN, axisFilter) {
  if (!event?.start) return null;
  const start = event.start;
  const end = event.end || event.start;
  const before = [];
  const after = [];
  for (const rec of weekly.total) {
    const week = rec[0];
    const n = rec[1];
    if (week < start) before.push({ week, n });
    else if (week > end) after.push({ week, n });
  }
  const b = before.slice(-weeksN);
  const a = after.slice(0, weeksN);
  const sum = (rows) => rows.reduce((s, r) => s + r.n, 0);
  const mean = (rows) => (rows.length ? sum(rows) / rows.length : null);
  let beforeN = mean(b);
  let afterN = mean(a);
  if (axisFilter && axisFilter.length && weekly.by_axis) {
    const pick = (pred, limit, fromEnd) => {
      const rows = weekly.by_axis.filter((r) => axisFilter.includes(r[1]) && pred(r[0]));
      const byWeek = new Map();
      for (const [week, _axis, n] of rows) byWeek.set(week, (byWeek.get(week) || 0) + n);
      const weeks = [...byWeek.keys()].sort();
      const sliced = fromEnd ? weeks.slice(-limit) : weeks.slice(0, limit);
      return sliced.map((w) => ({ week: w, n: byWeek.get(w) }));
    };
    const bb = pick((w) => w < start, weeksN, true);
    const aa = pick((w) => w > end, weeksN, false);
    beforeN = mean(bb);
    afterN = mean(aa);
  }
  return {
    beforeMean: beforeN,
    afterMean: afterN,
    beforeWeeks: weeksN,
    afterWeeks: weeksN,
    delta: beforeN != null && afterN != null ? afterN - beforeN : null,
  };
}
