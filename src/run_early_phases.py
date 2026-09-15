"""Phase1冒頭 + Phase3土台の先行検証スクリプト。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.io import PHARMACY_LAT, PHARMACY_LON, PHARMACY_NAME, PROCESSED_DIR, ROOT, ensure_dirs, read_csv

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = [
        "Hiragino Sans",
        "AppleGothic",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def phase1_gate_stats() -> dict:
    ensure_dirs()
    _setup_font()
    vt = read_csv("visit_triangle")
    n = len(vt)
    pattern = vt["立地パターン"].value_counts(dropna=False)
    gate = vt["門前フラグ"].astype(str).str.upper().value_counts(dropna=False)

    non_gate_patterns = ["患者近接型", "経由型", "遠隔型"]
    non_gate_n = int(vt["立地パターン"].isin(non_gate_patterns).sum())
    gate_n = int((vt["立地パターン"] == "門前型").sum())

    vt["年月"] = pd.to_datetime(vt["受診日"]).dt.to_period("M").astype(str)
    vt["非門前"] = vt["立地パターン"].isin(non_gate_patterns)
    monthly = vt.groupby(["年月", "非門前"]).size().unstack(fill_value=0)
    monthly = monthly.rename(columns={False: "門前型", True: "非門前型"})
    for c in ["門前型", "非門前型"]:
        if c not in monthly.columns:
            monthly[c] = 0
    monthly = monthly[["門前型", "非門前型"]]
    monthly.to_csv(PROCESSED_DIR / "monthly_by_gate.csv", encoding="utf-8-sig")

    # patient-level: ever non-gate / multi-clinic
    pm = read_csv("patient_master")
    multi = int((pm["受診クリニック数"] >= 2).sum())

    # descriptive by axis
    summary_rows = []
    for label, mask in [
        ("門前型", vt["立地パターン"] == "門前型"),
        ("非門前型", vt["立地パターン"].isin(non_gate_patterns)),
        ("全体", pd.Series(True, index=vt.index)),
    ]:
        sub = vt.loc[mask]
        summary_rows.append(
            {
                "区分": label,
                "受診件数": len(sub),
                "構成比": len(sub) / n,
                "ユニーク患者": sub["患者ID"].nunique(),
                "患者→薬局_道路km中央値": pd.to_numeric(sub["患者→薬局_道路km"], errors="coerce").median(),
                "クリニック→薬局_直線km中央値": pd.to_numeric(sub["クリニック→薬局_直線km"], errors="coerce").median(),
                "年齢中央値": pd.to_numeric(sub["年齢"], errors="coerce").median(),
            }
        )
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(PROCESSED_DIR / "gate_stratified_summary.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    monthly.plot(kind="bar", stacked=True, ax=ax, color=["#F58518", "#4C78A8"], width=0.85)
    ax.set_title(
        f"門前型 vs 非門前型の月別受診件数\n{PHARMACY_NAME} / N={n:,} "
        f"（門前型 {gate_n:,}={gate_n/n:.1%} / 非門前 {non_gate_n:,}={non_gate_n/n:.1%}）"
    )
    ax.set_ylabel("受診件数")
    ax.set_xlabel("年月")
    ax.legend(loc="upper right")
    ax.set_xticklabels(monthly.index, rotation=45, ha="right")
    fig.tight_layout()
    fig_path = FIGURES / "phase1_monthly_gate.png"
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)

    return {
        "n": n,
        "pattern": pattern.to_dict(),
        "gate_flag": gate.to_dict(),
        "gate_n": gate_n,
        "non_gate_n": non_gate_n,
        "multi_clinic_patients": multi,
        "summary": summary,
        "fig": fig_path,
    }


def write_phase1_intro(stats: dict) -> Path:
    s = stats["summary"]
    text = f"""# Phase 1: Prescription Flow Theory（記述）

## わかったこと3点

