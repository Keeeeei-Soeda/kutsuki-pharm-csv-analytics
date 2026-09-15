"""Huffモデル（記述的ベンチマーク）。因果解釈しない。"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
import pandas as pd


def attractiveness_from_competitor(comp: pd.DataFrame) -> pd.DataFrame:
    day_cols = [c for c in comp.columns if c.startswith("営業時間_") and not c.startswith("営業時間_出典")]

    def hours_len(s: str) -> float:
        s = str(s)
        if s in ("", "nan", "休", "None"):
            return 0.0
        total = 0.0
        for part in s.replace(" ", "").split(","):
            if "-" not in part or part == "休":
                continue
            try:
                a, b = part.split("-", 1)
                ah, am = map(int, a.split(":"))
                bh, bm = map(int, b.split(":"))
                total += (bh + bm / 60) - (ah + am / 60)
            except Exception:
                continue
        return max(total, 0.0)

    out = comp.copy()
    out["週合計営業h"] = out[day_cols].apply(lambda r: sum(hours_len(v) for v in r), axis=1)
    out["日曜営業"] = (
        (out.get("営業時間_日", pd.Series(dtype=str)).astype(str) != "休")
        & (out.get("営業時間_日", pd.Series(dtype=str)).astype(str).str.len() > 0)
    ).astype(float)
    # 自店を追加するための魅力度代理
    out["A"] = 1.0 + out["週合計営業h"] / 40.0 + 0.5 * out["日曜営業"]
    return out


def huff_probabilities(
    mesh: pd.DataFrame,
    stores: pd.DataFrame,
    pharmacy_lat: float,
    pharmacy_lon: float,
    pharmacy_A: float,
    lam: float,
) -> pd.DataFrame:
    """
    各メッシュから自店を選ぶ確率（競合+自店）。
    p_i,own = (A_own / d_own^λ) / Σ_k (A_k / d_k^λ)
    """
    mlat = mesh["中心緯度"].astype(float).values
    mlon = mesh["中心経度"].astype(float).values
    # own distance already in mesh
    d_own = np.maximum(mesh["くつき薬局南茨木店→メッシュ中心_直線km"].astype(float).values, 0.05)
    num_own = pharmacy_A / np.power(d_own, lam)

    slat = stores["緯度"].astype(float).values
    slon = stores["経度"].astype(float).values
    A = stores["A"].astype(float).values
    # haversine approx local
    lat0 = np.radians(np.nanmedian(mlat))
    mx = (mlon - pharmacy_lon) * np.cos(lat0) * 111.32
    my = (mlat - pharmacy_lat) * 110.54
    sx = (slon - pharmacy_lon) * np.cos(lat0) * 111.32
    sy = (slat - pharmacy_lat) * 110.54
    # distances km
    dx = mx[:, None] - sx[None, :]
    dy = my[:, None] - sy[None, :]
    d = np.sqrt(dx * dx + dy * dy)
    d = np.maximum(d, 0.05)
    num_comp = A[None, :] / np.power(d, lam)
    den = num_own + num_comp.sum(axis=1)
    p = num_own / den
    out = mesh[["メッシュコード", "中心緯度", "中心経度", "総人口"]].copy()
    out["huff_p"] = p
    out["距離_own_km"] = d_own
    return out


def fit_lambda_grid(
    mesh_with_rate: pd.DataFrame,
    stores: pd.DataFrame,
    pharmacy_lat: float,
    pharmacy_lon: float,
    pharmacy_A: float,
    lambdas: Tuple[float, ...] = (0.5, 1.0, 1.5, 2.0, 2.5, 3.0),
) -> Dict:
    """実測来局率との相関・RMSEでλを探索（記述的当てはまり）。"""
    df = mesh_with_rate.dropna(subset=["来局率"]).copy()
    df = df.loc[(df["来局率"] >= 0) & (df["来局率"] <= 1)]
    best = None
    rows = []
    for lam in lambdas:
        pred = huff_probabilities(df, stores, pharmacy_lat, pharmacy_lon, pharmacy_A, lam)
        merged = df[["メッシュコード", "来局率"]].merge(pred[["メッシュコード", "huff_p"]], on="メッシュコード")
        if len(merged) < 10:
            continue
        corr = float(np.corrcoef(merged["来局率"], merged["huff_p"])[0, 1])
        # scale huff_p to rate magnitude via OLS without intercept optional
        # compare rank / correlation primarily
        rmse = float(np.sqrt(np.mean((merged["来局率"] - merged["huff_p"]) ** 2)))
        # also scaled RMSE
        coef = float(np.dot(merged["huff_p"], merged["来局率"]) / max(np.dot(merged["huff_p"], merged["huff_p"]), 1e-12))
        rmse_s = float(np.sqrt(np.mean((merged["来局率"] - coef * merged["huff_p"]) ** 2)))
        rows.append({"lambda": lam, "corr": corr, "rmse": rmse, "rmse_scaled": rmse_s, "scale": coef})
        score = corr - rmse_s
        if best is None or score > best["score"]:
            best = {"lambda": lam, "corr": corr, "rmse_scaled": rmse_s, "scale": coef, "score": score, "pred": pred}
    return {"grid": pd.DataFrame(rows), "best": best}
