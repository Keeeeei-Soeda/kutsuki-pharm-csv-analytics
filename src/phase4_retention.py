"""Phase 4: 継続・コホート・生存・LTV・セグメンテーション。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, SEED, ensure_dirs, read_csv
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]
END_DATE = pd.Timestamp("2026-07-31")
RETENTION_DAYS = 90


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def load_base() -> Dict[str, pd.DataFrame]:
    vt = read_csv("visit_triangle")
    vt["受診日"] = pd.to_datetime(vt["受診日"])
    vt["軸"] = np.select(
        [vt["立地パターン"].astype(str).eq("門前型"), vt["立地パターン"].astype(str).isin(NON_GATE)],
        ["門前型", "非門前型"],
        default="不明",
    )
    pm = read_csv("patient_master")
    pm["初回受診日"] = pd.to_datetime(pm["初回受診日"])
    pm["最終受診日"] = pd.to_datetime(pm["最終受診日"])
    vh = read_csv("visit_history")
    vh["受診日"] = pd.to_datetime(vh["受診日"])
    return {"vt": vt, "pm": pm, "vh": vh}


def attach_first_attrs(pm: pd.DataFrame, vt: pd.DataFrame) -> pd.DataFrame:
    first = (
        vt.sort_values("受診日")
        .groupby("患者ID", as_index=False)
        .first()[["患者ID", "軸", "立地パターン", "クリニックID", "クリニック名", "曜日"]]
        .rename(
            columns={
                "軸": "初回軸",
                "立地パターン": "初回立地",
                "クリニックID": "初回クリニックID",
                "クリニック名": "初回クリニック名",
                "曜日": "初回曜日",
            }
        )
    )
    out = pm.merge(first, on="患者ID", how="left")
    out["道路km"] = pd.to_numeric(out["患者→薬局_道路km"], errors="coerce")
    out["距離帯"] = pd.cut(
        out["道路km"],
        bins=[-0.01, 1, 2, 5, 10, 1e6],
        labels=["0-1", "1-2", "2-5", "5-10", "10+"],
    )
    return out


# ---------------------------------------------------------------------------
# 1. Cohort retention
# ---------------------------------------------------------------------------

def cohort_retention(vh: pd.DataFrame, patients: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    p = patients.copy()
    p["初回月"] = p["初回受診日"].dt.to_period("M")
    # months since first visit for each visit
    v = vh.merge(p[["患者ID", "初回受診日", "初回月", "初回軸"]], on="患者ID", how="left")
    v["経過月"] = (
        (v["受診日"].dt.to_period("M") - v["初回月"]).apply(lambda x: x.n if pd.notna(x) else np.nan)
    )
    v = v.dropna(subset=["経過月", "初回月"])
    v["経過月"] = v["経過月"].astype(int)
    v = v.loc[(v["経過月"] >= 0) & (v["経過月"] <= 18)]

    def heat(df, title, path):
        # retention: unique patients active in month m / cohort size
        cohort_size = df.groupby("初回月")["患者ID"].nunique()
        active = df.groupby(["初回月", "経過月"])["患者ID"].nunique().unstack(fill_value=0)
        rate = active.div(cohort_size, axis=0)
        rate.to_csv(PROCESSED_DIR / path.replace(".png", ".csv").replace("phase4_", "phase4_"), encoding="utf-8-sig")
        fig, ax = plt.subplots(figsize=(11, 5.5))
        im = ax.imshow(rate.values.astype(float), aspect="auto", cmap="YlGnBu", vmin=0, vmax=1)
        ax.set_yticks(range(len(rate.index)))
        ax.set_yticklabels([str(i) for i in rate.index], fontsize=8)
        ax.set_xticks(range(len(rate.columns)))
        ax.set_xticklabels(rate.columns, fontsize=8)
        ax.set_xlabel("初回からの経過月")
        ax.set_ylabel("初回月コホート")
        ax.set_title(title)
        fig.colorbar(im, ax=ax, fraction=0.025, label="残存率")
        fig.tight_layout()
        fig.savefig(FIGURES / path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        return rate

    rate_all = heat(
        v,
        f"{PHARMACY_NAME} コホート残存率（月次・ユニーク来局）\n注: 年齢は基準日固定。自店受診のみ",
        "phase4_cohort_all.png",
    )
    rate_gate = heat(
        v.loc[v["初回軸"] == "門前型"],
        "コホート残存率【初回門前型】",
        "phase4_cohort_gate.png",
    )
    rate_ng = heat(
        v.loc[v["初回軸"] == "非門前型"],
        "コホート残存率【初回非門前型】",
        "phase4_cohort_nongate.png",
    )
    # summary at month 3 / 6 / 12
    def avg_at(rate, m):
        if m not in rate.columns:
            return np.nan
        return float(rate[m].mean())

    return {
        "m3": avg_at(rate_all, 3),
        "m6": avg_at(rate_all, 6),
        "m12": avg_at(rate_all, 12),
        "gate_m3": avg_at(rate_gate, 3),
        "nongate_m3": avg_at(rate_ng, 3),
    }


# ---------------------------------------------------------------------------
# 2. First retention logistic (90 days)
# ---------------------------------------------------------------------------

def first_retention_logit(vh: pd.DataFrame, patients: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    # exclude patients whose 90-day window not complete
    cutoff = END_DATE - pd.Timedelta(days=RETENTION_DAYS)
    p = patients.loc[patients["初回受診日"] <= cutoff].copy()
    # second visit within 90 days (exclude first day itself)
    visits = vh.merge(p[["患者ID", "初回受診日"]], on="患者ID", how="inner")
    visits["日差"] = (visits["受診日"] - visits["初回受診日"]).dt.days
    second = (
        visits.loc[visits["日差"] > 0]
        .groupby("患者ID")["日差"]
        .min()
        .rename("初回からの最短再来日数")
    )
    p = p.merge(second, on="患者ID", how="left")
    p["定着90"] = (p["初回からの最短再来日数"] <= RETENTION_DAYS).astype(int)
    p["定着90"] = p["定着90"].fillna(0).astype(int)

    # features
    d = p.dropna(subset=["道路km"]).copy()
    d = d.loc[d["道路km"] <= 30]
    d["log距離"] = np.log(d["道路km"].clip(lower=0.05))
    d["非門前"] = (d["初回軸"] == "非門前型").astype(float)
    d["年齢"] = pd.to_numeric(d["年齢"], errors="coerce")
    # top clinics FE collapsed: is top2 gate clinic
    top = {"C001", "C002"}  # may not match; use name
    top_names = d["初回クリニック名"].value_counts().head(2).index.tolist()
    d["上位門前クリニック"] = d["初回クリニック名"].isin(top_names).astype(float)

    y = d["定着90"].astype(float)
    X = pd.DataFrame(
        {
            "const": 1.0,
            "log距離": d["log距離"],
            "年齢": d["年齢"],
            "非門前": d["非門前"],
            "上位門前クリニック": d["上位門前クリニック"],
        }
    )
    # weekday dummies
    wd = pd.get_dummies(d["初回曜日"].astype(str), prefix="dow", drop_first=True, dtype=float)
    X = pd.concat([X, wd], axis=1)
    mask = X.notna().all(axis=1) & y.notna()
    model = sm.Logit(y[mask], X.loc[mask]).fit(disp=False)
    coef = pd.DataFrame({"coef": model.params, "se": model.bse, "pvalue": model.pvalues, "OR": np.exp(model.params)})
    coef.to_csv(PROCESSED_DIR / "phase4_retention90_logit.csv", encoding="utf-8-sig")

    rate = float(y[mask].mean())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    ax = axes[0]
    by_axis = d.loc[mask].groupby("初回軸")["定着90"].mean()
    by_axis.plot(kind="bar", ax=ax, color=["#c45c26", "#2f6f9f", "#888"])
    ax.set_ylim(0, 1)
    ax.set_ylabel("90日以内再来率")
    ax.set_title(f"初回定着率（全体 {rate:.1%}）\nN={int(mask.sum())} / 初回≤{cutoff.date()}")

    ax = axes[1]
    keys = ["log距離", "年齢", "非門前", "上位門前クリニック"]
    sub = coef.loc[[k for k in keys if k in coef.index]]
    ax.barh(sub.index, sub["OR"], color="#0f6a6a")
    ax.axvline(1, color="#333", lw=1)
    ax.set_xlabel("Odds Ratio")
    ax.set_title("90日定着ロジスティック OR（相関）")
    fig.suptitle(f"{PHARMACY_NAME} 初回定着（新患フラグ不使用・自前定義）", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_retention90.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {
        "n": int(mask.sum()),
        "rate": rate,
        "excluded_recent": int((patients["初回受診日"] > cutoff).sum()),
        "aic": float(model.aic),
        "coef": coef,
        "by_axis": by_axis.to_dict(),
        "prsquared": float(model.prsquared),
    }


# ---------------------------------------------------------------------------
# 3. Survival / intervals
# ---------------------------------------------------------------------------

def visit_interval_survival(vh: pd.DataFrame, patients: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    from lifelines import CoxPHFitter, KaplanMeierFitter

    v = vh.sort_values(["患者ID", "受診日"]).copy()
    v["前回"] = v.groupby("患者ID")["受診日"].shift(1)
    v["間隔日"] = (v["受診日"] - v["前回"]).dt.days
    intervals = v.dropna(subset=["間隔日"]).copy()
    intervals = intervals.loc[intervals["間隔日"] > 0]

    # last gap censoring: from last visit to END_DATE as censored interval opportunity
    last = vh.groupby("患者ID", as_index=False)["受診日"].max().rename(columns={"受診日": "最終"})
    last = last.merge(patients[["患者ID", "道路km", "初回軸", "年齢"]], on="患者ID", how="left")
    last["間隔日"] = (END_DATE - last["最終"]).dt.days.clip(lower=0)
    last["event"] = 0  # censored waiting
    # observed intervals are events=1 (a return happened)
    obs = intervals[["患者ID", "間隔日"]].copy()
    obs["event"] = 1
    obs = obs.merge(patients[["患者ID", "道路km", "初回軸", "年齢"]], on="患者ID", how="left")

    # KM on observed return intervals only (descriptive of gaps)
    km = KaplanMeierFitter()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    ax = axes[0]
    for label, color in [("門前型", "#c45c26"), ("非門前型", "#2f6f9f")]:
        sub = obs.loc[obs["初回軸"] == label, "間隔日"].dropna()
        if len(sub) < 30:
            continue
        km.fit(sub, event_observed=np.ones(len(sub)), label=label)
        km.plot_survival_function(ax=ax, color=color)
    ax.set_title("来局間隔のKM（観測された再来間隔）\n注: 処方日数非保有。打ち切り最終日=2026-07-31")
    ax.set_xlabel("間隔日数")
    ax.set_ylabel("S(t)")

    # histogram peaks
    ax = axes[1]
    clipped = obs["間隔日"].clip(upper=180)
    ax.hist(clipped, bins=60, color="#0f6a6a", alpha=0.85)
    for mark, name in [(28, "28日"), (56, "56日"), (84, "84日")]:
        ax.axvline(mark, color="#c45c26", ls="--", lw=1, label=name if mark == 28 else None)
    ax.set_title("再来間隔ヒストグラム（180日でクリップ）")
    ax.set_xlabel("日")
    ax.legend(["28/56/84日目安"])
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_intervals.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # Cox on time-to-next using observed intervals + patient attrs (recurrent simplified: one row per interval)
    cox_df = obs.dropna(subset=["間隔日", "道路km", "年齢"]).copy()
    cox_df = cox_df.loc[cox_df["道路km"] <= 30]
    cox_df["log距離"] = np.log(cox_df["道路km"].clip(0.05))
    cox_df["非門前"] = (cox_df["初回軸"] == "非門前型").astype(float)
    cox_df["event"] = 1
    cph = CoxPHFitter()
    cph.fit(cox_df[["間隔日", "event", "log距離", "年齢", "非門前"]], duration_col="間隔日", event_col="event")
    summary = cph.summary[["coef", "exp(coef)", "p"]].copy()
    summary.to_csv(PROCESSED_DIR / "phase4_cox_intervals.csv", encoding="utf-8-sig")

    med = float(obs["間隔日"].median())
    p28 = float((obs["間隔日"] <= 28).mean())
    p56 = float((obs["間隔日"] <= 56).mean())
    return {
        "n_intervals": int(len(obs)),
        "median_gap": med,
        "share_le28": p28,
        "share_le56": p56,
        "cox": summary,
        "c_index": float(cph.concordance_index_),
    }


# ---------------------------------------------------------------------------
# 4. Household - not available
# ---------------------------------------------------------------------------

def household_note(pm: pd.DataFrame) -> Dict:
    empty = int((pm["患者住所_詳細"].fillna("").astype(str).str.strip() == "").sum())
    return {
        "available": False,
        "empty_detail": empty,
        "n": len(pm),
        "reason": "患者住所_詳細が全空欄（座標利用の意図的設計）。世帯クラスタ・家族波及は現データでは実行不可。",
    }


# ---------------------------------------------------------------------------
# 5. LTV
# ---------------------------------------------------------------------------

def ltv_empirical(patients: pd.DataFrame, survival_med_gap: float) -> Dict:
    ensure_dirs()
    _setup_font()
    cfg_path = ROOT / "config" / "economics.yaml"
    with open(cfg_path, encoding="utf-8") as f:
        eco = yaml.safe_load(f)
    margin = float(eco.get("gross_margin_per_visit_yen", 2000))

    p = patients.copy()
    # empirical remaining visits proxy: observed visits (lower bound; censored)
    # survival-based expected lifetime visits ≈ 観測期間内頻度 × 期待継続月
    # simple: LTV = 受診回数 * margin (observed) and scenario multipliers
    p["LTV_観測円"] = p["受診回数"] * margin
    # expected additional: if median gap g days, monthly rate ~ 30/g, remaining months until churn
    # use residual rate from cohort m6 as continuation proxy
    by_axis = p.groupby("初回軸").agg(
        人数=("患者ID", "count"),
        平均来局=("受診回数", "mean"),
        中央来局=("受診回数", "median"),
        平均LTV円=("LTV_観測円", "mean"),
    )

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for label, color in [("門前型", "#c45c26"), ("非門前型", "#2f6f9f")]:
        sub = p.loc[p["初回軸"] == label, "受診回数"].clip(upper=40)
        ax.hist(sub, bins=40, alpha=0.55, label=label, color=color)
    ax.set_title(f"来局回数分布とLTV感度（粗利仮置き {margin:,.0f}円/回）\nLTV=来局回数×粗利。打ち切りあり＝下限寄り")
    ax.set_xlabel("受診回数（40でクリップ表示）")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_ltv.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    # sensitivity table
    sens = []
    for m in [1000, 2000, 3000, 5000]:
        sens.append(
            {
                "粗利円": m,
                "平均LTV_全体": float(p["受診回数"].mean() * m),
                "平均LTV_門前": float(p.loc[p["初回軸"] == "門前型", "受診回数"].mean() * m),
                "平均LTV_非門前": float(p.loc[p["初回軸"] == "非門前型", "受診回数"].mean() * m),
            }
        )
    sens_df = pd.DataFrame(sens)
    sens_df.to_csv(PROCESSED_DIR / "phase4_ltv_sensitivity.csv", index=False, encoding="utf-8-sig")
    by_axis.to_csv(PROCESSED_DIR / "phase4_ltv_by_axis.csv", encoding="utf-8-sig")
    return {"margin": margin, "by_axis": by_axis, "sens": sens_df, "mean_visits": float(p["受診回数"].mean())}


# ---------------------------------------------------------------------------
# 6. Multilevel
# ---------------------------------------------------------------------------

def multilevel_visits(patients: pd.DataFrame) -> Dict:
    ensure_dirs()
    d = patients.dropna(subset=["初回クリニックID", "受診回数", "道路km", "年齢"]).copy()
    d = d.loc[d["道路km"] <= 30]
    d["log距離"] = np.log(d["道路km"].clip(0.05))
    d["非門前"] = (d["初回軸"] == "非門前型").astype(float)
    # MixedLM on log(visits)
    d["log来局"] = np.log(d["受診回数"].clip(lower=1))
    # statsmodels MixedLM
    try:
        model = sm.MixedLM(
            d["log来局"],
            exog=sm.add_constant(d[["log距離", "年齢", "非門前"]]),
            groups=d["初回クリニックID"],
        ).fit(reml=False, method="lbfgs")
        re_var = float(model.cov_re.iloc[0, 0])
        fe_var = float(np.var(model.fittedvalues - model.random_effects_mean if False else model.fittedvalues))
        # ICC approx = re / (re + resid)
        resid = float(model.scale)
        icc = re_var / (re_var + resid) if (re_var + resid) > 0 else np.nan
        # clinic random intercepts
        re = pd.Series({k: float(v.iloc[0] if hasattr(v, "iloc") else v) for k, v in model.random_effects.items()})
        re = re.sort_values(ascending=False)
        # map names
        name_map = patients.drop_duplicates("初回クリニックID").set_index("初回クリニックID")["初回クリニック名"]
        top = pd.DataFrame({"クリニックID": re.head(10).index, "RE": re.head(10).values})
        top["クリニック名"] = top["クリニックID"].map(name_map)
        top.to_csv(PROCESSED_DIR / "phase4_clinic_random_effects.csv", index=False, encoding="utf-8-sig")

        _setup_font()
        fig, ax = plt.subplots(figsize=(8, 5))
        plot_df = top.iloc[::-1]
        ax.barh(plot_df["クリニック名"].astype(str).str[:18], plot_df["RE"], color="#2f6f9f")
        ax.axvline(0, color="#333", lw=1)
        ax.set_title(f"初回クリニックのランダム切片（log来局） ICC≈{icc:.3f}\n正＝そのクリニック経由患者の来局が多い")
        fig.tight_layout()
        fig.savefig(FIGURES / "phase4_multilevel.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        return {"ok": True, "icc": icc, "n": len(d), "n_groups": int(d["初回クリニックID"].nunique()), "top": top}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 7. Clustering
# ---------------------------------------------------------------------------

def cluster_patients(patients: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    d = patients.dropna(subset=["道路km", "年齢", "受診回数", "受診クリニック数"]).copy()
    d = d.loc[d["道路km"] <= 30]
    d["非門前"] = (d["初回軸"] == "非門前型").astype(float)
    feats = d[["道路km", "年齢", "受診回数", "受診クリニック数", "非門前"]].astype(float)
    Xs = StandardScaler().fit_transform(feats)

    scores = []
    best_k, best_s = 3, -1
    for k in range(3, 7):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=10)
        lab = km.fit_predict(Xs)
        s = float(silhouette_score(Xs, lab, sample_size=min(3000, len(Xs)), random_state=SEED))
        scores.append({"k": k, "silhouette": s})
        if s > best_s:
            best_k, best_s = k, s
    km = KMeans(n_clusters=best_k, random_state=SEED, n_init=10)
    d["クラスタ"] = km.fit_predict(Xs)
    summary = d.groupby("クラスタ").agg(
        人数=("患者ID", "count"),
        道路km=("道路km", "median"),
        年齢=("年齢", "median"),
        来局=("受診回数", "mean"),
        クリニック数=("受診クリニック数", "mean"),
        非門前率=("非門前", "mean"),
    ).sort_values("人数", ascending=False)
    summary.to_csv(PROCESSED_DIR / "phase4_clusters.csv", encoding="utf-8-sig")
    pd.DataFrame(scores).to_csv(PROCESSED_DIR / "phase4_cluster_silhouette.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(7, 4.5))
    sc = ax.scatter(d["道路km"], d["受診回数"].clip(upper=40), c=d["クラスタ"], s=10, alpha=0.5, cmap="tab10")
    ax.set_xlabel("道路km")
    ax.set_ylabel("受診回数")
    ax.set_title(f"患者クラスタ k={best_k}（シルエット={best_s:.3f}）\n距離≤30km / 自店患者")
    fig.colorbar(sc, ax=ax, label="cluster")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_clusters.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"k": best_k, "silhouette": best_s, "summary": summary, "scores": scores}


def write_reports(cohort, ret, surv, house, ltv, multi, clus) -> Dict[str, Path]:
    md = f"""# Phase 4: 継続・定着・LTV・セグメンテーション

