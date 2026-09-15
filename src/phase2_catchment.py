"""Phase 2: Clinic Catchment Area（GIS・ネットワーク・競合圧力）。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from src.io import (
    PHARMACY_LAT,
    PHARMACY_LON,
    PHARMACY_NAME,
    PROCESSED_DIR,
    ROOT,
    SEED,
    ensure_dirs,
    read_csv,
)
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [np.asarray(lat1, float), np.asarray(lon1, float), np.asarray(lat2, float), np.asarray(lon2, float)])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 2 * r * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def std_dev_ellipse(lats: np.ndarray, lons: np.ndarray) -> Dict:
    """平面近似の標準偏差楕円（記述用。厳密な測地は Phase 後期で EPSG:6674 へ）。"""
    x = lons - lons.mean()
    y = lats - lats.mean()
    if len(x) < 3:
        return {"ok": False}
    cov = np.cov(x, y)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    # degrees approx
    a = 2 * np.sqrt(max(eigvals[0], 0)) * 111.0  # lon deg rough -> km at mid-lat later
    b = 2 * np.sqrt(max(eigvals[1], 0)) * 111.0
    # better: convert using local meters
    lat0 = float(lats.mean())
    mx = x * np.cos(np.radians(lat0)) * 111_320
    my = y * 110_540
    cov_m = np.cov(mx, my)
    ev, evec = np.linalg.eigh(cov_m)
    ev = ev[::-1]
    evec = evec[:, ::-1]
    major = 2 * np.sqrt(max(ev[0], 0)) / 1000.0
    minor = 2 * np.sqrt(max(ev[1], 0)) / 1000.0
    angle = float(np.degrees(np.arctan2(evec[1, 0], evec[0, 0])) % 180)
    return {
        "ok": True,
        "centroid_lat": float(lats.mean()),
        "centroid_lon": float(lons.mean()),
        "major_km": float(major),
        "minor_km": float(minor),
        "angle_deg": angle,
        "n": int(len(lats)),
    }


def load_visits() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    vt = read_csv("visit_triangle")
    vt["軸"] = np.select(
        [vt["立地パターン"].astype(str).eq("門前型"), vt["立地パターン"].astype(str).isin(NON_GATE)],
        ["門前型", "非門前型"],
        default="不明",
    )
    cm = read_csv("clinic_master")
    mesh = read_csv("mesh_population")
    comp = read_csv("competitor_pharmacy")
    return vt, cm, mesh, comp


# ---------------------------------------------------------------------------
# 1. Clinic catchments for top clinics
# ---------------------------------------------------------------------------

def clinic_catchments(vt: pd.DataFrame, min_visits: int = 100) -> pd.DataFrame:
    ensure_dirs()
    _setup_font()
    counts = vt.dropna(subset=["クリニックID"]).groupby(["クリニックID", "クリニック名"]).size().rename("件数")
    top = counts[counts >= min_visits].sort_values(ascending=False).reset_index()

    rows = []
    fig, axes = plt.subplots(2, 3, figsize=(12, 8))
    axes = axes.ravel()
    for i, r in top.head(6).iterrows():
        sub = vt.loc[
            (vt["クリニックID"] == r["クリニックID"])
            & vt["患者緯度"].notna()
            & vt["患者経度"].notna()
        ].copy()
        # 商圏記述は外れ値除外（道路km≤10）。全件件数は別掲。
        d_road_all = pd.to_numeric(sub["患者→クリニック_道路km"], errors="coerce")
        d_lin_all = pd.to_numeric(sub["患者→クリニック_直線km"], errors="coerce")
        sub_c = sub.loc[(d_road_all <= 10) | ((d_road_all.isna()) & (d_lin_all <= 5))].copy()
        # さらに直線>15kmは除外（フェリー経路等）
        sub_c = sub_c.loc[pd.to_numeric(sub_c["患者→クリニック_直線km"], errors="coerce").fillna(0) <= 15]
        lat = sub_c["患者緯度"].astype(float).values
        lon = sub_c["患者経度"].astype(float).values
        ell = std_dev_ellipse(lat, lon) if len(sub_c) >= 3 else {"ok": False}
        d_lin = pd.to_numeric(sub_c["患者→クリニック_直線km"], errors="coerce")
        d_road = pd.to_numeric(sub_c["患者→クリニック_道路km"], errors="coerce")
        rows.append(
            {
                "クリニックID": r["クリニックID"],
                "クリニック名": r["クリニック名"],
                "件数": int(r["件数"]),
                "座標あり件数": int(len(sub)),
                "商圏サンプル件数_道路10km内": int(len(sub_c)),
                "直線km_中央値": float(d_lin.median()) if d_lin.notna().any() else np.nan,
                "道路km_中央値": float(d_road.median()) if d_road.notna().any() else np.nan,
                "重心緯度": ell.get("centroid_lat"),
                "重心経度": ell.get("centroid_lon"),
                "楕円長軸_km": ell.get("major_km"),
                "楕円短軸_km": ell.get("minor_km"),
                "楕円方位_度": ell.get("angle_deg"),
            }
        )
        ax = axes[i]
        if len(sub_c) >= 10:
            # 描画用に最大2000点サンプリング（KDEの負荷軽減）
            if len(sub_c) > 2000:
                rng = np.random.default_rng(SEED)
                idx = rng.choice(len(sub_c), 2000, replace=False)
                lat_p, lon_p = lat[idx], lon[idx]
            else:
                lat_p, lon_p = lat, lon
            try:
                kde = gaussian_kde(np.vstack([lon_p, lat_p]))
                xmin, xmax = lon_p.min() - 0.01, lon_p.max() + 0.01
                ymin, ymax = lat_p.min() - 0.01, lat_p.max() + 0.01
                xx, yy = np.meshgrid(np.linspace(xmin, xmax, 60), np.linspace(ymin, ymax, 60))
                zz = kde(np.vstack([xx.ravel(), yy.ravel()])).reshape(xx.shape)
                levels = np.quantile(zz, [0.2, 0.5])
                ax.contour(xx, yy, zz, levels=levels, colors=["#4C78A8", "#E45756"], linewidths=1.2)
            except Exception:
                pass
            ax.scatter(lon_p, lat_p, s=6, alpha=0.25, c="#9ecae1")
        if ell.get("ok"):
            ax.scatter([ell["centroid_lon"]], [ell["centroid_lat"]], c="#E45756", s=40, marker="x")
        clat = pd.to_numeric(sub["クリニック緯度"], errors="coerce").dropna()
        clon = pd.to_numeric(sub["クリニック経度"], errors="coerce").dropna()
        if len(clat):
            ax.scatter([clon.iloc[0]], [clat.iloc[0]], c="#c45c26", s=50, marker="^", label="clinic")
        ax.scatter([PHARMACY_LON], [PHARMACY_LAT], c="#0f6a6a", s=50, marker="s")
        med = d_road.median() if d_road.notna().any() else np.nan
        ax.set_title(f"{r['クリニック名'][:18]}\nN={int(r['件数'])} / 中央道路{med:.2f}km", fontsize=9)
        ax.set_xlabel("経度")
        ax.set_ylabel("緯度")
        ax.tick_params(labelsize=7)

    for j in range(len(top.head(6)), 6):
        axes[j].axis("off")
    fig.suptitle(
        f"{PHARMACY_NAME} 上位クリニックの患者住所分布（KDE等高線・重心）\n注: 自店経由患者のみ。真のクリニック商圏ではない",
        y=1.02,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "phase2_clinic_catchments.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    out = pd.DataFrame(rows)
    out.to_csv(PROCESSED_DIR / "clinic_catchments_top.csv", index=False, encoding="utf-8-sig")
    return out


# ---------------------------------------------------------------------------
# 2. District x clinic matrix
# ---------------------------------------------------------------------------

def district_clinic_matrix(vt: pd.DataFrame, top_n_clinic: int = 15, top_n_city: int = 12) -> Dict:
    ensure_dirs()
    _setup_font()
    df = vt.dropna(subset=["クリニック名"]).copy()
    df["市区町村"] = df["患者住所_市区町村"].fillna("不明")
    top_c = df["クリニック名"].value_counts().head(top_n_clinic).index
    top_city = df["市区町村"].value_counts().head(top_n_city).index
    sub = df.loc[df["クリニック名"].isin(top_c) & df["市区町村"].isin(top_city)]
    mat = pd.crosstab(sub["市区町村"], sub["クリニック名"])
    # reorder
    mat = mat.loc[top_city.intersection(mat.index), [c for c in top_c if c in mat.columns]]
    row_share = mat.div(mat.sum(axis=1).replace(0, np.nan), axis=0)
    col_share = mat.div(mat.sum(axis=0).replace(0, np.nan), axis=1)

    mat.to_csv(PROCESSED_DIR / "district_clinic_counts.csv", encoding="utf-8-sig")
    row_share.to_csv(PROCESSED_DIR / "district_clinic_row_share.csv", encoding="utf-8-sig")
    col_share.to_csv(PROCESSED_DIR / "district_clinic_col_share.csv", encoding="utf-8-sig")

    # top pairs by row share
    pairs = []
    for city in row_share.index:
        s = row_share.loc[city].dropna().sort_values(ascending=False)
        if len(s):
            pairs.append(
                {
                    "市区町村": city,
                    "第1クリニック": s.index[0],
                    "選択率_自店内": float(s.iloc[0]),
                    "件数": int(mat.loc[city, s.index[0]]),
                    "市区町村合計": int(mat.loc[city].sum()),
                }
            )
    pairs_df = pd.DataFrame(pairs).sort_values("選択率_自店内", ascending=False)
    pairs_df.to_csv(PROCESSED_DIR / "district_top_clinic_pairs.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(12, 6))
    im = ax.imshow(row_share.values.astype(float), aspect="auto", cmap="YlGnBu", vmin=0, vmax=1)
    ax.set_xticks(range(row_share.shape[1]))
    ax.set_xticklabels([c[:10] for c in row_share.columns], rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(row_share.shape[0]))
    ax.set_yticklabels(row_share.index, fontsize=9)
    ax.set_title("地区別クリニック選択率（行正規化）\n注: 自店来局患者内の選択率。市場全体の選択率ではない")
    fig.colorbar(im, ax=ax, fraction=0.025, label="行内シェア")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase2_district_clinic_heatmap.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # non-gate only heatmap (smaller)
    ng = df.loc[df["軸"] == "非門前型"]
    if len(ng) > 50:
        top_c2 = ng["クリニック名"].value_counts().head(12).index
        top_city2 = ng["市区町村"].value_counts().head(10).index
        m2 = pd.crosstab(
            ng.loc[ng["クリニック名"].isin(top_c2) & ng["市区町村"].isin(top_city2), "市区町村"],
            ng.loc[ng["クリニック名"].isin(top_c2) & ng["市区町村"].isin(top_city2), "クリニック名"],
        )
        rs2 = m2.div(m2.sum(axis=1).replace(0, np.nan), axis=0)
        fig, ax = plt.subplots(figsize=(11, 5.5))
        im = ax.imshow(rs2.values.astype(float), aspect="auto", cmap="Oranges", vmin=0, vmax=1)
        ax.set_xticks(range(rs2.shape[1]))
        ax.set_xticklabels([c[:10] for c in rs2.columns], rotation=45, ha="right", fontsize=8)
        ax.set_yticks(range(rs2.shape[0]))
        ax.set_yticklabels(rs2.index, fontsize=9)
        ax.set_title("【非門前のみ】地区別クリニック選択率（自店内）")
        fig.colorbar(im, ax=ax, fraction=0.03)
        fig.tight_layout()
        fig.savefig(FIGURES / "phase2_district_clinic_nongate.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    return {"matrix": mat, "row_share": row_share, "pairs": pairs_df}


# ---------------------------------------------------------------------------
# 3. Mesh visit rate + simple Moran
# ---------------------------------------------------------------------------

def mesh_visit_rate(vt: pd.DataFrame, mesh: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    pts = vt.dropna(subset=["患者緯度", "患者経度"]).copy()
    # 5km圏メッシュへの割当は、薬局から直線≤5.5kmの患者に限定（遠方割当による歪み防止）
    d_ph = pd.to_numeric(pts["患者→薬局_直線km"], errors="coerce")
    pts = pts.loc[d_ph.notna() & (d_ph <= 5.5)].copy()
    mlat = mesh["中心緯度"].astype(float).values
    mlon = mesh["中心経度"].astype(float).values
    plat = pts["患者緯度"].astype(float).values
    plon = pts["患者経度"].astype(float).values
    assign = np.empty(len(pts), dtype=np.int32)
    # 緯度経度を局所メートルに変換して最近傍（ハバーサイン行列より軽量）
    lat0 = float(np.nanmedian(mlat))
    mx = (mlon - PHARMACY_LON) * np.cos(np.radians(lat0)) * 111_320.0
    my = (mlat - PHARMACY_LAT) * 110_540.0
    px = (plon - PHARMACY_LON) * np.cos(np.radians(lat0)) * 111_320.0
    py = (plat - PHARMACY_LAT) * 110_540.0
    mesh_xy = np.column_stack([mx, my])
    for i in range(0, len(pts), 4000):
        sl = slice(i, min(i + 4000, len(pts)))
        dx = px[sl][:, None] - mesh_xy[None, :, 0]
        dy = py[sl][:, None] - mesh_xy[None, :, 1]
        assign[sl] = (dx * dx + dy * dy).argmin(axis=1)
    pts = pts.copy()
    pts["mesh_idx"] = assign
    uniq = pts.groupby("mesh_idx")["患者ID"].nunique().rename("来局ユニーク")
    mesh2 = mesh.copy().reset_index(drop=True)
    mesh2["来局ユニーク"] = uniq.reindex(mesh2.index).fillna(0).astype(int)
    mesh2["総人口"] = pd.to_numeric(mesh2["総人口"], errors="coerce")
    mesh2["来局率"] = np.where(mesh2["総人口"] > 0, mesh2["来局ユニーク"] / mesh2["総人口"], np.nan)
    mesh2["距離km"] = pd.to_numeric(mesh2["くつき薬局南茨木店→メッシュ中心_直線km"], errors="coerce")
    mesh2.to_csv(PROCESSED_DIR / "mesh_visit_rate.csv", index=False, encoding="utf-8-sig")

    valid = mesh2.dropna(subset=["来局率"]).copy()
    # 来局率>1は人口秘匿・境界効果の疑い → Moranからは除外して記述
    valid = valid.loc[valid["来局率"] <= 1.0].copy()
    y = valid["来局率"].to_numpy(dtype=np.float64)
    coords = valid[["中心緯度", "中心経度"]].to_numpy(dtype=np.float64)
    n = len(y)
    D = haversine_km(coords[:, 0][:, None], coords[:, 1][:, None], coords[:, 0][None, :], coords[:, 1][None, :])
    knn = 6
    W = np.zeros((n, n), dtype=np.float64)
    for i in range(n):
        nbrs = np.argsort(D[i])[1 : knn + 1]
        W[i, nbrs] = 1.0
    rs = W.sum(axis=1, keepdims=True)
    rs[rs == 0] = 1.0
    W = W / rs
    z = y - y.mean()
    den = float(np.dot(z, z))
    moran = float((n / W.sum()) * (z @ (W @ z)) / den) if den > 0 else np.nan
    local = (z * (W @ z)) / (den / n)
    valid = valid.copy()
    valid["local_I"] = local
    q75 = np.nanpercentile(local, 75)
    hot = valid.loc[(z > 0) & (local >= q75)].sort_values("来局率", ascending=False).head(10)
    cold = valid.loc[(z < 0) & (local >= q75)].sort_values("来局率").head(10)

    fig, ax = plt.subplots(figsize=(8, 6))
    sc = ax.scatter(
        valid["中心経度"],
        valid["中心緯度"],
        c=valid["来局率"] * 1000,
        s=40,
        cmap="viridis",
        alpha=0.85,
    )
    ax.scatter([PHARMACY_LON], [PHARMACY_LAT], c="#c45c26", s=80, marker="*", label="薬局")
    fig.colorbar(sc, ax=ax, label="来局率×1000")
    ax.set_title(
        f"メッシュ来局率（患者を最近傍メッシュへ割当）\nMoran's I≈{moran:.3f}（kNN=6・記述） Nメッシュ={n}"
    )
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "phase2_mesh_visit_rate.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    hot.to_csv(PROCESSED_DIR / "mesh_hotspots.csv", index=False, encoding="utf-8-sig")
    cold.to_csv(PROCESSED_DIR / "mesh_coldspots.csv", index=False, encoding="utf-8-sig")
    return {"moran": moran, "n": n, "hot": hot, "cold": cold, "mesh": mesh2}


# ---------------------------------------------------------------------------
# 4. Competitor pressure on mesh
# ---------------------------------------------------------------------------

def competitor_pressure(mesh: pd.DataFrame, comp: pd.DataFrame) -> pd.DataFrame:
    ensure_dirs()
    mlat = mesh["中心緯度"].astype(float).values
    mlon = mesh["中心経度"].astype(float).values
    clat = comp["緯度"].astype(float).values
    clon = comp["経度"].astype(float).values
    D = haversine_km(mlat[:, None], mlon[:, None], clat[None, :], clon[None, :])
    nearest = D.min(axis=1)
    n500 = (D <= 0.5).sum(axis=1)
    n1000 = (D <= 1.0).sum(axis=1)

    # opening hours advantage proxies
    day_cols = [c for c in comp.columns if c.startswith("営業時間_")]
    def hours_len(s: str) -> float:
        s = str(s)
        if s in ("", "nan", "休"):
            return 0.0
        # sum spans like 9:00-20:00 or multiple
        total = 0.0
        for part in s.replace(" ", "").split(","):
            if "-" not in part or part == "休":
                continue
            try:
                a, b = part.split("-", 1)
                ah, am = a.split(":")
                bh, bm = b.split(":")
                total += (int(bh) + int(bm) / 60) - (int(ah) + int(am) / 60)
            except Exception:
                continue
        return max(total, 0.0)

    comp = comp.copy()
    comp["週合計営業h"] = comp[day_cols].apply(lambda r: sum(hours_len(v) for v in r), axis=1)
    # pharmacy own hours unknown -> use median competitor as baseline note
    sunday_open = (comp["営業時間_日"].astype(str) != "休") & (comp["営業時間_日"].astype(str).str.len() > 0)
    # for each mesh: count sunday-open competitors within 1km
    sun_idx = np.where(sunday_open.values)[0]
    n_sun_1km = (D[:, sun_idx] <= 1.0).sum(axis=1) if len(sun_idx) else np.zeros(len(mesh))

    out = mesh.copy()
    out["最近隣競合_km"] = nearest
    out["競合数_500m"] = n500
    out["競合数_1km"] = n1000
    out["日曜営業競合_1km"] = n_sun_1km
    out.to_csv(PROCESSED_DIR / "mesh_competitor_pressure.csv", index=False, encoding="utf-8-sig")

    _setup_font()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    ax = axes[0]
    sc = ax.scatter(out["中心経度"], out["中心緯度"], c=out["競合数_1km"], s=35, cmap="Reds")
    ax.scatter([PHARMACY_LON], [PHARMACY_LAT], c="#0f6a6a", marker="*", s=90)
    fig.colorbar(sc, ax=ax, label="1km内競合数")
    ax.set_title("メッシュ別 競合密度（1km）")
    ax = axes[1]
    sc = ax.scatter(out["中心経度"], out["中心緯度"], c=out["最近隣競合_km"], s=35, cmap="Blues_r")
    ax.scatter([PHARMACY_LON], [PHARMACY_LAT], c="#0f6a6a", marker="*", s=90)
    fig.colorbar(sc, ax=ax, label="最近隣競合km")
    ax.set_title("メッシュ別 最近隣競合距離")
    fig.suptitle(f"{PHARMACY_NAME} 競合の空間的圧力（競合66件・2km圏収録）", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase2_competitor_pressure.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# 5. Network: city - clinic - pharmacy
# ---------------------------------------------------------------------------

def network_analysis(vt: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    df = vt.dropna(subset=["クリニック名"]).copy()
    df["市区町村"] = df["患者住所_市区町村"].fillna("不明")
    # focus top to keep graph readable
    top_city = df["市区町村"].value_counts().head(20).index
    top_clinic = df["クリニック名"].value_counts().head(25).index
    sub = df.loc[df["市区町村"].isin(top_city) & df["クリニック名"].isin(top_clinic)]

    G = nx.DiGraph()
    pharmacy = PHARMACY_NAME
    for (city, clinic), n in sub.groupby(["市区町村", "クリニック名"]).size().items():
        G.add_edge(f"地:{city}", f"ク:{clinic}", weight=int(n))
    for clinic, n in sub.groupby("クリニック名").size().items():
        G.add_edge(f"ク:{clinic}", f"薬:{pharmacy}", weight=int(n))

    # betweenness on clinics (undirected projection of clinic nodes via flows)
    # Use betweenness with weight=1/count
    H = G.copy()
    for u, v, d in H.edges(data=True):
        d["dist"] = 1.0 / max(d.get("weight", 1), 1)
    bt = nx.betweenness_centrality(H, weight="dist", normalized=True)
    clinic_bt = (
        pd.Series({k.replace("ク:", ""): v for k, v in bt.items() if k.startswith("ク:")})
        .sort_values(ascending=False)
        .head(15)
    )
    clinic_bt.rename("媒介中心性").to_csv(PROCESSED_DIR / "clinic_betweenness.csv", encoding="utf-8-sig")

    # plot top betweenness clinics bar
    fig, ax = plt.subplots(figsize=(9, 5))
    clinic_bt.iloc[::-1].plot(kind="barh", ax=ax, color="#2f6f9f")
    ax.set_title("クリニック媒介中心性（地区↔自店の結節）\n注: 自店フロー上の重要性。市場全体の中心性ではない")
    ax.set_xlabel("betweenness")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase2_clinic_betweenness.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {"betweenness": clinic_bt, "n_edges": G.number_of_edges(), "n_nodes": G.number_of_nodes()}


# ---------------------------------------------------------------------------
# Folium overview map
# ---------------------------------------------------------------------------

def folium_map(catch: pd.DataFrame, mesh_rate: pd.DataFrame, comp: pd.DataFrame) -> Path:
    import folium
    from folium.plugins import MarkerCluster

    m = folium.Map(location=[PHARMACY_LAT, PHARMACY_LON], zoom_start=13, tiles="OpenStreetMap")
    folium.Marker(
        [PHARMACY_LAT, PHARMACY_LON],
        popup=PHARMACY_NAME,
        icon=folium.Icon(color="green", icon="plus-sign"),
    ).add_to(m)

    # top clinics
    for _, r in catch.iterrows():
        # use clinic coords from name join later - catch has centroid of patients
        if pd.notna(r.get("重心緯度")):
            folium.CircleMarker(
                [r["重心緯度"], r["重心経度"]],
                radius=6,
                color="#c45c26",
                fill=True,
                popup=f"{r['クリニック名']}<br>件数={r['件数']}<br>患者重心",
            ).add_to(m)

    # competitors
    for _, r in comp.iterrows():
        folium.CircleMarker(
            [float(r["緯度"]), float(r["経度"])],
            radius=3,
            color="#888",
            fill=True,
            popup=r["薬局名"],
        ).add_to(m)

    # mesh rates as circles
    mr = mesh_rate.dropna(subset=["来局率"]).copy()
    mr = mr.loc[mr["来局ユニーク"] > 0]
    for _, r in mr.iterrows():
        folium.CircleMarker(
            [float(r["中心緯度"]), float(r["中心経度"])],
            radius=max(3, min(18, float(r["来局ユニーク"]) ** 0.5)),
            color="#0f6a6a",
            fill=True,
            fill_opacity=0.35,
            popup=f"mesh {r['メッシュコード']}<br>来局率={r['来局率']:.4f}<br>ユニーク={int(r['来局ユニーク'])}",
        ).add_to(m)

    out = FIGURES / "phase2_map.html"
    m.save(str(out))
    return out


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def write_reports(catch, matrix, mesh_stats, pressure, net, map_path: Path, vt: pd.DataFrame) -> Dict[str, Path]:
    pairs = matrix["pairs"].head(10)
    hot = mesh_stats["hot"][["メッシュコード", "総人口", "来局ユニーク", "来局率", "距離km"]].head(5)
    cold = mesh_stats["cold"][["メッシュコード", "総人口", "来局ユニーク", "来局率", "距離km"]].head(5)
    bt = net["betweenness"]

    # Markdown
    md = f"""# Phase 2: Clinic Catchment Area

