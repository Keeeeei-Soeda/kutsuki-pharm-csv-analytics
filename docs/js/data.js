/** docs/data/*.json の読み込み（モジュール相対・キャッシュ付き）。 */

import { hydrate, isReady } from "./store.js";

const cache = new Map();

function dataUrl(name) {
  return new URL(`../data/${name}`, import.meta.url);
}

export async function loadJson(name) {
  if (cache.has(name)) return cache.get(name);
  const res = await fetch(dataUrl(name));
  if (!res.ok) throw new Error(`${name} を読めません (${res.status})`);
  const json = await res.json();
  cache.set(name, json);
  return json;
}

export async function loadExploreData() {
  const [facts, totals, weekly, retention, dims, params, events] = await Promise.all([
    loadJson("facts_monthly.json"),
    loadJson("totals_monthly.json"),
    loadJson("totals_weekly.json"),
    loadJson("retention.json"),
    loadJson("dims.json"),
    loadJson("params.json"),
    loadJson("events.json"),
  ]);
  if (!isReady()) hydrate({ dims, params });
  return { facts, totals, weekly, retention, dims, params, events };
}
