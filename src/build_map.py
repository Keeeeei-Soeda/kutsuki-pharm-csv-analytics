"""独立した地図ページ（map.html）を生成する。

- タイルは国土地理院（淡色）を既定、OpenStreetMap を切替候補にする。
  どちらもキー発行・課金設定が不要。Google Maps JS API は要件になった段階で差し替える。
- クリニックの円は **log1p(件数)** で半径・色を決め、凡例は実数で示す。
  件数をそのまま半径に割り当てると、はせがわ耳鼻科1点に潰れて他が読めなくなる。
- 患者住所の個別点はプロットしない。250m グリッドに集約し、
  少数セル（既定 3件未満）は伏せたうえでヒートマップにする。

``python3 -m src.build_map``
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from src.io import PHARMACY_LAT, PHARMACY_LON, PHARMACY_NAME, ROOT, ensure_dirs, read_csv
from src.specialty_taxonomy import build_specialty_map
from src.viz.sidebar import PERIOD_LABEL, render_sidebar, sidebar_css, sidebar_js

REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

# 500m メッシュ（1/2地域メッシュ）のセル半幅
MESH_HALF_LAT = 1 / 480
MESH_HALF_LON = 1 / 320

# 患者密度グリッド（約250m）と秘匿しきい値
GRID_LAT = 1 / 480
GRID_LON = 1 / 320
MIN_CELL_COUNT = 3


def clinic_layer() -> List[dict]:
    vt = read_csv("visit_triangle")
    cm = read_csv("clinic_master")
    smap = build_specialty_map(cm)[["クリニックID", "主科"]]

    counts = vt.groupby("クリニックID").size().rename("件数").reset_index()
    gate = (
        vt.assign(門前=vt["立地パターン"].astype(str).eq("門前型"))
        .groupby("クリニックID")["門前"]
        .mean()
        .rename("門前比")
        .reset_index()
    )
    df = (
        cm[["クリニックID", "クリニック名", "緯度", "経度", "クリニック→薬局_直線km", "種別"]]
        .merge(counts, on="クリニックID", how="inner")
        .merge(gate, on="クリニックID", how="left")
        .merge(smap, on="クリニックID", how="left")
        .dropna(subset=["緯度", "経度"])
    )
    df = df[df["件数"] > 0].sort_values("件数", ascending=False)
    return [
        {
            "id": r["クリニックID"],
            "name": r["クリニック名"],
            "lat": float(r["緯度"]),
            "lon": float(r["経度"]),
            "n": int(r["件数"]),
            "km": None if pd.isna(r["クリニック→薬局_直線km"]) else float(r["クリニック→薬局_直線km"]),
            "sp": r["主科"] if isinstance(r["主科"], str) else "不明",
            "gate": bool((r["門前比"] or 0) >= 0.5),
        }
        for _, r in df.iterrows()
    ]


def mesh_layer() -> List[dict]:
    path = ROOT / "data" / "processed" / "mesh_visit_rate.csv"
    if not path.exists():
        return []
    m = pd.read_csv(path, encoding="utf-8-sig")
    m = m.dropna(subset=["中心緯度", "中心経度"])
    return [
        {
            "code": str(r["メッシュコード"]),
            "lat": float(r["中心緯度"]),
            "lon": float(r["中心経度"]),
            "pop": int(r["総人口"]) if pd.notna(r["総人口"]) else 0,
            "uniq": int(r["来局ユニーク"]) if pd.notna(r["来局ユニーク"]) else 0,
            "rate": float(r["来局率"]) if pd.notna(r["来局率"]) else 0.0,
        }
        for _, r in m.iterrows()
    ]


def competitor_layer() -> List[dict]:
    cp = read_csv("competitor_pharmacy").dropna(subset=["緯度", "経度"])
    return [
        {
            "id": r["競合薬局ID"],
            "name": r["薬局名"],
            "lat": float(r["緯度"]),
            "lon": float(r["経度"]),
            "km": float(r["くつき薬局南茨木店→競合薬局_直線km"])
            if pd.notna(r["くつき薬局南茨木店→競合薬局_直線km"])
            else None,
        }
        for _, r in cp.iterrows()
    ]


def patient_density_layer() -> Dict[str, object]:
    """患者住所を約250mグリッドに集約して返す（個別点は出さない）。"""
    pm = read_csv("patient_master").dropna(subset=["緯度", "経度"])
    lat = pd.to_numeric(pm["緯度"], errors="coerce")
    lon = pd.to_numeric(pm["経度"], errors="coerce")
    ok = lat.notna() & lon.notna()
    lat, lon = lat[ok], lon[ok]

    gi = np.floor(lat / GRID_LAT).astype(int)
    gj = np.floor(lon / GRID_LON).astype(int)
    grid = (
        pd.DataFrame({"gi": gi, "gj": gj})
        .value_counts()
        .rename("n")
        .reset_index()
    )
    suppressed = int((grid["n"] < MIN_CELL_COUNT).sum())
    grid = grid[grid["n"] >= MIN_CELL_COUNT]
    points = [
        [
            float((r.gi + 0.5) * GRID_LAT),
            float((r.gj + 0.5) * GRID_LON),
            float(math.log1p(r.n)),
        ]
        for r in grid.itertuples()
    ]
    return {
        "points": points,
        "max": float(math.log1p(grid["n"].max())) if len(grid) else 1.0,
        "cells": int(len(grid)),
        "suppressed_cells": suppressed,
        "n_patients": int(ok.sum()),
        "max_count": int(grid["n"].max()) if len(grid) else 0,
    }


def build(out_path: Path = REPORTS / "map.html") -> Path:
    ensure_dirs()
    clinics = clinic_layer()
    meshes = mesh_layer()
    competitors = competitor_layer()
    density = patient_density_layer()

    # メッシュ来局率は対数でも右に寄って読めないため、非ゼロ値の五分位で色を割る。
    # 凡例には実数（%）の区間を出す。
    nonzero = sorted(m["rate"] for m in meshes if m["rate"] > 0)
    if nonzero:
        cuts = [float(np.quantile(nonzero, q)) for q in (0.2, 0.4, 0.6, 0.8)]
    else:
        cuts = [0.0, 0.0, 0.0, 0.0]
    mesh_colors = ["#d9f0d3", "#a6dba0", "#5aae61", "#2b8cbe", "#084081"]
    mesh_bands = []
    lows = [0.0] + cuts
    highs = cuts + [float(nonzero[-1]) if nonzero else 0.0]
    for lo, hi, col in zip(lows, highs, mesh_colors):
        mesh_bands.append({"lo": lo, "hi": hi, "color": col})

    max_n = max((c["n"] for c in clinics), default=1)
    # 凡例に出す実数の目盛り（半径は log1p だが表示は実数）
    ticks = [t for t in (10, 50, 200, 1000, 5000, 15000) if t <= max_n] or [max_n]
    if ticks[-1] != max_n:
        ticks.append(max_n)

    payload = {
        "pharmacy": {"lat": PHARMACY_LAT, "lon": PHARMACY_LON, "name": PHARMACY_NAME},
        "clinics": clinics,
        "meshes": meshes,
        "competitors": competitors,
        "density": density,
        "maxN": max_n,
        "ticks": ticks,
        "meshHalf": {"lat": MESH_HALF_LAT, "lon": MESH_HALF_LON},
        "minCellCount": MIN_CELL_COUNT,
        "meshCuts": cuts,
        "meshBands": mesh_bands,
    }

    toc = [
        ("map-sec", "地図"),
        ("legend", "凡例と縮尺の考え方"),
        ("notes-sec", "読み方と限界"),
    ]
    sidebar = render_sidebar(
        "map", toc, breadcrumb="Kutsuki DataBank / 地図", period=PERIOD_LABEL
    )

    mesh_rate_max = max((m["rate"] for m in meshes), default=0.0)
    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>商圏マップ | {PHARMACY_NAME}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
:root {{
  --bg: #f3f1eb; --surface: #fffcf7; --ink: #1c2430; --muted: #5c6675;
  --line: #d9d2c5; --accent: #0f6a6a; --accent-2: #c45c26;
  --shadow: 0 10px 30px rgba(28,36,48,.08);
  --sans: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace;
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: var(--sans); color: var(--ink); background: var(--bg); line-height:1.65; }}
a {{ color: var(--accent); }}
.wrap {{ max-width: 960px; margin: 0 auto; padding: 24px 20px 64px; }}
.hero {{
  background: linear-gradient(135deg,#103a3a 0%,#0f6a6a 55%,#2f6f9f 100%);
  color:#f7fffe; border-radius:28px; padding:30px 32px 24px; box-shadow: var(--shadow);
}}
.hero .eyebrow {{ letter-spacing:.14em; text-transform:uppercase; font-size:12px; opacity:.85; }}
.hero h1 {{ margin:8px 0 10px; font-size: clamp(26px,4vw,36px); line-height:1.2; }}
.hero p {{ margin:0; opacity:.92; }}
.meta {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }}
.chip {{ background: rgba(255,255,255,.14); border-radius:999px; padding:6px 12px; font-size:12px; }}
h2 {{ margin:32px 0 12px; font-size:22px; border-left:4px solid var(--accent); padding-left:12px; }}
.card {{ background: var(--surface); border:1px solid var(--line); border-radius:18px; padding:18px; box-shadow: var(--shadow); }}
#map {{ height: 620px; border-radius:18px; border:1px solid var(--line); box-shadow: var(--shadow); }}
.legend-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(230px,1fr)); gap:14px; margin-top:14px; }}
.legend-row {{ display:flex; align-items:center; gap:8px; margin:4px 0; font-size:13px; }}
.swatch {{ width:16px; height:16px; border-radius:4px; flex:0 0 auto; border:1px solid rgba(0,0,0,.15); }}
.bubble {{ border-radius:50%; background: rgba(196,92,38,.55); border:1px solid #c45c26; flex:0 0 auto; }}
.num {{ font-family: var(--mono); font-variant-numeric: tabular-nums; }}
.footer {{ margin-top:36px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:16px; }}
.leaflet-container {{ font-family: var(--sans); }}
.map-legend {{
  background: rgba(255,252,247,.94); padding:8px 10px; border-radius:10px;
  border:1px solid var(--line); font-size:12px; line-height:1.5; max-width:190px;
}}
ul {{ padding-left: 1.2rem; }}
{sidebar_css()}
</style>
</head>
<body>
{sidebar}
<main class="wrap" id="main">
  <header class="hero">
    <div class="eyebrow">Kutsuki DataBank / 地図</div>
    <h1>商圏マップ</h1>
    <p>自店・クリニック・メッシュ来局率・競合薬局・患者密度をレイヤ切替で重ねて見る。
       円の大きさは件数の対数で、凡例は実数。</p>
    <div class="meta">
      <span class="chip">{PHARMACY_NAME}</span>
      <span class="chip">{PERIOD_LABEL}</span>
      <span class="chip">タイル: 国土地理院 / OSM</span>
    </div>
  </header>

  <h2 id="map-sec">地図</h2>
  <div id="map"></div>
  <p style="color:var(--muted);font-size:13px;margin-top:8px">
    右上のコントロールでレイヤを切り替えられます。円・矩形をクリックすると内訳が出ます。
  </p>

  <h2 id="legend">凡例と縮尺の考え方</h2>
  <div class="card">
    <div class="legend-grid">
      <div>
        <strong style="font-size:13px">クリニック（円＝件数）</strong>
        <div id="bubble-legend"></div>
        <p style="font-size:12px;color:var(--muted);margin:8px 0 0">
          半径は <span class="num">log1p(件数)</span> に比例。件数をそのまま半径にすると
          最大施設1点だけが巨大になり、他が読めなくなるため。<strong>表示している数値は実数</strong>。
        </p>
      </div>
      <div>
        <strong style="font-size:13px">メッシュ来局率</strong>
        <div id="mesh-legend"></div>
        <p style="font-size:12px;color:var(--muted);margin:8px 0 0">
          500mメッシュの「自店来局ユニーク患者 ÷ メッシュ人口」。
          最大 {mesh_rate_max:.1%}。色は非ゼロ値の<strong>五分位</strong>で割っている
          （対数でも右に寄って読めないため）。
        </p>
      </div>
      <div>
        <strong style="font-size:13px">その他のレイヤ</strong>
        <div class="legend-row"><span class="swatch" style="background:#0f6a6a"></span>自店（くつき薬局南茨木店）</div>
        <div class="legend-row"><span class="swatch" style="background:#2f6f9f"></span>競合薬局（{len(competitors)}件）</div>
        <div class="legend-row"><span class="swatch" style="background:linear-gradient(90deg,#ffeda0,#feb24c,#fc4e2a,#bd0026)"></span>患者密度（KDEヒートマップ）</div>
        <p style="font-size:12px;color:var(--muted);margin:8px 0 0">
          患者密度は<strong>個別点をプロットしていません</strong>。約250mグリッドに集約し、
          {MIN_CELL_COUNT}件未満のセルは非表示（{density['suppressed_cells']}セルを秘匿）。
        </p>
      </div>
    </div>
  </div>

  <h2 id="notes-sec">読み方と限界</h2>
  <div class="card">
    <ul>
      <li>クリニックの円は<strong>自店を経由した処方箋件数</strong>であり、そのクリニックの総発行数ではない。
          自店シェアの分母は観測できない。</li>
      <li>メッシュ来局率の分子は自店患者のみ。他薬局の利用は含まないため、
          地域の「薬局利用率」ではなく<strong>自店の浸透度</strong>として読む。</li>
      <li>患者密度は集約値。セル単位の件数は {MIN_CELL_COUNT} 件以上のものだけを使っている。</li>
      <li>競合薬局は所在のみ。処方箋枚数は未取得のため、圧力は立地・営業時間の代理指標。</li>
      <li>タイルは国土地理院・OpenStreetMap。Google Maps JS API はキー発行と課金設定が必要なため、
          要件になった段階で差し替える。</li>
    </ul>
  </div>

  <footer class="footer" id="notes">
    自店受診データに基づく記述分析です。市場全体の選択率・因果効果としては解釈しないでください。
  </footer>
</main>

<script id="map-data" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>
<script>
(function () {{
  var D = JSON.parse(document.getElementById("map-data").textContent);

  var gsi = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/pale/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 18, attribution: "地理院タイル（淡色地図）"
  }});
  var gsiStd = L.tileLayer("https://cyberjapandata.gsi.go.jp/xyz/std/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 18, attribution: "地理院タイル（標準地図）"
  }});
  var osm = L.tileLayer("https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
    maxZoom: 19, attribution: "&copy; OpenStreetMap contributors"
  }});

  var map = L.map("map", {{
    center: [D.pharmacy.lat, D.pharmacy.lon], zoom: 13, layers: [gsi], scrollWheelZoom: false
  }});
  map.on("focus", function () {{ map.scrollWheelZoom.enable(); }});
  map.on("blur", function () {{ map.scrollWheelZoom.disable(); }});

  /* --- 自店 --- */
  var storeLayer = L.layerGroup([
    L.circleMarker([D.pharmacy.lat, D.pharmacy.lon], {{
      radius: 9, color: "#0f6a6a", fillColor: "#0f6a6a", fillOpacity: .95, weight: 2
    }}).bindPopup("<b>" + D.pharmacy.name + "</b><br>自店")
  ]).addTo(map);

  /* --- クリニック: 半径は log1p(件数) --- */
  var maxLog = Math.log1p(D.maxN);
  function radiusFor(n) {{ return 4 + 22 * (Math.log1p(n) / maxLog); }}
  var clinicLayer = L.layerGroup();
  D.clinics.forEach(function (c) {{
    L.circleMarker([c.lat, c.lon], {{
      radius: radiusFor(c.n),
      color: c.gate ? "#c45c26" : "#2f6f9f",
      fillColor: c.gate ? "#c45c26" : "#2f6f9f",
      fillOpacity: .42, weight: 1.2
    }}).bindPopup(
      "<b>" + c.name + "</b><br>処方箋 " + c.n.toLocaleString() + " 件<br>" +
      (c.sp || "-") + " / " + (c.gate ? "門前型" : "非門前型") +
      (c.km !== null ? "<br>薬局まで直線 " + c.km.toFixed(3) + " km" : "")
    ).addTo(clinicLayer);
  }});
  clinicLayer.addTo(map);

  /* --- メッシュ来局率（対数スケールのコロプレス） --- */
  function meshColor(rate) {{
    if (!rate) {{ return "#eeeae0"; }}
    for (var i = 0; i < D.meshCuts.length; i++) {{
      if (rate <= D.meshCuts[i]) {{ return D.meshBands[i].color; }}
    }}
    return D.meshBands[D.meshBands.length - 1].color;
  }}
  var meshLayer = L.layerGroup();
  D.meshes.forEach(function (m) {{
    L.rectangle([
      [m.lat - D.meshHalf.lat, m.lon - D.meshHalf.lon],
      [m.lat + D.meshHalf.lat, m.lon + D.meshHalf.lon]
    ], {{
      color: "#8d8577", weight: .4, fillColor: meshColor(m.rate),
      fillOpacity: m.rate ? .6 : .18
    }}).bindPopup(
      "メッシュ " + m.code + "<br>人口 " + m.pop.toLocaleString() +
      "<br>来局ユニーク " + m.uniq.toLocaleString() +
      "<br>来局率 " + (m.rate * 100).toFixed(2) + "%"
    ).addTo(meshLayer);
  }});

  /* --- 競合薬局 --- */
  var compLayer = L.layerGroup();
  D.competitors.forEach(function (p) {{
    L.circleMarker([p.lat, p.lon], {{
      radius: 4.5, color: "#2f6f9f", fillColor: "#fff", fillOpacity: .9, weight: 2
    }}).bindPopup("<b>" + p.name + "</b><br>競合薬局" +
      (p.km !== null ? "<br>自店から直線 " + p.km.toFixed(3) + " km" : "")).addTo(compLayer);
  }});

  /* --- 患者密度（集約済みグリッドの KDE ヒート） --- */
  var heatLayer = null;
  if (window.L && L.heatLayer && D.density.points.length) {{
    heatLayer = L.heatLayer(D.density.points, {{
      radius: 26, blur: 20, max: D.density.max, minOpacity: .30,
      gradient: {{ 0.3: "#ffeda0", 0.55: "#feb24c", 0.78: "#fc4e2a", 1.0: "#bd0026" }}
    }});
  }}

  var overlays = {{
    "自店": storeLayer,
    "クリニック（円=件数の対数）": clinicLayer,
    "メッシュ来局率": meshLayer
  }};
  overlays["競合薬局（" + D.competitors.length + "件）"] = compLayer;
  if (heatLayer) {{ overlays["患者密度（集約KDE）"] = heatLayer; }}
  L.control.layers(
    {{ "地理院 淡色": gsi, "地理院 標準": gsiStd, "OpenStreetMap": osm }},
    overlays, {{ collapsed: false }}
  ).addTo(map);

  /* --- 地図上の凡例 --- */
  var legend = L.control({{ position: "bottomright" }});
  legend.onAdd = function () {{
    var div = L.DomUtil.create("div", "map-legend");
    var rows = D.ticks.map(function (n) {{
      var r = radiusFor(n);
      return '<div style="display:flex;align-items:center;gap:6px;margin:2px 0">' +
        '<span style="display:inline-block;width:' + (2 * r) + 'px;height:' + (2 * r) +
        'px;border-radius:50%;background:rgba(196,92,38,.45);border:1px solid #c45c26"></span>' +
        '<span>' + n.toLocaleString() + ' 件</span></div>';
    }}).join("");
    div.innerHTML = "<b>クリニック件数</b>（半径は対数）" + rows;
    L.DomEvent.disableClickPropagation(div);
    return div;
  }};
  legend.addTo(map);

  /* --- ページ内の凡例（実数表示） --- */
  var bl = document.getElementById("bubble-legend");
  if (bl) {{
    bl.innerHTML = D.ticks.map(function (n) {{
      var r = radiusFor(n);
      return '<div class="legend-row"><span class="bubble" style="width:' + (2 * r) +
        'px;height:' + (2 * r) + 'px"></span><span class="num">' + n.toLocaleString() +
        '</span> 件</div>';
    }}).join("");
  }}
  var ml = document.getElementById("mesh-legend");
  if (ml) {{
    ml.innerHTML =
      '<div class="legend-row"><span class="swatch" style="background:#eeeae0"></span>' +
      '<span class="num">0%</span>（来局なし）</div>' +
      D.meshBands.map(function (b) {{
        return '<div class="legend-row"><span class="swatch" style="background:' + b.color +
          '"></span><span class="num">' + (b.lo * 100).toFixed(2) + '〜' +
          (b.hi * 100).toFixed(2) + '%</span></div>';
      }}).join("");
  }}
}}());
</script>
<script data-shell="sidebar">
{sidebar_js()}
</script>
</body>
</html>
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


def publish_docs(path: Path) -> Path:
    DOCS.mkdir(parents=True, exist_ok=True)
    target = DOCS / "map.html"
    shutil.copy2(path, target)
    return target


if __name__ == "__main__":
    p = build()
    print("wrote", p, f"({p.stat().st_size/1024:.0f} KB)")
    print("published", publish_docs(p))