## わかったこと3点

1. **上位クリニックの商圏は徒歩圏中心。** 件数≥100の施設で患者→クリニック道路km中央値はおおむね1km前後（詳細は `clinic_catchments_top.csv`）。
2. **地区×クリニックの偏りは依頼書仮説と整合しうる。** 行正規化選択率の上位ペアを表に示す（**自店患者内の選択率**）。
3. **メッシュ来局率に空間相関（Moran's I≈{mesh_stats['moran']:.3f}）。** ホット/コールドスポットは獲得余地の候補。競合1km密度と併せて読む。

## わからなかったこと3点

1. 真の地区別クリニック選択率（自店非来局者のクリニック選択が非観測）。
2. 厳密な測地商圏面積（本Phaseは局所平面近似。EPSG:6674投影は次段で強化可能）。
3. 競合の処方箋規模がないため、圧力指標は立地・営業時間代理に留まる。

## 次に必要なデータ

- クリニック総発行数、競合規模代理、他店舗データ（`docs/QUESTIONS_TO_CLIENT.md`）

---

## 1. クリニック別商圏

![catchment](figures/phase2_clinic_catchments.png)

```
{catch.head(10).to_string(index=False)}
```

## 2. 地区 × クリニック

![heatmap](figures/phase2_district_clinic_heatmap.png)

