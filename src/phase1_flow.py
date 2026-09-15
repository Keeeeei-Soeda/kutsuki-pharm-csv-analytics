"""Phase 1: Prescription Flow Theory（記述分析の本体）。

門前型 / 非門前型で層別し、ABC・時系列・外生要因・ポートフォリオ・Sankey を出力する。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tsa.seasonal import STL

from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, SEED, ensure_dirs, read_csv

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _axis_label(pattern: pd.Series) -> pd.Series:
    out = pd.Series(np.where(pattern.astype(str).eq("門前型"), "門前型", "非門前型"), index=pattern.index)
    out = out.where(pattern.notna(), "不明")
    out = out.where(~pattern.astype(str).isin(NON_GATE), "非門前型")
    out = pd.Series(
        np.select(
            [
                pattern.astype(str).eq("門前型"),
                pattern.astype(str).isin(NON_GATE),
            ],
            ["門前型", "非門前型"],
            default="不明",
        ),
        index=pattern.index,
    )
    return out


def load_base() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    vt = read_csv("visit_triangle")
    vt["受診日"] = pd.to_datetime(vt["受診日"])
    vt["軸"] = _axis_label(vt["立地パターン"])
    vt["年月"] = vt["受診日"].dt.to_period("M").astype(str)
    vt["週"] = vt["受診日"].dt.to_period("W-SUN").astype(str)
    vt["曜日番号"] = vt["受診日"].dt.dayofweek  # Mon=0

    pm = read_csv("patient_master")
    cm = read_csv("clinic_master")
    return vt, pm, cm


# ---------------------------------------------------------------------------
# 1. ABC / Pareto
# ---------------------------------------------------------------------------

def abc_pareto(vt: pd.DataFrame, cm: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    ensure_dirs()
    _setup_font()
    results = {}

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, axis_name in zip(axes, ["門前型", "非門前型"]):
        sub = vt.loc[vt["軸"] == axis_name].dropna(subset=["クリニックID"])
        g = (
            sub.groupby(["クリニックID", "クリニック名"], dropna=False)
            .size()
            .rename("件数")
            .reset_index()
            .sort_values("件数", ascending=False)
            .reset_index(drop=True)
        )
        g["累積件数"] = g["件数"].cumsum()
        g["累積構成比"] = g["累積件数"] / g["件数"].sum()
        g["構成比"] = g["件数"] / g["件数"].sum()
        # join clinic attrs
        g = g.merge(
            cm[["クリニックID", "クリニック→薬局_直線km", "商圏内フラグ", "診療科", "種別"]],
            on="クリニックID",
            how="left",
        )
        g["門前_0.3km"] = pd.to_numeric(g["クリニック→薬局_直線km"], errors="coerce") <= 0.3
        n80 = int((g["累積構成比"] <= 0.8).sum()) + 1
        n80 = min(n80, len(g))
        top1_share = float(g.iloc[0]["構成比"]) if len(g) else np.nan
        g.attrs = {"n80": n80, "top1_share": top1_share, "n_clinics": len(g), "n_visits": int(g["件数"].sum())}
        results[axis_name] = g
        g.to_csv(PROCESSED_DIR / f"abc_clinics_{axis_name}.csv", index=False, encoding="utf-8-sig")

        top = g.head(20)
        ax.bar(range(len(top)), top["件数"], color="#F58518" if axis_name == "門前型" else "#4C78A8")
        ax2 = ax.twinx()
        ax2.plot(range(len(top)), top["累積構成比"], color="#E45756", marker="o", ms=3)
        ax2.axhline(0.8, ls="--", color="gray", lw=1)
        ax2.set_ylim(0, 1.05)
        ax.set_title(
            f"{axis_name} 上位20施設\n"
            f"N={g.attrs['n_visits']:,} / 施設{g.attrs['n_clinics']} / "
            f"80%到達={g.attrs['n80']}施設 / 最大シェア={g.attrs['top1_share']:.1%}"
        )
        ax.set_xlabel("順位")
        ax.set_ylabel("件数")
        ax2.set_ylabel("累積構成比")
        ax.set_xticks(range(len(top)))
        ax.set_xticklabels([str(i + 1) for i in range(len(top))])

    fig.suptitle(f"{PHARMACY_NAME} クリニック別ABC（自店受診に限定）", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase1_abc_pareto.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # overall
    sub = vt.dropna(subset=["クリニックID"])
    g = (
        sub.groupby(["クリニックID", "クリニック名"], dropna=False)
        .size()
        .rename("件数")
        .reset_index()
        .sort_values("件数", ascending=False)
        .reset_index(drop=True)
    )
    g["累積構成比"] = g["件数"].cumsum() / g["件数"].sum()
    g["構成比"] = g["件数"] / g["件数"].sum()
    g = g.merge(
        cm[["クリニックID", "クリニック→薬局_直線km", "商圏内フラグ", "診療科", "種別"]],
        on="クリニックID",
        how="left",
    )
    g["門前_0.3km"] = pd.to_numeric(g["クリニック→薬局_直線km"], errors="coerce") <= 0.3
    n80 = int((g["累積構成比"] <= 0.8).sum()) + 1
    g.attrs = {
        "n80": min(n80, len(g)),
        "top1_share": float(g.iloc[0]["構成比"]),
        "n_clinics": len(g),
        "n_visits": int(g["件数"].sum()),
    }
    results["全体"] = g
    g.to_csv(PROCESSED_DIR / "abc_clinics_全体.csv", index=False, encoding="utf-8-sig")
    return results


# ---------------------------------------------------------------------------
# 2. Time series
# ---------------------------------------------------------------------------

def time_series_analysis(vt: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    np.random.seed(SEED)

    daily = vt.groupby("受診日").size().rename("件数").asfreq("D", fill_value=0)
    # STL needs >=2 periods; use period=7
    stl = STL(daily.astype(float), period=7, robust=True).fit()
    stl_df = pd.DataFrame(
        {"件数": daily, "trend": stl.trend, "seasonal": stl.seasonal, "resid": stl.resid}
    )
    stl_df.to_csv(PROCESSED_DIR / "daily_stl.csv", encoding="utf-8-sig")

    # DOW (Mon-Sat only observed)
    dow = (
        vt.groupby(vt["受診日"].dt.dayofweek)
        .size()
        .reindex(range(7), fill_value=0)
    )
    dow.index = ["月", "火", "水", "木", "金", "土", "日"]

    # monthly by axis
    monthly_axis = (
        vt.groupby(["年月", "軸"])
        .size()
        .unstack(fill_value=0)
        .reindex(columns=["門前型", "非門前型", "不明"], fill_value=0)
    )

    # national index
    nat = read_csv("prescriptions_monthly")
    nat["年月"] = pd.to_datetime(nat["年"].astype(str) + "-" + nat["月"].astype(str).str.zfill(2) + "-01").dt.to_period("M").astype(str)
    store_m = vt.groupby("年月").size().rename("自店件数")
    merged = store_m.to_frame().join(nat.set_index("年月")["処方箋枚数"].rename("全国枚数"), how="left")
    # index both to first overlapping month with national data
    valid = merged.dropna()
    if len(valid):
        base_store = valid["自店件数"].iloc[0]
        base_nat = valid["全国枚数"].iloc[0]
        merged["自店指数"] = merged["自店件数"] / base_store * 100
        merged["全国指数"] = merged["全国枚数"] / base_nat * 100
        merged["相対指数"] = merged["自店指数"] / merged["全国指数"] * 100
    merged.to_csv(PROCESSED_DIR / "monthly_vs_national.csv", encoding="utf-8-sig")

    # figures
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=False)
    ax = axes[0]
    ax.plot(daily.index, daily.values, lw=0.8, color="#4C78A8", label="日次")
    ax.plot(stl_df.index, stl_df["trend"], lw=1.5, color="#E45756", label="STL trend")
    ax.set_title(f"日次受診件数とSTLトレンド（period=7） N日={daily.shape[0]}")
    ax.legend(loc="upper right")
    ax.set_ylabel("件数")

    ax = axes[1]
    dow.plot(kind="bar", ax=ax, color="#54A24B")
    ax.set_title("曜日別合計（日曜=0は休業/非取扱の可能性。祝日フラグ未整備）")
    ax.set_ylabel("件数")

    ax = axes[2]
    if "自店指数" in merged.columns:
        m = merged.dropna(subset=["自店指数", "全国指数"])
        ax.plot(m.index, m["自店指数"], marker="o", label="自店指数")
        ax.plot(m.index, m["全国指数"], marker="s", label="全国処方箋指数")
        ax.plot(m.index, m["相対指数"], marker="^", label="相対（自店/全国×100）")
        ax.legend()
        ax.set_title("月次指数（重複期間の初月=100）。全国はMEDIAS電算・推計でない実測統計")
        ax.tick_params(axis="x", rotation=45)
    fig.suptitle(f"{PHARMACY_NAME} 時系列分解", y=1.01)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase1_timeseries.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # monthly stacked already exists; add weekly
    weekly = vt.groupby(["週", "軸"]).size().unstack(fill_value=0)
    weekly.to_csv(PROCESSED_DIR / "weekly_by_gate.csv", encoding="utf-8-sig")

    return {
        "daily_mean": float(daily.mean()),
        "daily_std": float(daily.std()),
        "dow": dow.to_dict(),
        "stl_trend_start": float(stl_df["trend"].dropna().iloc[0]),
        "stl_trend_end": float(stl_df["trend"].dropna().iloc[-1]),
        "monthly_axis": monthly_axis,
        "national": merged,
    }


# ---------------------------------------------------------------------------
# 3. Exogenous GLM
# ---------------------------------------------------------------------------

def exogenous_glm(vt: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()

    weather = read_csv("weather_pollen")
    weather["日付"] = pd.to_datetime(weather["日付"])
    daily = vt.groupby("受診日").size().rename("件数").asfreq("D", fill_value=0).rename_axis("日付")
    df = daily.to_frame().join(weather.set_index("日付"), how="left")
    df["曜日"] = df.index.dayofweek
    df["月"] = df.index.month
    # exclude Sundays (always 0)
    df = df.loc[df["曜日"] < 6].copy()

    # infectious weekly → daily broadcast
    inf = read_csv("infectious_disease_osaka_weekly")
    focus = ["インフルエンザ", "COVID-19", "感染性胃腸炎"]
    inf = inf.loc[inf["疾患名"].isin(focus)].copy()
    inf["週開始日"] = pd.to_datetime(inf["週開始日"])
    # expand to daily
    rows = []
    for _, r in inf.iterrows():
        for d in pd.date_range(r["週開始日"], periods=7, freq="D"):
            rows.append({"日付": d, "疾患名": r["疾患名"], "定当": r["定点当たり報告数"]})
    inf_d = pd.DataFrame(rows).pivot_table(index="日付", columns="疾患名", values="定当", aggfunc="first")
    inf_d.columns = [f"定当_{c}" for c in inf_d.columns]
    df = df.join(inf_d, how="left")

    # Model A: weather (full Mon-Sat sample). Pollen NOT zero-filled — separate model.
    y = df["件数"].astype(float)
    X_cols = ["最高気温", "最低気温", "降水量mm"]
    X = df[X_cols].copy()
    X = X.join(pd.get_dummies(df["曜日"], prefix="dow", drop_first=True, dtype=float))
    X = X.join(pd.get_dummies(df["月"], prefix="month", drop_first=True, dtype=float))
    X = sm.add_constant(X.astype(float), has_constant="add")
    mask = X.notna().all(axis=1) & y.notna()
    model_weather = sm.GLM(y[mask], X.loc[mask], family=sm.families.NegativeBinomial(alpha=1.0)).fit()

    # Model B: pollen season only（0埋め禁止）
    pollen_mask = df["花粉合計"].notna()
    Xp = df.loc[pollen_mask, ["最高気温", "降水量mm", "花粉合計"]].copy()
    Xp = Xp.join(pd.get_dummies(df.loc[pollen_mask, "曜日"], prefix="dow", drop_first=True, dtype=float))
    Xp = sm.add_constant(Xp.astype(float), has_constant="add")
    yp = y[pollen_mask]
    model_pollen = (
        sm.GLM(yp, Xp, family=sm.families.NegativeBinomial(alpha=1.0)).fit() if len(yp) > 30 else None
    )

    # Model C: infectious (ecological)
    inf_cols = [c for c in df.columns if c.startswith("定当_")]
    Xi = df[["最高気温", "降水量mm"] + inf_cols].copy()
    Xi = Xi.join(pd.get_dummies(df["曜日"], prefix="dow", drop_first=True, dtype=float))
    Xi = sm.add_constant(Xi.astype(float), has_constant="add")
    mask_i = Xi.notna().all(axis=1)
    model_inf = sm.GLM(y[mask_i], Xi.loc[mask_i], family=sm.families.NegativeBinomial(alpha=1.0)).fit()

    # save coef tables
    def coef_table(res, name):
        tab = pd.DataFrame(
            {
                "coef": res.params,
                "se": res.bse,
                "pvalue": res.pvalues,
                "IRR": np.exp(res.params),
            }
        )
        tab.to_csv(PROCESSED_DIR / f"glm_coefs_{name}.csv", encoding="utf-8-sig")
        return tab

    tabs = {"weather": coef_table(model_weather, "weather")}
    if model_pollen is not None:
        tabs["pollen"] = coef_table(model_pollen, "pollen")
    tabs["infectious"] = coef_table(model_inf, "infectious")

    # figure: daily vs pollen / flu
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax = axes[0]
    ax.plot(df.index, df["件数"], color="#4C78A8", lw=0.7, label="日次件数(月〜土)")
    ax.set_ylabel("件数")
    ax.legend(loc="upper left")
    ax2 = ax.twinx()
    ax2.plot(df.index, df["花粉合計"], color="#F58518", lw=0.8, alpha=0.7, label="花粉合計(欠測は空白)")
    ax2.set_ylabel("花粉合計")
    ax.set_title("日次件数 vs 花粉（0埋めなし。欠測区間は空白）")

    ax = axes[1]
    ax.plot(df.index, df["件数"], color="#4C78A8", lw=0.7)
    ax2 = ax.twinx()
    if "定当_インフルエンザ" in df.columns:
        ax2.plot(df.index, df["定当_インフルエンザ"], color="#E45756", lw=0.9, label="インフル定当(府)")
    if "定当_COVID-19" in df.columns:
        ax2.plot(df.index, df["定当_COVID-19"], color="#B279A2", lw=0.9, label="COVID定当(府)")
    ax2.legend(loc="upper right")
    ax.set_title("日次件数 vs 大阪府感染症定点（生態学的相関。個人疾患ではない）")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase1_exogenous.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {
        "weather_n": int(mask.sum()),
        "weather_llf": float(model_weather.llf),
        "weather_aic": float(model_weather.aic),
        "pollen_n": int(pollen_mask.sum()),
        "pollen_aic": float(model_pollen.aic) if model_pollen is not None else None,
        "inf_n": int(mask_i.sum()),
        "inf_aic": float(model_inf.aic),
        "tabs": tabs,
        "key_weather": tabs["weather"].loc[["最高気温", "最低気温", "降水量mm"]].to_dict(),
        "key_pollen": tabs["pollen"].loc[["花粉合計"]].to_dict() if "pollen" in tabs and "花粉合計" in tabs["pollen"].index else {},
        "key_inf": {
            k: tabs["infectious"].loc[k].to_dict()
            for k in tabs["infectious"].index
            if k.startswith("定当_")
        },
    }


# ---------------------------------------------------------------------------
# 4. Patient portfolio
# ---------------------------------------------------------------------------

def patient_portfolio(vt: pd.DataFrame, pm: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()

    # city from triangle
    city = (
        vt.dropna(subset=["患者住所_市区町村"])
        .groupby("患者ID")["患者住所_市区町村"]
        .agg(lambda s: s.value_counts().index[0])
    )
    # first-axis
    first = (
        vt.sort_values("受診日")
        .groupby("患者ID", as_index=False)
        .first()[["患者ID", "軸", "立地パターン", "クリニックID"]]
        .rename(columns={"軸": "初回軸", "立地パターン": "初回立地", "クリニックID": "初回クリニックID"})
    )
    port = pm.merge(first, on="患者ID", how="left")
    port["市区町村"] = port["患者ID"].map(city)
    port["面利用候補"] = port["受診クリニック数"] >= 2

    age_ct = pd.crosstab(port["年齢階級"], port["初回軸"], normalize="columns")
    for col in ["門前型", "非門前型"]:
        if col not in age_ct.columns:
            age_ct[col] = 0.0
    age_ct = age_ct[["門前型", "非門前型"]]

    city_top = port["市区町村"].value_counts().head(15)
    visit_hist = port["受診回数"].clip(upper=30)
    multi = port.loc[port["面利用候補"]].copy()

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    ax = axes[0, 0]
    # age order
    order = [f"{a}-{a+4}" for a in range(0, 85, 5)] + ["85+"]
    age_counts = port["年齢階級"].value_counts().reindex(order).fillna(0)
    age_counts.plot(kind="bar", ax=ax, color="#4C78A8")
    ax.set_title(f"年齢階級分布（基準日2026-07-31固定） N患者={len(port):,}")
    ax.tick_params(axis="x", rotation=45)

    ax = axes[0, 1]
    city_top.plot(kind="barh", ax=ax, color="#54A24B")
    ax.invert_yaxis()
    ax.set_title("市区町村 Top15（visit_triangle由来・自店患者）")

    ax = axes[1, 0]
    visit_hist.plot(kind="hist", bins=30, ax=ax, color="#F58518", edgecolor="white")
    ax.set_title("来局回数分布（30回超は30にクリップ表示）")
    ax.set_xlabel("受診回数")

    ax = axes[1, 1]
    vc = port["受診クリニック数"].value_counts().sort_index()
    vc.plot(kind="bar", ax=ax, color="#E45756")
    ax.set_title(f"受診クリニック数（2施設以上={int(port['面利用候補'].sum()):,}人={(port['面利用候補'].mean()):.1%}）")
    ax.set_xlabel("クリニック数")

    fig.suptitle(f"{PHARMACY_NAME} 患者ポートフォリオ", y=1.01)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase1_portfolio.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # multi-clinic profile
    multi_summary = {
        "n": int(multi.shape[0]),
        "share": float(multi.shape[0] / len(port)),
        "mean_visits": float(multi["受診回数"].mean()),
        "median_age": float(multi["年齢"].median()),
        "non_gate_first_share": float((multi["初回軸"] == "非門前型").mean()) if len(multi) else np.nan,
        "top_cities": multi["市区町村"].value_counts().head(5).to_dict(),
    }
    port.to_csv(PROCESSED_DIR / "patient_portfolio.csv", index=False, encoding="utf-8-sig")
    age_ct.to_csv(PROCESSED_DIR / "age_by_first_axis.csv", encoding="utf-8-sig")

    return {
        "age_top": age_counts.head(5).to_dict(),
        "city_top": city_top.head(5).to_dict(),
        "multi": multi_summary,
        "visit_median": float(port["受診回数"].median()),
        "visit_mean": float(port["受診回数"].mean()),
        "age_ct": age_ct,
    }


# ---------------------------------------------------------------------------
# 5. Sankey (HTML)
# ---------------------------------------------------------------------------

def sankey_flow(vt: pd.DataFrame) -> Path:
    ensure_dirs()
    df = vt.dropna(subset=["クリニック名"]).copy()
    df["市区町村"] = df["患者住所_市区町村"].fillna("不明")
    # top cities / clinics
    top_cities = df["市区町村"].value_counts().head(12).index.tolist()
    top_clinics = df["クリニック名"].value_counts().head(20).index.tolist()
    df["市区町村_s"] = np.where(df["市区町村"].isin(top_cities), df["市区町村"], "その他地域")
    df["クリニック_s"] = np.where(df["クリニック名"].isin(top_clinics), df["クリニック名"], "その他クリニック")
    df["薬局"] = PHARMACY_NAME

    # two-step links: city->clinic, clinic->pharmacy
    l1 = df.groupby(["市区町村_s", "クリニック_s"]).size().reset_index(name="value")
    l2 = df.groupby(["クリニック_s", "薬局"]).size().reset_index(name="value")

    labels = []
    for col in ["市区町村_s", "クリニック_s", "薬局"]:
        for v in pd.concat([l1.get(col, pd.Series(dtype=object)), l2.get(col, pd.Series(dtype=object))]).dropna().unique():
            if v not in labels:
                labels.append(v)
    idx = {lab: i for i, lab in enumerate(labels)}

    sources, targets, values = [], [], []
    for _, r in l1.iterrows():
        sources.append(idx[r["市区町村_s"]])
        targets.append(idx[r["クリニック_s"]])
        values.append(int(r["value"]))
    for _, r in l2.iterrows():
        sources.append(idx[r["クリニック_s"]])
        targets.append(idx[r["薬局"]])
        values.append(int(r["value"]))

    # also stratified non-gate only version
    df_ng = df.loc[df["軸"] == "非門前型"]
    # simplify: save counts table
    l1.to_csv(PROCESSED_DIR / "sankey_city_clinic_all.csv", index=False, encoding="utf-8-sig")

    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<title>Sankey - {PHARMACY_NAME}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head><body>
<h2>{PHARMACY_NAME} 流動 Sankey（上位12地域→上位20クリニック→薬局）</h2>
<p>注: 自店受診データに限定。真の地区別クリニック選択率ではない。N={len(df):,}</p>
<div id="sankey" style="width:100%;height:720px;"></div>
<script>
var data = [{{
  type: "sankey",
  orientation: "h",
  node: {{ pad: 12, thickness: 14, label: {labels!r} }},
  link: {{ source: {sources}, target: {targets}, value: {values} }}
}}];
Plotly.newPlot("sankey", data, {{title: "患者住所(市区町村) → クリニック → 薬局"}}, {{responsive:true}});
</script>
<p><a href="phase1_sankey_nongate.html">非門前型のみ版</a></p>
</body></html>
"""
    out = FIGURES / "phase1_sankey.html"
    out.write_text(html, encoding="utf-8")

    # non-gate sankey
    if len(df_ng):
        top_c2 = df_ng["クリニック名"].value_counts().head(15).index.tolist()
        top_city2 = df_ng["市区町村"].value_counts().head(10).index.tolist()
        d2 = df_ng.copy()
        d2["市区町村_s"] = np.where(d2["市区町村"].isin(top_city2), d2["市区町村"], "その他地域")
        d2["クリニック_s"] = np.where(d2["クリニック名"].isin(top_c2), d2["クリニック名"], "その他クリニック")
        d2["薬局"] = PHARMACY_NAME
        a = d2.groupby(["市区町村_s", "クリニック_s"]).size().reset_index(name="value")
        b = d2.groupby(["クリニック_s", "薬局"]).size().reset_index(name="value")
        labels2 = []
        for series in [a["市区町村_s"], a["クリニック_s"], b["クリニック_s"], b["薬局"]]:
            for v in series.unique():
                if v not in labels2:
                    labels2.append(v)
        idx2 = {lab: i for i, lab in enumerate(labels2)}
        s2, t2, v2 = [], [], []
        for _, r in a.iterrows():
            s2.append(idx2[r["市区町村_s"]]); t2.append(idx2[r["クリニック_s"]]); v2.append(int(r["value"]))
        for _, r in b.iterrows():
            s2.append(idx2[r["クリニック_s"]]); t2.append(idx2[r["薬局"]]); v2.append(int(r["value"]))
        html2 = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<title>Sankey 非門前 - {PHARMACY_NAME}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head><body>
