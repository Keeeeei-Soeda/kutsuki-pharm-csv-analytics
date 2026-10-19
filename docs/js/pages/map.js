/** 商圏マップ（Leaflet）。Google マップ版でも同じフィルタ／排他ロジックを使う想定。 */

import { getFilters, subscribe } from "../store.js";

const GATE = "#c45c26";
const NONGATE = "#2f6f9f";
const STORE = "#1f6e4d";
const COMP = "#6b7280";

function $(id) {
  return document.getElementById(id);
}

function loadData() {
  const node = $("map-data");
  if (!node) return null;
  return JSON.parse(node.textContent);
}

function radiusFor(n, maxN) {
  const maxLog = Math.log1p(maxN || 1);
  return 4 + 22 * (Math.log1p(n) / maxLog);
}

function meshColor(rate, D) {
  if (!rate) return "#eeeae0";
  for (let i = 0; i < D.meshCuts.length; i += 1) {
    if (rate <= D.meshCuts[i]) return D.meshBands[i].color;
  }
  return D.meshBands[D.meshBands.length - 1].color;
}

function clinicPopup(c, totalN) {
  const share = totalN > 0 ? ((c.n / totalN) * 100).toFixed(1) : "—";
  return (
    `<b>${c.name}</b><br>処方箋 ${c.n.toLocaleString()} 枚` +
    `<br>処方箋に占める割合 ${share}%` +
    `<br>${c.sp || "-"} / ${c.gate ? "隣の2院" : "それ以外の医院"}` +
    (c.km != null ? `<br>薬局からの距離 ${c.km.toFixed(2)} km` : "")
  );
}

function selectedIds(filters) {
  return new Set(filters.clinic || []);
}

function selectedDepts(filters) {
  return new Set(filters.dept || []);
}

function clinicVisible(c, filters) {
  const depts = selectedDepts(filters);
  if (depts.size && !depts.has(c.sp || "不明")) return false;
  return true;
}