![nongate](figures/phase2_district_clinic_nongate.png)

### 地区内第1クリニック（自店患者内選択率）

```
{pairs.to_string(index=False)}
```

## 3. メッシュ来局率・空間相関

![mesh](figures/phase2_mesh_visit_rate.png)

- Moran's I（kNN=6）≈ **{mesh_stats['moran']:.3f}** / メッシュ数 {mesh_stats['n']}

ホットスポット候補（抜粋）:

```
{hot.to_string(index=False)}
```

コールドスポット候補（抜粋）:

```
{cold.to_string(index=False)}
```

## 4. 競合圧力

![comp](figures/phase2_competitor_pressure.png)

- 競合収録: 2km圏66件。メッシュ別に最近隣距離・500m/1km件数・日曜営業競合を付与 → `mesh_competitor_pressure.csv`

## 5. ネットワーク（媒介中心性）

![bt](figures/phase2_clinic_betweenness.png)

```
{bt.head(10).to_string()}
```

地図: [phase2_map.html](figures/phase2_map.html)

> 注: すべて自店受診フローに基づく。市場全体の商圏・選択率・中心性ではない。
"""
    md_path = REPORTS / "phase2_catchment.md"
    md_path.write_text(md, encoding="utf-8")

    # HTML
    rep = HtmlReport(
        title="Phase 2 Clinic Catchment",
        subtitle="クリニック商圏・地区選択・メッシュ来局率・競合圧力・ネットワーク。門前が規模、非門前が成長余地、という Phase1 の軸を空間で確認する。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 2",
        active_phase=2,
    )
    rep.add_kpi("Moran's I", f"{mesh_stats['moran']:.3f}", "メッシュ来局率・kNN=6")
    rep.add_kpi("分析メッシュ", f"{mesh_stats['n']}", "5km圏メッシュ")
    rep.add_kpi("上位結節クリニック", bt.index[0][:14] if len(bt) else "-", "媒介中心性1位")
    rep.add_kpi("競合薬局", "66", "半径2km収録")

    rep.callout(
        "わかったこと",
        [
            "上位クリニック商圏は徒歩圏中心（道路km中央値〜1km）。",
            "地区×クリニックの偏りを自店内選択率として定量化。",
            f"メッシュ来局率に空間相関（I≈{mesh_stats['moran']:.3f}）。コールドスポットは獲得余地候補。",
        ],
        kind="ok",
    )
    rep.callout(
        "限界",
        [
            "分子は自店経由患者のみ（真の地区別クリニック選択率ではない）。",
            "競合の処方箋枚数なし → 圧力は立地・営業時間代理。",
            "楕円・距離は局所平面近似（厳密投影は今後強化可）。",
        ],
        kind="warn",
    )

    rep.section("catchment", "1. クリニック別商圏", "件数≥100の上位施設。KDE等高線と患者重心。")
    rep.figure(FIGURES / "phase2_clinic_catchments.png", "自店経由患者の住所点群に基づく記述的商圏")
    rep.table(
        ["クリニック", "件数", "道路km中央", "楕円長軸km"],
        [
            [
                r["クリニック名"][:20],
                int(r["件数"]),
                f"{r['道路km_中央値']:.2f}" if pd.notna(r["道路km_中央値"]) else "-",
                f"{r['楕円長軸_km']:.2f}" if pd.notna(r["楕円長軸_km"]) else "-",
            ]
            for _, r in catch.head(8).iterrows()
        ],
        numeric_cols=[1, 2, 3],
    )

    rep.section("district", "2. 地区 × クリニック", "行正規化＝地区内シェア（自店患者限定）。")
    rep.figure(FIGURES / "phase2_district_clinic_heatmap.png")
    if (FIGURES / "phase2_district_clinic_nongate.png").exists():
        rep.figure(FIGURES / "phase2_district_clinic_nongate.png", "非門前のみ（軸B）")
    rep.table(
        ["市区町村", "第1クリニック", "自店内選択率", "件数"],
        [
            [r["市区町村"], str(r["第1クリニック"])[:18], f"{r['選択率_自店内']:.1%}", int(r["件数"])]
            for _, r in pairs.iterrows()
        ],
        numeric_cols=[2, 3],
    )

    rep.section("mesh", "3. メッシュ来局率と空間相関")
    rep.figure(FIGURES / "phase2_mesh_visit_rate.png")
    rep.paragraph(f"Moran's I ≈ {mesh_stats['moran']:.3f}（記述統計。推論のp値は未算出）。")

    rep.section("competitor", "4. 競合の空間的圧力")
    rep.figure(FIGURES / "phase2_competitor_pressure.png")

    rep.section("network", "5. ネットワーク媒介中心性", "地区と自店をつなぐ結節クリニック。")
    rep.figure(FIGURES / "phase2_clinic_betweenness.png")
    rep.table(
        ["クリニック", "媒介中心性"],
        [[idx[:24], f"{val:.4f}"] for idx, val in bt.head(10).items()],
        numeric_cols=[1],
    )

    rep.section("map", "6. インタラクティブ地図")
    rep.folium_iframe(map_path, "薬局・患者重心・メッシュ来局・競合")

    html_path = REPORTS / "phase2_catchment.html"
    # save map next to html for iframe relative path
    # map is in figures/; html in reports/ so fix iframe to figures/phase2_map.html
    rep.blocks = [
        b.replace(f'src="{map_path.name}"', 'src="figures/phase2_map.html"')
        if "iframe" in b and map_path.name in b
        else b
        for b in rep.blocks
    ]
    rep.save(html_path)
    return {"md": md_path, "html": html_path}


def run_phase2() -> Dict:
    np.random.seed(SEED)
    ensure_dirs()
    vt, cm, mesh, comp = load_visits()
    catch = clinic_catchments(vt)
    matrix = district_clinic_matrix(vt)
    mesh_stats = mesh_visit_rate(vt, mesh)
    # merge visit rate onto pressure base
    pressure = competitor_pressure(mesh_stats["mesh"], comp)
    net = network_analysis(vt)
    map_path = folium_map(catch, mesh_stats["mesh"], comp)
    paths = write_reports(catch, matrix, mesh_stats, pressure, net, map_path, vt)
    return {"paths": paths, "moran": mesh_stats["moran"], "top_bt": net["betweenness"].index[0]}


if __name__ == "__main__":
    out = run_phase2()
    print("wrote", out["paths"])
    print("Moran I", round(out["moran"], 3), "top betweenness", out["top_bt"])