1. **この薬局は『面薬局』ではなく、実態として門前薬局データである。** 立地パターン門前型は {stats['gate_n']:,}/{stats['n']:,} 件（**{stats['gate_n']/stats['n']:.1%}**）。
2. **成長余地の実体は非門前 {stats['non_gate_n']:,} 件（{stats['non_gate_n']/stats['n']:.1%}）。** 以降の5理論検証は主にこの軸Bで行う。
3. 受診クリニック数≥2の患者は {stats['multi_clinic_patients']:,} 人（面利用候補）。

## わからなかったこと3点

1. 門前需要のうち、自店施策で動かせる余地がどの程度か（クリニック総発行数が未知）。
2. 非門前患者の獲得経路（検索/紹介/以前から等）は観測不能。
3. 月1,800枚目標との定義差（明細 vs 処方箋枚数）が未確定。

## 次に必要なデータ

- クリニック別総処方箋発行数、イベント年表、他店舗同一スキーマ（`docs/QUESTIONS_TO_CLIENT.md`）

---

## この薬局は面薬局か門前薬局か（数値回答）

**結論: 門前薬局（門前型 {stats['gate_n']/stats['n']:.1%}）。** 面の実体は非門前 {stats['non_gate_n']/stats['n']:.1%}。

### 層別サマリ

```
{s.to_string(index=False)}
```

### 立地パターン内訳

```
{stats['pattern']}
```

![月別](figures/phase1_monthly_gate.png)

> 注: 自店受診データに限定。市場全体の立地構成ではない。

## 以降のセクション

