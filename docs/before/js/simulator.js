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
  const g = inp.gate_share;
  const n = inp.nongate_share;
  const u = 1 - g - n;
  const target = inp.target_monthly;
  const rows = [];

  add(rows, "現状ベース", base, base, target, "直近3か月平均");
  add(rows, "門前需要+10%", base * (1 + 0.1 * g), base, target, "軸A: 直近クリニック流量増。薬局施策の寄与は限定的");
  add(rows, "門前需要+20%", base * (1 + 0.2 * g), base, target, "軸A");
  add(rows, "非門前×2", base * (g + n * 2 + u), base, target, "軸B: 面獲得の拡大");
  add(rows, "非門前×3", base * (g + n * 3 + u), base, target, "軸B");
  add(rows, "来局頻度+10%", base * 1.1, base, target, "継続率・処方間隔の改善代理");
  add(rows, "来局頻度+20%", base * 1.2, base, target, "継続");
  add(rows, "活動患者+15%", base * 1.15, base, target, "新規獲得（門前+非門前合算）");
  add(rows, "活動患者+30%", base * 1.3, base, target, "新規獲得");
  const combo = base * (g * 1.05 + n * 2.5 + u) * 1.1;
  add(rows, "複合:門前+5%×非門前×2.5×頻度+10%", combo, base, target, "同時施策の粗い積");
  const needM = (target / base - g - u) / Math.max(n, 1e-9);
  add(rows, `参考:非門前のみで目標→×${needM.toFixed(1)}が必要`, target, base, target, "他条件一定のときの必要条件（実現可能性の目安）");
  return rows;
}

export function simulateLevers(inp, levers) {
  const g = inp.gate_share;
  const n = inp.nongate_share;
  const u = 1 - g - n;
  const gate = 1 + Number(levers.gateGrowth || 0);
  const nongateMult = Number(levers.nongateMult ?? 1);
  const freq = 1 + Number(levers.freqGrowth || 0);
  const stock = 1 + Number(levers.stockGrowth || 0);
  const visits = inp.monthly_visits * (g * gate + n * nongateMult + u) * freq * stock;
  const needNongateMult = (inp.target_monthly / inp.monthly_visits - g - u) / Math.max(n, 1e-9);
  return {
    visits,
    reachRatio: visits / inp.target_monthly,
    needNongateMult,
  };
}
