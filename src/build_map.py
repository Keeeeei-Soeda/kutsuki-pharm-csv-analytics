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

from src.axis import TOP2_IDS
from src.io import PHARMACY_LAT, PHARMACY_LON, PHARMACY_NAME, PROCESSED_DIR, ROOT, ensure_dirs, read_csv, REPORTS_DIR, DOCS_DIR
from src.specialty_taxonomy import build_specialty_map
from src.viz.html_report import FOOTER_NOTE
from src.viz.sidebar import FONTS_LINK, PERIOD_LABEL, render_sidebar, sidebar_css, sidebar_js

TARGET_TOWNS = ("千里丘西", "西駅前町", "摂津市千里丘", "新芦屋上", "下穂積")

REPORTS = REPORTS_DIR
DOCS = DOCS_DIR

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
        vt.assign(隣の2院=vt["クリニックID"].astype(str).isin(TOP2_IDS))
        .groupby("クリニックID")["隣の2院"]
        .mean()
        .rename("隣の2院比")
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
            "gate": bool((r["隣の2院比"] or 0) >= 0.5),
        }
        for _, r in df.iterrows()
    ]


def mesh_layer() -> List[dict]:
    path = PROCESSED_DIR / "mesh_visit_rate.csv"
    if not path.exists():
        return []
    m = pd.read_csv(path, encoding="utf-8-sig")
    m = m.dropna(subset=["中心緯度", "中心経度"])
    has_town = "町名" in m.columns
    return [
        {
            "code": str(r["メッシュコード"]),
            "lat": float(r["中心緯度"]),
            "lon": float(r["中心経度"]),
            "pop": int(r["総人口"]) if pd.notna(r["総人口"]) else 0,
            "uniq": int(r["来局ユニーク"]) if pd.notna(r["来局ユニーク"]) else 0,
            "rate": float(r["来局率"]) if pd.notna(r["来局率"]) else 0.0,
            "town": (str(r["町名"]) if has_town and pd.notna(r["町名"]) else ""),
        }
        for _, r in m.iterrows()
    ]