- ABC/パレート、時系列分解、外生要因、Sankey は Phase 1 続きとして実装予定。
"""
    path = REPORTS / "phase1_flow.md"
    path.write_text(text, encoding="utf-8")
    return path


def visit_rate_and_decay() -> Path:
    ensure_dirs()
    _setup_font()

    frames = []
    for year in (2024, 2025, 2026):
        df = read_csv(f"population_visitors_{year}")
        df = df.rename(columns={"くつき薬局南茨木店にそこから訪れた人": "来局患者数"})
        df["年"] = year
        frames.append(df)
    pv = pd.concat(frames, ignore_index=True)
    pv["人口"] = pd.to_numeric(pv["人口"], errors="coerce")
    pv["来局患者数"] = pd.to_numeric(pv["来局患者数"], errors="coerce").fillna(0)
    pv = pv[pv["人口"] > 0].copy()
    pv["来局率"] = pv["来局患者数"] / pv["人口"]

    # region centroids approx via triangle city + patient road distance
    pm = read_csv("patient_master")
    vt = read_csv("visit_triangle")
    city = (
        vt.dropna(subset=["患者住所_市区町村"])
        .groupby("患者ID", as_index=False)["患者住所_市区町村"]
        .agg(lambda s: s.value_counts().index[0])
        .rename(columns={"患者住所_市区町村": "市区町村"})
    )
    pm2 = pm.merge(city, on="患者ID", how="left")

    def region_key(city_name) -> object:
        if pd.isna(city_name) or not str(city_name).strip():
            return np.nan
        c = str(city_name).strip()
        if c.startswith(("大阪", "京都", "兵庫", "奈良", "滋賀", "和歌山", "東京", "神奈川", "千葉", "埼玉")):
            return c
        return f"大阪府{c}"

    pm2["地域"] = [region_key(c) for c in pm2["市区町村"]]
    region_dist = (
        pm2.dropna(subset=["地域", "患者→薬局_道路km"])
        .groupby("地域", as_index=False)
        .agg(道路距離_km=("患者→薬局_道路km", "median"), 患者数=("患者ID", "nunique"))
    )

    # aggregate visit rate by region (sum across ages, mean year or latest year 2026)
    latest = pv[pv["年"] == 2026].groupby("地域", as_index=False).agg(人口=("人口", "sum"), 来局患者数=("来局患者数", "sum"))
    latest["来局率"] = latest["来局患者数"] / latest["人口"]
    merged = latest.merge(region_dist, on="地域", how="inner")
    merged = merged[merged["道路距離_km"] <= 30].copy()  # 記述の遠方除外
    merged.to_csv(PROCESSED_DIR / "visit_rate_by_region_2026.csv", index=False, encoding="utf-8-sig")

    # mesh version: assign patients to nearest mesh? simpler: mesh population vs count of patients within mesh distance bands using patient coords
    mesh = read_csv("mesh_population")
    # distance decay by band using patient road km
    pm_d = pm.dropna(subset=["患者→薬局_道路km"]).copy()
    pm_d["距離帯"] = pd.cut(
        pm_d["患者→薬局_道路km"],
        bins=[0, 0.5, 1, 1.5, 2, 3, 5, 10, 30],
        right=True,
    )
    # population proxy: mesh sum in same straight-km bands (approx)
    mesh["距離帯"] = pd.cut(
        mesh["くつき薬局南茨木店→メッシュ中心_直線km"],
        bins=[0, 0.5, 1, 1.5, 2, 3, 5, 10, 30],
        right=True,
    )
    pop_band = mesh.groupby("距離帯", observed=False)["総人口"].sum()
    pat_band = pm_d.groupby("距離帯", observed=False)["患者ID"].nunique()
    decay = pd.DataFrame({"人口_メッシュ合算": pop_band, "来局患者": pat_band}).fillna(0)
    decay["来局率_粗"] = np.where(decay["人口_メッシュ合算"] > 0, decay["来局患者"] / decay["人口_メッシュ合算"], np.nan)
    decay.to_csv(PROCESSED_DIR / "distance_decay_bands.csv", encoding="utf-8-sig")

    # plot region scatter + band curve
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    ax = axes[0]
    ax.scatter(merged["道路距離_km"], merged["来局率"] * 1000, s=18, alpha=0.6, c="#4C78A8")
    # log-distance simple fit for visual
    x = merged["道路距離_km"].values
    y = merged["来局率"].values
    mask = (x > 0) & (y > 0)
    if mask.sum() > 5:
        coef = np.polyfit(np.log(x[mask]), np.log(y[mask]), 1)
        xs = np.linspace(max(x[mask].min(), 0.05), x[mask].max(), 100)
        ys = np.exp(coef[1] + coef[0] * np.log(xs))
        ax.plot(xs, ys * 1000, color="#E45756", label=f"log-log傾き={coef[0]:.2f}")
        ax.legend()
    ax.set_xlabel("地域中央値 患者→薬局 道路km（自店患者）")
    ax.set_ylabel("来局率 ×1000（2026・地域合計）")
    ax.set_title("地域別来局率の距離減衰\n注: 自店来局÷住基人口。非来局は外部選択肢")

    ax2 = axes[1]
    decay_plot = decay.dropna(subset=["来局率_粗"]).copy()
    ax2.bar(range(len(decay_plot)), decay_plot["来局率_粗"] * 1000, color="#54A24B")
    ax2.set_xticks(range(len(decay_plot)))
    ax2.set_xticklabels([str(i) for i in decay_plot.index], rotation=45, ha="right")
    ax2.set_ylabel("粗来局率 ×1000")
    ax2.set_xlabel("距離帯(km)")
    ax2.set_title("メッシュ人口合算に対する距離帯別粗来局率\n注: 直線km帯×道路km帯の近似・記述用")

    fig.suptitle(f"{PHARMACY_NAME} 来局率×距離（Phase3土台・先行検証）", y=1.02)
    fig.tight_layout()
    out = FIGURES / "phase3_distance_decay.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)

    # age-region table sample output
    pv.to_parquet(PROCESSED_DIR / "visit_rate_region_age_year.parquet", index=False)
    return out


def main():
    stats = phase1_gate_stats()
    write_phase1_intro(stats)
    fig = visit_rate_and_decay()
    print("phase1 gate_n/non_gate", stats["gate_n"], stats["non_gate_n"])
    print("wrote reports/phase1_flow.md")
    print("decay fig", fig)


if __name__ == "__main__":
    main()