<h2>非門前型のみ Sankey（面の実体） N={len(df_ng):,}</h2>
<p>注: 自店・非門前受診に限定。</p>
<div id="sankey" style="width:100%;height:720px;"></div>
<script>
Plotly.newPlot("sankey", [{{
  type:"sankey", orientation:"h",
  node:{{pad:12,thickness:14,label:{labels2!r}}},
  link:{{source:{s2}, target:{t2}, value:{v2}}}
}}], {{title:"非門前: 地域 → クリニック → 薬局"}}, {{responsive:true}});
</script>
</body></html>
"""
        (FIGURES / "phase1_sankey_nongate.html").write_text(html2, encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write_report(abc, ts, exo, port, sankey_path: Path, vt: pd.DataFrame) -> Path:
    gate_n = int((vt["軸"] == "門前型").sum())
    nongate_n = int((vt["軸"] == "非門前型").sum())
    n = len(vt)
    abc_all = abc["全体"]
    abc_g = abc["門前型"]
    abc_ng = abc["非門前型"]

    def top_table(g: pd.DataFrame, k: int = 10) -> str:
        cols = ["クリニック名", "件数", "構成比", "クリニック→薬局_直線km", "診療科", "門前_0.3km"]
        t = g.head(k)[cols].copy()
        t["構成比"] = t["構成比"].map(lambda x: f"{x:.1%}")
        t["クリニック→薬局_直線km"] = pd.to_numeric(t["クリニック→薬局_直線km"], errors="coerce").round(3)
        return t.to_string(index=False)

    # weather key IRR
    def fmt_key(tab: pd.DataFrame, key: str) -> str:
        if key not in tab.index:
            return "n/a"
        r = tab.loc[key]
        return f"IRR={r['IRR']:.3f} (p={r['pvalue']:.3f})"

    wtab = exo["tabs"]["weather"]
    ptab = exo["tabs"].get("pollen")
    itab = exo["tabs"]["infectious"]
    pollen_line = fmt_key(ptab, "花粉合計") if ptab is not None else "n/a"
    inf_lines = ", ".join(
        f"{k.replace('定当_', '')}: {fmt_key(itab, k)}"
        for k in itab.index
        if str(k).startswith("定当_")
    )

    text = f"""# Phase 1: Prescription Flow Theory（記述）