/** Leaflet 実装。Google 版は同名メソッドで差し替える。 */
function createLeafletEngine(D) {
  if (typeof L === "undefined") throw new Error("Leaflet が読み込まれていません");

  const gsi = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "地理院タイル（淡色地図）",
  });
  const gsiStd = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "地理院タイル（標準地図）",
  });
  const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  });

  const map = L.map("map", {
    center: [D.pharmacy.lat, D.pharmacy.lon],
    zoom: 13,
    layers: [gsi],
    scrollWheelZoom: false,
    attributionControl: false,
  });
  L.control.attribution({ prefix: "Leaflet" }).addTo(map);
  map.on("focus", () => map.scrollWheelZoom.enable());
  map.on("blur", () => map.scrollWheelZoom.disable());

  map.createPane("clinicsPane");
  map.getPane("clinicsPane").style.zIndex = 450;
  map.createPane("compPane");
  map.getPane("compPane").style.zIndex = 460;
  map.createPane("storePane");
  map.getPane("storePane").style.zIndex = 650;

  const storeLayer = L.layerGroup().addTo(map);
  const outer = L.circleMarker([D.pharmacy.lat, D.pharmacy.lon], {
    pane: "storePane",
    radius: 12,
    color: "#ffffff",
    weight: 3,
    fillColor: STORE,
    fillOpacity: 1,
  });
  const inner = L.circleMarker([D.pharmacy.lat, D.pharmacy.lon], {
    pane: "storePane",
    radius: 4,
    color: "#ffffff",
    weight: 1,
    fillColor: "#ffffff",
    fillOpacity: 1,
  });
  outer.bindPopup(`<b>${D.pharmacy.name}</b><br>自店`);
  storeLayer.addLayer(outer);
  storeLayer.addLayer(inner);

  const clinicLayer = L.layerGroup().addTo(map);
  const clinicMarkers = new Map();
  const sorted = [...D.clinics].sort((a, b) => b.n - a.n);
  sorted.forEach((c) => {
    const m = L.circleMarker([c.lat, c.lon], {
      pane: "clinicsPane",
      radius: radiusFor(c.n, D.maxN),
      color: "#ffffff",
      fillColor: c.gate ? GATE : NONGATE,
      fillOpacity: 0.3,
      weight: 1,
    });
    m.bindPopup(clinicPopup(c, D.totalN));
    m.on("click", () => {
      map.setView([c.lat, c.lon], Math.max(map.getZoom(), 14), { animate: true });
    });
    m._clinic = c;
    clinicMarkers.set(c.id, m);
    clinicLayer.addLayer(m);
  });

  const targetLayer = L.layerGroup().addTo(map);
  (D.targets || []).forEach((m) => {
    L.rectangle(
      [
        [m.lat - D.meshHalf.lat, m.lon - D.meshHalf.lon],
        [m.lat + D.meshHalf.lat, m.lon + D.meshHalf.lon],
      ],
      {
        color: "#c4472b",
        weight: 2.5,
        fillColor: "transparent",
        fillOpacity: 0,
      }
    )
      .bindPopup(
        `<b>配布候補</b>${m.town ? "（" + m.town + "）" : ""}` +
          `<br>人口 ${m.pop.toLocaleString()} 人` +
          `<br>自店に来た人 ${m.uniq.toLocaleString()} 人`
      )
      .addTo(targetLayer);
  });

  const meshLayer = L.layerGroup();
  D.meshes.forEach((m) => {
    L.rectangle(
      [
        [m.lat - D.meshHalf.lat, m.lon - D.meshHalf.lon],
        [m.lat + D.meshHalf.lat, m.lon + D.meshHalf.lon],
      ],
      {
        color: "#8d8577",
        weight: 0.4,
        fillColor: meshColor(m.rate, D),
        fillOpacity: m.rate ? 0.6 : 0.18,
      }
    )
      .bindPopup(
        `メッシュ ${m.code}<br>人口 ${m.pop.toLocaleString()} 人` +
          `<br>自店に来た人 ${m.uniq.toLocaleString()} 人` +
          `<br>人口のうち自店に来た人の割合 ${(m.rate * 100).toFixed(2)}%`
      )
      .addTo(meshLayer);
  });

  const compLayer = L.layerGroup();
  D.competitors.forEach((p) => {
    const icon = L.divIcon({
      className: "comp-marker",
      html: '<span class="comp-diamond" aria-hidden="true"></span>',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
    L.marker([p.lat, p.lon], { icon, pane: "compPane" })
      .bindPopup(
        `<b>${p.name}</b><br>競合薬局` +
          (p.km != null ? `<br>自店から直線 ${p.km.toFixed(3)} km` : "")
      )
      .addTo(compLayer);
  });

  let heatLayer = null;
  if (window.L && L.heatLayer && D.density.points.length) {
    heatLayer = L.heatLayer(D.density.points, {
      radius: 26,
      blur: 20,
      max: D.density.max,
      minOpacity: 0.3,
      gradient: { 0.3: "#ffeda0", 0.55: "#feb24c", 0.78: "#fc4e2a", 1.0: "#bd0026" },
    });
  }

  const bases = { "地理院 淡色": gsi, "地理院 標準": gsiStd, OpenStreetMap: osm };
  let densityMode = heatLayer ? "heat" : "none"; // none | mesh | heat
  if (heatLayer) map.addLayer(heatLayer);

  function setDensity(mode) {
    densityMode = mode;
    if (map.hasLayer(meshLayer)) map.removeLayer(meshLayer);
    if (heatLayer && map.hasLayer(heatLayer)) map.removeLayer(heatLayer);
    if (mode === "mesh") map.addLayer(meshLayer);
    if (mode === "heat" && heatLayer) map.addLayer(heatLayer);
    syncChrome();
  }

  function applyFilters(filters) {
    const selected = selectedIds(filters);
    const hasClinic = selected.size > 0;
    const bounds = [[D.pharmacy.lat, D.pharmacy.lon]];
    const visibleMarkers = [];

    clinicMarkers.forEach((m, id) => {
      const c = m._clinic;
      if (!clinicVisible(c, filters)) {
        if (clinicLayer.hasLayer(m)) clinicLayer.removeLayer(m);
        return;
      }
      visibleMarkers.push(m);
      const highlight = hasClinic && selected.has(id);
      const dim = hasClinic && !selected.has(id);
      m.setStyle({
        fillOpacity: dim ? 0.15 : highlight ? 0.75 : 0.3,
        weight: highlight ? 2.5 : 1,
        color: highlight ? (c.gate ? GATE : NONGATE) : "#ffffff",
        fillColor: c.gate ? GATE : NONGATE,
      });
      if (highlight) bounds.push([c.lat, c.lon]);
    });

    // 大きい円を下・小さい円を上（件数降順で再配置）
    visibleMarkers
      .sort((a, b) => b._clinic.n - a._clinic.n)
      .forEach((m) => {
        if (clinicLayer.hasLayer(m)) clinicLayer.removeLayer(m);
        clinicLayer.addLayer(m);
      });
    visibleMarkers
      .filter((m) => hasClinic && selected.has(m._clinic.id))
      .forEach((m) => m.bringToFront());

    if (hasClinic && bounds.length > 1) {
      map.fitBounds(bounds, { padding: [48, 48], maxZoom: 15 });
    }
  }

  function syncChrome() {
    const root = $("map-chrome");
    if (!root) return;
    root.querySelectorAll("[data-density]").forEach((btn) => {
      btn.classList.toggle("is-on", btn.getAttribute("data-density") === densityMode);
      btn.setAttribute("aria-pressed", btn.getAttribute("data-density") === densityMode ? "true" : "false");
    });
    root.querySelectorAll("[data-overlay]").forEach((input) => {
      const key = input.getAttribute("data-overlay");
      const on =
        (key === "store" && map.hasLayer(storeLayer)) ||
        (key === "clinic" && map.hasLayer(clinicLayer)) ||
        (key === "comp" && map.hasLayer(compLayer)) ||
        (key === "target" && map.hasLayer(targetLayer));
      input.checked = !!on;
    });
  }

  function mountChrome() {
    const shell = $("map-shell");
    if (!shell || $("map-chrome")) return;
    const wide = window.matchMedia("(min-width: 900px)").matches;
    const chrome = document.createElement("div");
    chrome.id = "map-chrome";
    chrome.className = "map-chrome";
    chrome.innerHTML = `
      <div class="map-panel map-layers${wide ? " is-open" : ""}">
        <button type="button" class="map-panel-toggle" data-toggle="layers" aria-expanded="${wide}">
          <span class="map-panel-icon" aria-hidden="true">☰</span>
          <span>表示の切替</span>
        </button>
        <div class="map-panel-body">
          <p class="map-panel-label">地図</p>
          <label class="map-check"><input type="radio" name="map-base" value="gsi" checked/>地理院 淡色</label>
          <label class="map-check"><input type="radio" name="map-base" value="gsiStd"/>地理院 標準</label>
          <label class="map-check"><input type="radio" name="map-base" value="osm"/>OpenStreetMap</label>
          <p class="map-panel-label">重ねる情報</p>
          <label class="map-check"><input type="checkbox" data-overlay="store" checked/>自店</label>
          <label class="map-check"><input type="checkbox" data-overlay="clinic" checked/>クリニック</label>
          <label class="map-check"><input type="checkbox" data-overlay="comp"/>競合薬局（${D.competitors.length}軒）</label>
          <label class="map-check"><input type="checkbox" data-overlay="target" ${D.targets && D.targets.length ? "checked" : ""}/>配布候補</label>
          <p class="map-panel-label">地域の色（どれか1つ）</p>
          <div class="map-radio-row">
            <button type="button" class="map-chip" data-density="none" aria-pressed="false">なし</button>
            <button type="button" class="map-chip" data-density="mesh" aria-pressed="false">来局の割合</button>
            <button type="button" class="map-chip${heatLayer ? " is-on" : ""}" data-density="heat" aria-pressed="${heatLayer ? "true" : "false"}"${heatLayer ? "" : " disabled"}>患者が多い範囲</button>
          </div>
        </div>
      </div>
      <div class="map-panel map-legend-panel${wide ? " is-open" : ""}">
        <button type="button" class="map-panel-toggle" data-toggle="legend" aria-expanded="${wide}">
          <span class="map-panel-icon" aria-hidden="true">ⓘ</span>
          <span>凡例</span>
        </button>
        <div class="map-panel-body" id="map-float-legend"></div>
      </div>`;
    shell.appendChild(chrome);

    chrome.querySelectorAll("[data-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const panel = btn.closest(".map-panel");
        panel.classList.toggle("is-open");
        btn.setAttribute("aria-expanded", panel.classList.contains("is-open") ? "true" : "false");
      });
    });
    chrome.querySelectorAll('input[name="map-base"]').forEach((input) => {
      input.addEventListener("change", () => {
        if (!input.checked) return;
        Object.values(bases).forEach((layer) => {
          if (map.hasLayer(layer)) map.removeLayer(layer);
        });
        const pick = { gsi, gsiStd, osm }[input.value] || gsi;
        map.addLayer(pick);
      });
    });
    chrome.querySelectorAll("[data-overlay]").forEach((input) => {
      input.addEventListener("change", () => {
        const key = input.getAttribute("data-overlay");
        const layer =
          key === "store" ? storeLayer : key === "clinic" ? clinicLayer : key === "target" ? targetLayer : compLayer;
        if (input.checked) map.addLayer(layer);
        else map.removeLayer(layer);
      });
    });
    chrome.querySelectorAll("[data-density]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        setDensity(btn.getAttribute("data-density"));
      });
    });

    const fl = $("map-float-legend");
    if (fl) {
      fl.innerHTML =
        D.ticks
          .map((n) => {
            const r = radiusFor(n, D.maxN);
            return `<div class="legend-row"><span class="bubble bubble-size" style="width:${2 * r}px;height:${2 * r}px"></span><span class="num">${n.toLocaleString()}</span> 枚</div>`;
          })
          .join("") +
        `<div class="legend-row"><span class="swatch-dot" style="background:${GATE}"></span>隣の2院</div>` +
        `<div class="legend-row"><span class="swatch-dot" style="background:${NONGATE}"></span>それ以外の医院</div>` +
        `<div class="legend-row"><span class="swatch" style="border:2px solid #c4472b;background:transparent"></span>配布候補</div>` +
        `<div class="legend-row"><span class="swatch dot" style="background:#1f6e4d;width:14px;height:14px;border:2px solid #fff;box-shadow:0 0 0 1px #1f6e4d"></span>自店</div>` +
        `<div class="legend-row"><span class="swatch ring"></span>競合薬局</div>`;
    }
    syncChrome();
  }

  function fillPageLegends() {
    const bl = $("bubble-legend");
    if (bl) {
      bl.innerHTML = D.ticks
        .map((n) => {
          const r = radiusFor(n, D.maxN);
          return `<div class="legend-row"><span class="bubble bubble-size" style="width:${2 * r}px;height:${2 * r}px"></span><span class="num">${n.toLocaleString()}</span> 枚</div>`;
        })
        .join("");
    }
    const ml = $("mesh-legend");
    if (ml) {
      const maxPct = (D.meshRateMax * 100).toFixed(2);
      const rows = [
        `<div class="legend-row"><span class="swatch" style="background:#eeeae0"></span><span class="num">来局なし</span></div>`,
      ];
      const words = D.meshWords || ["ほぼ来ていない", "少ない", "ふつう", "多い", "とても多い"];
      D.meshBands.forEach((b, i) => {
        const word = words[i] || "";
        rows.push(
          `<div class="legend-row"><span class="swatch" style="background:${b.color}"></span><span class="num">${word}</span></div>`
        );
      });
      rows.push(
        `<p class="legend-note">最上位の最大は ${maxPct}%（外れ値を含む）。</p>`
      );
      ml.innerHTML = rows.join("");
    }
    const other = $("other-legend");
    if (other) {
      other.innerHTML =
        `<div class="legend-row"><span class="swatch dot" style="background:#1f6e4d;width:14px;height:14px;border:2px solid #fff;box-shadow:0 0 0 1px #1f6e4d"></span>自店（くつき薬局南茨木店）</div>` +
        `<div class="legend-row"><span class="swatch ring"></span>競合薬局（${D.competitors.length}軒）</div>` +
        `<div class="legend-row"><span class="swatch" style="border:2px solid #c4472b;background:transparent"></span>配布候補</div>` +
        `<div class="legend-row"><span class="swatch" style="background:linear-gradient(90deg,#ffeda0,#feb24c,#fc4e2a,#bd0026)"></span>患者が多く住んでいる範囲</div>`;
    }
  }

  return {
    map,
    applyFilters,
    mountChrome,
    fillPageLegends,
    setDensity,
  };
}

function boot() {
  const shell = $("map-shell");
  if (!shell) return;
  const D = loadData();
  if (!D) return;

  let engine;
  try {
    engine = createLeafletEngine(D);
  } catch (err) {
    console.error(err);
    return;
  }
  engine.fillPageLegends();
  engine.mountChrome();

  const apply = () => engine.applyFilters(getFilters());
  apply();
  subscribe(apply);
}

boot();
