"""探索層向けのデータ確認（§2-0）。生CSVは読み取りのみ。コミット対象外。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from src.io import read_csv
from src.phase1_flow import _axis_label
from src.specialty_taxonomy import build_specialty_map


DIST_BINS = [-0.01, 0.5, 1.0, 2.0, 1e9]
DIST_LABELS = ["0-0.5", "0.5-1", "1-2", "2+"]


def _counts(series: pd.Series) -> pd.Series:
    return series.value_counts(dropna=False).sort_values(ascending=False)


def main() -> None:
    vt = read_csv("visit_triangle")
    pm = read_csv("patient_master")
    cm = read_csv("clinic_master")

    visit_date = pd.to_datetime(vt["受診日"])
    print("=== visit_triangle ===")
    print(f"行数: {len(vt):,}")
    print(f"受診日 min: {visit_date.min().date()}")
    print(f"受診日 max: {visit_date.max().date()}")
    print("立地パターン:")
    for val, n in _counts(vt["立地パターン"]).items():
        print(f"  {val!r}: {n:,}")

    smap = build_specialty_map(cm)
    merged = vt.merge(smap[["クリニックID", "主科"]], on="クリニックID", how="left")
    unmatched = merged["主科"].isna() | merged["主科"].eq("")
    merged["主科"] = merged["主科"].fillna("不明").replace("", "不明")
    print("\n=== 主科（クリニックID結合） ===")
    print(f"結合できなかった件数: {int(unmatched.sum()):,} / {len(merged):,}")
    print("主科:")
    for val, n in _counts(merged["主科"]).items():
        print(f"  {val}: {n:,}")

    dist = pd.to_numeric(pm["患者→薬局_道路km"], errors="coerce")
    print("\n=== 患者→薬局_道路km（patient_master） ===")
    print(f"患者数: {len(pm):,}")
    print(f"欠損数: {int(dist.isna().sum()):,}")
    band = pd.cut(dist, bins=DIST_BINS, labels=DIST_LABELS)
    for lab in DIST_LABELS:
        print(f"  {lab}: {int((band == lab).sum()):,}")

    visits = merged.copy()
    visits["受診日"] = pd.to_datetime(visits["受診日"], errors="coerce")
    visits = visits.dropna(subset=["患者ID", "受診日"]).copy()
    visits = visits.sort_values(["患者ID", "受診日", "受診ID"], kind="mergesort")
    visits["受診順"] = visits.groupby("患者ID").cumcount() + 1
    visits["ym"] = visits["受診日"].dt.to_period("M").astype(str)
    visits["axis"] = _axis_label(visits["立地パターン"])
    visits["dept"] = visits["主科"]
    visits = visits.merge(
        pm[["患者ID", "患者→薬局_道路km"]],
        on="患者ID",
        how="left",
        suffixes=("", "_pm"),
    )
    road = pd.to_numeric(visits["患者→薬局_道路km"], errors="coerce")
    visits["dist"] = pd.cut(road, bins=DIST_BINS, labels=DIST_LABELS).astype(object)
    visits.loc[road.isna(), "dist"] = "unknown"
    visits["visit_type"] = visits["受診順"].eq(1).map({True: "初回", False: "再来"})

    cells = (
        visits.groupby(["ym", "axis", "dept", "dist", "visit_type"], dropna=False)
        .size()
        .rename("n")
        .reset_index()
    )
    n_cells = len(cells)
    n_small = int((cells["n"] < 5).sum())
    print("\n=== セル（月 × 区分 × 主科 × 距離帯 × 初回/再来） ===")
    print(f"セル数: {n_cells:,}")
    print(f"5件未満セル: {n_small:,} ({n_small / n_cells:.1%})")
    print(f"件数の中央値: {float(cells['n'].median()):.1f}")
    print(f"件数の最大: {int(cells['n'].max()):,}")


if __name__ == "__main__":
    main()