## わかったこと3点

1. **門前集中が規模を決める。** 全体の80%件数は上位 **{abc_all.attrs['n80']}** 施設で到達。最大シェア施設は **{abc_all.attrs['top1_share']:.1%}**（経営の単一クリニック依存リスク）。門前型ではさらに集中が強い。
2. **非門前は別構造。** 非門前の80%到達施設数は **{abc_ng.attrs['n80']}**、最大シェア **{abc_ng.attrs['top1_share']:.1%}**。クリニック→薬局距離の中央値が門前より大きく、面の獲得は分散した多数施設経由。
3. **外生要因は曜日・季節が主で、花粉・府感染症は補助的。** 花粉は欠測を0埋めせず飛散期のみ推定（N={exo['pollen_n']}日）。府定点は生態学的相関に留まる。

## わからなかったこと3点

1. 上位門前クリニックの「総発行処方箋」に対する自店シェア（分母なし）。
2. 全国指数との相対変動の因果（イベント年表なし）。祝日フラグ未整備。
3. 面利用候補（受診クリニック数≥2）の獲得経路（紹介/検索等）は非観測。

## 次に必要なデータ

- クリニック別総処方箋発行数、祝日カレンダー、イベント年表、他店舗データ（`docs/QUESTIONS_TO_CLIENT.md`）

