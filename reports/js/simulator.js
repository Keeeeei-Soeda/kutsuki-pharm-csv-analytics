/** Python ``simulate_scenarios`` の一次近似を JS に移植した純関数。 */

function add(rows, name, visits, base, target, note) {
  rows.push({
    name,
    visits,
    ratio: visits / base,
    reaches_target: visits >= target,
    note,
  });
}

export function simulateScenarios(inp) {
  const base = inp.monthly_visits;
  const h = inp.hasegawa_share || 0.39;
  const n = inp.nongate_share;
  const target = inp.target_monthly;
  const rows = [];
  const retLift = base * 0.06;
  add(rows, "現状", base, base, target, "直近3か月平均");
  add(rows, "はせがわが1割減る", base * (1 - 0.1 * h), base, target, "2院依存のリスク");
  add(rows, "はせがわが3割減る", base * (1 - 0.3 * h), base, target, "最悪ケース");
  add(rows, "面が1.5倍になる", base * (1 + 0.5 * n), base, target, "2院以外");
  add(rows, "再来が41%から50%になる", base + retLift, base, target, "概算");
  add(rows, "面1.5倍＋再来50%＋内科2院（各100枚）", base * (1 + 0.5 * n) + retLift + 200, base, target, "全部やっても差が残る");
  return rows;
}

export function simulateLevers(inp, levers) {
  const h = inp.hasegawa_share || 0.39;
  const n = inp.nongate_share;
  const hDelta = Number(levers.hasegawaDelta || 0);
  const otherMult = Number(levers.otherMult ?? 1);
  const newVisits = Number(levers.newVisits || 0);
  const retPts = Number(levers.retentionPts || 0);
  const retLift = inp.monthly_visits * 0.06 * (retPts / 9);
  const visits = inp.monthly_visits * (1 + h * hDelta + n * (otherMult - 1)) + newVisits + retLift;
  return {
    visits,
    reachRatio: visits / inp.target_monthly,
    needNongateMult: (inp.target_monthly / inp.monthly_visits - (1 - n)) / Math.max(n, 1e-9),
  };
}
