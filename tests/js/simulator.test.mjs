import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { simulateScenarios } from "../../docs/js/simulator.js";

const params = JSON.parse(readFileSync(new URL("../../docs/data/params.json", import.meta.url), "utf8"));

describe("simulateScenarios", () => {
  it("matches Python default_scenarios", () => {
    const got = simulateScenarios({
      monthly_visits: params.current.monthly_visits,
      target_monthly: params.target_monthly,
      gate_share: params.current.gate_share,
      nongate_share: params.current.nongate_share,
    });
    const expected = params.default_scenarios;
    assert.equal(got.length, expected.length);
    for (let i = 0; i < expected.length; i += 1) {
      assert.equal(got[i].name, expected[i].name);
      assert.ok(Math.abs(got[i].visits - expected[i].visits) < 1e-6, `${got[i].name} visits`);
      assert.equal(got[i].reaches_target, expected[i].reaches_target);
    }
  });
});