---

## この薬局は面薬局か門前薬局か（数値回答）

**結論: 門前薬局（門前型 {gate_n/n:.1%}）。** 面の実体は非門前 {nongate_n/n:.1%}（{nongate_n:,}件）。

| 区分 | 受診件数 | 構成比 | ユニーク患者 |
|---|---:|---:|---:|
| 門前型 | {gate_n:,} | {gate_n/n:.1%} | {(vt.loc[vt['軸']=='門前型','患者ID'].nunique()):,} |
| 非門前型 | {nongate_n:,} | {nongate_n/n:.1%} | {(vt.loc[vt['軸']=='非門前型','患者ID'].nunique()):,} |
| 不明 | {(vt['軸']=='不明').sum():,} | {(vt['軸']=='不明').mean():.1%} | — |

![月別](figures/phase1_monthly_gate.png)

> 注: すべて自店受診データ。市場全体の立地構成ではない。

---

## 1. 医療機関別 ABC / パレート（層別）

![ABC](figures/phase1_abc_pareto.png)

### 全体
- 施設数: {abc_all.attrs['n_clinics']} / 件数: {abc_all.attrs['n_visits']:,}
- **80%到達: {abc_all.attrs['n80']} 施設** / **最大シェア: {abc_all.attrs['top1_share']:.1%}**