def target_layer(meshes: List[dict]) -> List[dict]:
    """Phase 2 の配布候補地域に当たるメッシュ。"""
    out = []
    for m in meshes:
        town = m.get("town") or ""
        if any(t in town for t in TARGET_TOWNS):
            out.append(m)
    return out


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
    # 青系はクリニック（門前以外）と被るため使わない。薄い黄緑 → 濃い緑。
    mesh_colors = ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"]
    mesh_bands = []
    lows = [0.0] + cuts
    highs = cuts + [float(nonzero[-1]) if nonzero else 0.0]
    for lo, hi, col in zip(lows, highs, mesh_colors):
        mesh_bands.append({"lo": lo, "hi": hi, "color": col})

    max_n = max((c["n"] for c in clinics), default=1)
    total_n = int(sum(c["n"] for c in clinics))
    mesh_rate_max = max((m["rate"] for m in meshes), default=0.0)
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
        "totalN": total_n,
        "ticks": ticks,
        "meshHalf": {"lat": MESH_HALF_LAT, "lon": MESH_HALF_LON},
        "minCellCount": MIN_CELL_COUNT,
        "meshCuts": cuts,
        "meshBands": mesh_bands,
        "meshRateMax": mesh_rate_max,
        "targets": target_layer(meshes),
        "meshWords": ["ほぼ来ていない", "少ない", "ふつう", "多い", "とても多い"],
    }

    toc = [
        ("map-sec", "地図"),
        ("legend", "凡例"),
        ("notes-sec", "専門家向けの詳細"),
    ]
    sidebar = render_sidebar(
        "map", toc, breadcrumb="Kutsuki DataBank / 地図", period=PERIOD_LABEL
    )

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
.map-shell {{
  position: relative;
  z-index: 0;
  isolation: isolate;
  border-radius: 18px;
  border: 1px solid var(--line);
  box-shadow: var(--shadow);
  overflow: hidden;
}}
#map {{ height: 620px; width: 100%; border: 0; border-radius: 0; }}
.legend-grid {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(230px,1fr)); gap:14px; margin-top:14px; }}
.legend-row {{ display:flex; align-items:center; gap:8px; margin:4px 0; font-size:13px; }}
.swatch {{ width:16px; height:16px; border-radius:4px; flex:0 0 auto; border:1px solid rgba(0,0,0,.15); }}
.swatch.dot {{ border-radius:50%; }}
.swatch.ring {{ border-radius:50%; background:#fff; border:2.5px solid #7b5ea7; }}
.bubble {{ background: rgba(120,110,100,.16); border:1.5px solid #8d8577; }}
.bubble-size {{
  border-radius:50%; background: rgba(120,110,100,.16); border: 1.5px solid #8d8577; flex:0 0 auto;
}}
.swatch-dot {{
  width:12px; height:12px; border-radius:50%; flex:0 0 auto; border:1px solid rgba(0,0,0,.12);
}}
.num {{ font-variant-numeric: tabular-nums; }}
.legend-note {{ font-size:12px; color: var(--muted); margin: 8px 0 0; }}
.footer {{ margin-top:36px; color:var(--muted); font-size:12px; border-top:1px solid var(--line); padding-top:16px; }}
.leaflet-container {{ font-family: var(--sans); }}
.leaflet-popup-content-wrapper {{ padding-right: 8px; }}
.leaflet-container a.leaflet-popup-close-button {{
  top: 6px; right: 8px; width: 22px; height: 22px; font-size: 18px; padding: 0;
}}
/* 国旗アイコン付きの既定 prefix を出さない */
.leaflet-control-attribution .leaflet-attribution-flag {{ display: none !important; }}
ul {{ padding-left: 1.2rem; }}
{sidebar_css()}
</style>
{FONTS_LINK}
</head>
<body data-map="1">
{sidebar}
<main class="wrap" id="main">
  <header class="hero">
    <div class="eyebrow">Kutsuki DataBank / 地図</div>
    <h1>商圏マップ</h1>
    <p>患者がどこに住み、どのクリニックから処方箋が来ているかを地図で見ます。</p>
    <div class="meta">
      <span class="chip">{PHARMACY_NAME}</span>
      <span class="chip">{PERIOD_LABEL}</span>
      <span class="chip">データ：2026-07-31まで</span>
    </div>
  </header>
  <section class="takeaway" aria-label="このページのまとめ"><dl>
    <div class="tk-row"><dt>わかったこと</dt><dd>患者の半分以上は薬局から1km以内に住んでいる。1kmを超えると急に来なくなる。</dd></div>
    <div class="tk-row tone-chance"><dt>判断</dt><dd>チャンス。近所には強い。1.5〜2kmに、まだ来ていない人が多い地域がある。</dd></div>
    <div class="tk-row tk-action"><dt>今月やること</dt><dd>千里丘西と西駅前町に、QRコード付きチラシを各2,000枚。配布日と枚数を Phase 5 の記録表に書く。</dd></div>
    <div class="tk-row"><dt>効いたかの見方</dt><dd>配布後8週間で、この2町からの初めての患者が月5人以上（今は月0〜1人）。</dd></div>
    <div class="tk-row tk-link"><dt>くわしくは</dt><dd><a href="phase2_catchment.html#targets">根拠の表・図</a></dd></div>
  </dl></section>

  <h2 id="map-sec">地図</h2>
  <div class="map-shell" id="map-shell" data-map="1">
    <div id="map" role="application" aria-label="商圏マップ"></div>
  </div>
  <p style="color:var(--muted);font-size:13px;margin-top:8px">
    左上の「表示の切替」でレイヤを選べます。円・矩形をクリックすると内訳が出ます。
    地域の色（来局の割合／患者が多い範囲）は同時には出せません。
  </p>

  <h2 id="legend">凡例</h2>
  <div class="card">
    <div class="legend-grid">
      <div>
        <strong style="font-size:13px">クリニック（処方箋の枚数）</strong>
        <div id="bubble-legend"></div>
        <div class="legend-row"><span class="swatch-dot" style="background:#c45c26"></span>隣の2院（はせがわ・平山）</div>
        <div class="legend-row"><span class="swatch-dot" style="background:#2f6f9f"></span>それ以外の医院</div>
        <p style="font-size:12px;color:var(--muted);margin:8px 0 0">
          円が大きいほど処方箋が多い（大きさは実際の差より控えめに表示）。
          グレーの輪は大きさの目安、色は隣の2院／それ以外です。
        </p>
      </div>
      <div>
        <strong style="font-size:13px">地域ごとの来局の割合</strong>
        <div id="mesh-legend"></div>
        <p style="font-size:12px;color:var(--muted);margin:8px 0 0">
          色が濃いほど、その地域の人口のうち自店に来た人の割合が高い。
        </p>
      </div>
      <div>
        <strong style="font-size:13px">その他</strong>
        <div id="other-legend"></div>
      </div>
    </div>
  </div>

  <h2 id="notes-sec">専門家向けの詳細</h2>
  <details class="expert">
  <summary>専門家向けの詳細（縮尺・色分け・秘匿ルール・限界）</summary>
  <div class="expert-body">
  <div class="card">
    <ul>
      <li>クリニックの円の半径は <span class="num">log1p(件数)</span> に比例。件数をそのまま半径にすると
          最大施設1点だけが巨大になり、他が読めなくなるため。表示している数値は実数。</li>
      <li>メッシュ来局率は500mメッシュの「自店来局ユニーク患者 ÷ メッシュ人口」。色は非ゼロ値の五分位で割っている
          （対数でも右に寄って読めないため）。</li>
      <li>患者密度は個別点をプロットしていない。約250mグリッドに集約した KDE ヒートマップで、
          {MIN_CELL_COUNT}件未満のセルは非表示（{density['suppressed_cells']}セルを秘匿）。</li>
      <li>クリニックの円は<strong>自店を経由した処方箋件数</strong>であり、そのクリニックの総発行数ではない。
          自店シェアの分母は観測できない。</li>
      <li>メッシュ来局率の分子は自店患者のみ。他薬局の利用は含まないため、
          地域の「薬局利用率」ではなく<strong>自店の浸透度</strong>として読む。</li>
      <li>患者密度は集約値。セル単位の件数は {MIN_CELL_COUNT} 件以上のものだけを使っている。</li>
      <li>競合薬局は所在のみ。処方箋枚数は未取得のため、圧力は立地・営業時間の代理指標。</li>
      <li>タイルは国土地理院・OpenStreetMap。Google Maps JS API はキー発行と課金設定が必要なため、
          要件になった段階で差し替える（`.map-shell` の z-index 封じ込めとフィルタ連動は共通）。</li>
    </ul>
  </div>
  </div>
  </details>

  <footer class="footer" id="notes">
    {FOOTER_NOTE}
  </footer>
</main>

<script id="map-data" type="application/json">{json.dumps(payload, ensure_ascii=False)}</script>
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
    from src.viz.sidebar import apply_shell

    p = build()
    print("wrote", p, f"({p.stat().st_size/1024:.0f} KB)")
    docs_path = publish_docs(p)
    print("published", docs_path)
    apply_shell(p, "map")
    apply_shell(docs_path, "map")
    print("shell applied")