## わかったこと3点

1. **初回90日定着は層で差がある。** 全体定着率 {ret['rate']:.1%}（N={ret['n']:,}、直近初回{ret['excluded_recent']:,}人は窓未満了で除外）。
2. **再来間隔の中央値は約{surv['median_gap']:.0f}日。** 28日以内再来 {surv['share_le28']:.1%} / 56日以内 {surv['share_le56']:.1%}（処方日数は非保有のため混合分布の記述）。
3. **クリニック階層のICC≈{multi.get('icc', float('nan')):.3f}。** 初回クリニックによりその後の来局量に差（ターゲティング候補）。

## わからなかったこと3点

1. **世帯・家族波及は不可。** {house['reason']}
2. 処方日数がないため、間隔ピークが疾患周期性か処方日数由来か分離できない。
3. LTVは観測打ち切りありの下限寄り。粗利は仮置き。

## 次に必要なデータ

- 住所詳細（世帯分析）、処方日数、粗利単価の確定、性別

---

## 1. コホート残存

![all](figures/phase4_cohort_all.png)
![gate](figures/phase4_cohort_gate.png)
![ng](figures/phase4_cohort_nongate.png)

- 平均残存の目安: 3か月後 {cohort['m3']:.1%} / 6か月 {cohort['m6']:.1%} / 12か月 {cohort['m12']:.1%}
- 門前初回の3か月残存 {cohort['gate_m3']:.1%} / 非門前初回 {cohort['nongate_m3']:.1%}