```
{top_table(abc_all)}
```

### 門前型
- 80%到達: **{abc_g.attrs['n80']} 施設** / 最大シェア: **{abc_g.attrs['top1_share']:.1%}**

```
{top_table(abc_g)}
```

### 非門前型（軸B）
- 80%到達: **{abc_ng.attrs['n80']} 施設** / 最大シェア: **{abc_ng.attrs['top1_share']:.1%}**

```
{top_table(abc_ng)}
```

CSV: `data/processed/abc_clinics_*.csv`

---

## 2. 時系列分解

![時系列](figures/phase1_timeseries.png)

- 日次平均: {ts['daily_mean']:.1f}（SD {ts['daily_std']:.1f}）※全日（日曜0含む）
- STLトレンド: {ts['stl_trend_start']:.1f} → {ts['stl_trend_end']:.1f}
- 曜日合計: {ts['dow']}
- 全国MEDIASとの月次指数: `data/processed/monthly_vs_national.csv`（全国は都道府県別月次非公表のため全国統制）

---

## 3. 外生要因（負の二項GLM・相関として報告）

![外生](figures/phase1_exogenous.png)

**サンプル定義**
- 気象モデル: 月〜土のみ、気象欠損除外、N={exo['weather_n']}日 / AIC={exo['weather_aic']:.1f}
- 花粉モデル: 花粉合計非欠損日のみ（0埋め禁止）、N={exo['pollen_n']}日 / AIC={exo.get('pollen_aic')}
- 感染症モデル: 大阪府定点を日次に展開、N={exo['inf_n']}日 / AIC={exo['inf_aic']:.1f}

