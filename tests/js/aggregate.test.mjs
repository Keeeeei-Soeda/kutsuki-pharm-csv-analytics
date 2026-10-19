import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { firstShare, kpis, prescriptionTotal, recentMean, retentionRate } from "../../docs/js/aggregate.js";

const root = new URL("../../docs/data/", import.meta.url);
const load = (name) => JSON.parse(readFileSync(new URL(name, root), "utf8"));
const data = {
  facts: load("facts_monthly.json"),
  totals: load("totals_monthly.json"),
  retention: load("retention.json"),
  dims: load("dims.json"),
};
const full = { from: "2024-09", to: "2026-07", axis: [], dept: [], clinic: [], dist: [], visitType: "all" };

describe("unfiltered KPIs", () => {
  it("recent 3-month mean is 1768", () => {
    const r = recentMean(data, full, 3);
    assert.equal(r.mean, 1768);
  });

  it("90-day retention is about 41%", () => {
    const r = retentionRate(data.retention, full, data.dims);
    assert.ok(Math.abs(r.rate - 0.4067) < 1e-4);
  });

  it("top-2 share is about 73%", () => {
    const k = kpis(data, full, { targetMonthly: 3000, recentMonths: 3, marginYen: 2000 }, data.dims);
    assert.ok(Math.abs(k.top2 - 0.7305) < 1e-3);
  });

  it("period total matches monthly totals", () => {
    const { sum } = prescriptionTotal(data, full);
    assert.equal(sum, 31924);
  });

  it("first share is a ratio between 0 and 1", () => {
    const s = firstShare(data, full);
    assert.ok(s.share > 0 && s.share < 1);
  });
});