## 2. 初回定着（90日）

![ret](figures/phase4_retention90.png)

- サンプル: 初回受診日 ≤ { (END_DATE - pd.Timedelta(days=RETENTION_DAYS)).date() }
- McFadden擬似R²={ret['prsquared']:.3f} / AIC={ret['aic']:.1f}
- 層別: {ret['by_axis']}

> 新患フラグは使用していない（識別力なし）。

## 3. 来局間隔・生存

![int](figures/phase4_intervals.png)

- 観測間隔 N={surv['n_intervals']:,} / Cox c-index={surv['c_index']:.3f}

## 4. 世帯波及

**実行不可（住所詳細 {house['empty_detail']:,}/{house['n']:,} が空欄）。**

## 5. LTV

![ltv](figures/phase4_ltv.png)

- 粗利仮置き: {ltv['margin']:,.0f} 円/回（`config/economics.yaml`）
- 平均来局 {ltv['mean_visits']:.2f} 回

```
{ltv['sens'].to_string(index=False)}
```

## 6. マルチレベル

![multi](figures/phase4_multilevel.png)

- ICC≈{multi.get('icc', float('nan')):.3f} / グループ数={multi.get('n_groups')}

## 7. クラスタ

![clus](figures/phase4_clusters.png)

- 採用 k={clus['k']}（シルエット={clus['silhouette']:.3f}）