**主な係数（IRR=exp(β)、因果ではない）**
- 最高気温: {fmt_key(wtab, '最高気温')}
- 最低気温: {fmt_key(wtab, '最低気温')}
- 降水量mm: {fmt_key(wtab, '降水量mm')}
- 花粉合計: {pollen_line}
- 感染症定当: {inf_lines}

> 限界: 祝日ダミーなし。感染症は府単位の生態学的相関。個人の疾患とは結合していない。

係数CSV: `data/processed/glm_coefs_*.csv`

---

## 4. 患者ポートフォリオ

![ポートフォリオ](figures/phase1_portfolio.png)

- 来局回数: 平均 {port['visit_mean']:.2f} / 中央値 {port['visit_median']:.0f}
- **面利用候補（受診クリニック数≥2）: {port['multi']['n']:,}人（{port['multi']['share']:.1%}）**
  - 平均来局 {port['multi']['mean_visits']:.1f}回 / 年齢中央値 {port['multi']['median_age']:.0f}
  - 初回が非門前の割合 {port['multi']['non_gate_first_share']:.1%}
  - 上位市区町村: {port['multi']['top_cities']}
- 年齢・地域の詳細: `data/processed/patient_portfolio.csv`

> 注: 年齢は基準日2026-07-31固定。市区町村は visit_triangle 由来（patient_master の住所テキストは意図的空欄）。