```
{clus['summary'].to_string()}
```

## 限界

- 年齢は基準日2026-07-31固定
- 自店来局のみ
- 因果表現はしない
"""
    path = REPORTS / "phase4_retention.md"
    path.write_text(md, encoding="utf-8")

    rep = HtmlReport(
        title="Phase 4 Retention & LTV",
        subtitle="コホート残存・90日定着・来局間隔・LTV感度・クリニック階層・患者クラスタ。世帯分析は住所詳細が空のため保留。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 4",
    )
    rep.add_kpi("90日定着率", f"{ret['rate']:.1%}", f"N={ret['n']:,}")
    rep.add_kpi("間隔中央値", f"{surv['median_gap']:.0f}日", f"≤28日 {surv['share_le28']:.0%}")
    rep.add_kpi("ICC", f"{multi.get('icc', float('nan')):.3f}", "クリニック階層")
    rep.add_kpi("クラスタk", str(clus["k"]), f"silhouette={clus['silhouette']:.3f}")

    rep.callout(
        "わかったこと",
        [
            f"90日定着 {ret['rate']:.1%}（層別差あり）。",
            f"再来間隔中央値 {surv['median_gap']:.0f}日。",
            f"クリニックICC≈{multi.get('icc', float('nan')):.3f} → 経由クリニックで定着差。",
        ],
        kind="ok",
    )
    rep.callout("限界", [house["reason"], "処方日数なし", "LTVは打ち切り下限・粗利仮置き"], kind="warn")

    rep.section("cohort", "コホート残存")
    rep.figure(FIGURES / "phase4_cohort_all.png")
    rep.figure(FIGURES / "phase4_cohort_gate.png", "門前初回")
    rep.figure(FIGURES / "phase4_cohort_nongate.png", "非門前初回")

    rep.section("retention", "初回90日定着")
    rep.figure(FIGURES / "phase4_retention90.png")

    rep.section("survival", "来局間隔")
    rep.figure(FIGURES / "phase4_intervals.png")

    rep.section("ltv", "LTV感度")
    rep.figure(FIGURES / "phase4_ltv.png")
    rep.table(
        ["粗利円", "平均LTV全体", "門前", "非門前"],
        [[int(r["粗利円"]), f"{r['平均LTV_全体']:.0f}", f"{r['平均LTV_門前']:.0f}", f"{r['平均LTV_非門前']:.0f}"] for _, r in ltv["sens"].iterrows()],
        numeric_cols=[0, 1, 2, 3],
    )

    if multi.get("ok"):
        rep.section("multi", "マルチレベル（クリニックRE）")
        rep.figure(FIGURES / "phase4_multilevel.png")

    rep.section("cluster", "患者クラスタ")
    rep.figure(FIGURES / "phase4_clusters.png")
    rep.table(
        ["クラスタ", "人数", "道路km中央", "年齢中央", "平均来局", "非門前率"],
        [
            [
                int(i),
                int(r["人数"]),
                f"{r['道路km']:.2f}",
                f"{r['年齢']:.0f}",
                f"{r['来局']:.2f}",
                f"{r['非門前率']:.1%}",
            ]
            for i, r in clus["summary"].iterrows()
        ],
        numeric_cols=[1, 2, 3, 4, 5],
    )

    html_path = REPORTS / "phase4_retention.html"
    rep.save(html_path)
    return {"md": path, "html": html_path}


def publish_docs(html_path: Path) -> None:
    import shutil

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, DOCS / "phase4_retention.html")
    for p in FIGURES.glob("phase4_*.png"):
        shutil.copy2(p, DOCS / "figures" / p.name)

    index = DOCS / "index.html"
    if index.exists() and "phase4_retention.html" not in index.read_text(encoding="utf-8"):
        text = index.read_text(encoding="utf-8")
        card = """
      <article class="card">
        <h2>Phase 4 · Retention &amp; LTV</h2>
        <p>コホート残存・90日定着・来局間隔・LTV・クリニック階層・クラスタ。</p>
        <a class="btn secondary" href="phase4_retention.html">レポートを開く</a>
      </article>