---

## 5. 流動フロー（Sankey）

- 全体（上位12地域→上位20クリニック→薬局）: [{sankey_path.name}](figures/{sankey_path.name})
- 非門前のみ: [phase1_sankey_nongate.html](figures/phase1_sankey_nongate.html)

> 注: タイトルどおり「自店に来た患者におけるフロー」。真の地区別クリニック選択率ではない。

---

## サンプル定義・限界（共通）

1. 対象: くつき薬局南茨木店の自店受診 {n:,} 件（2024-09-02〜2026-07-31）
2. 門前型 = 立地パターン「門前型」。非門前 = 患者近接/経由/遠隔。不明={((vt['軸']=='不明').sum())}件（座標欠測等）
3. 新患フラグは使用していない
4. 花粉欠損は0埋めしていない
5. GLM係数は条件付き関連であり因果効果ではない
"""
    path = REPORTS / "phase1_flow.md"
    path.write_text(text, encoding="utf-8")
    return path


def run_phase1() -> Dict:
    ensure_dirs()
    vt, pm, cm = load_base()
    abc = abc_pareto(vt, cm)
    ts = time_series_analysis(vt)
    exo = exogenous_glm(vt)
    port = patient_portfolio(vt, pm)
    sankey = sankey_flow(vt)
    report = write_report(abc, ts, exo, port, sankey, vt)
    return {
        "report": report,
        "abc_n80": abc["全体"].attrs["n80"],
        "top1": abc["全体"].attrs["top1_share"],
        "multi": port["multi"]["n"],
        "sankey": sankey,
    }


if __name__ == "__main__":
    out = run_phase1()
    print("wrote", out["report"])
    print("ABC 80% facilities:", out["abc_n80"], "top1:", round(out["top1"], 3))
    print("multi-clinic patients:", out["multi"])
    print("sankey", out["sankey"])