"""
        text = text.replace(
            """    </div>

    <div class="note">""",
            card + """
    </div>

    <div class="note">""",
            1,
        )
        index.write_text(text, encoding="utf-8")


def run_phase4() -> Dict:
    np.random.seed(SEED)
    ensure_dirs()
    data = load_base()
    patients = attach_first_attrs(data["pm"], data["vt"])
    patients.to_csv(PROCESSED_DIR / "phase4_patients_enriched.csv", index=False, encoding="utf-8-sig")

    cohort = cohort_retention(data["vh"], patients)
    ret = first_retention_logit(data["vh"], patients)
    surv = visit_interval_survival(data["vh"], patients)
    house = household_note(data["pm"])
    ltv = ltv_empirical(patients, surv["median_gap"])
    multi = multilevel_visits(patients)
    clus = cluster_patients(patients)
    paths = write_reports(cohort, ret, surv, house, ltv, multi, clus)
    publish_docs(paths["html"])
    return {
        "paths": paths,
        "retention90": ret["rate"],
        "median_gap": surv["median_gap"],
        "icc": multi.get("icc"),
        "k": clus["k"],
    }


if __name__ == "__main__":
    out = run_phase4()
    print("wrote", out["paths"])
    print(
        "retention90=",
        round(out["retention90"], 3),
        "median_gap=",
        out["median_gap"],
        "icc=",
        out["icc"],
        "k=",
        out["k"],
    )
