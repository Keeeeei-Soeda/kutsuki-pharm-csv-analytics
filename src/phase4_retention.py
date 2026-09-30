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
from src.kpi import save_page_summary
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]
END_DATE = pd.Timestamp("2026-07-31")
RETENTION_DAYS = 90
MIN_CLINIC_PATIENTS = 30
AXIS_PLAIN = {"門前型": "門前", "非門前型": "門前以外"}


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
        "コホート残存率【初回が門前】",
        "phase4_cohort_gate.png",
    )
    rate_ng = heat(
        v.loc[v["初回軸"] == "非門前型"],
        "コホート残存率【初回が門前以外】",
        "phase4_cohort_nongate.png",
    )
    # summary at month 3 / 6 / 12
    def avg_at(rate, m):
        if m not in rate.columns:
            return np.nan
        return float(rate[m].mean())

    curves = {
        "門前": _retention_curve(v.loc[v["初回軸"] == "門前型"]),
        "門前以外": _retention_curve(v.loc[v["初回軸"] == "非門前型"]),
    }
    _plot_retention_curve(curves)

    return {
        "m3": avg_at(rate_all, 3),
        "m6": avg_at(rate_all, 6),
        "m12": avg_at(rate_all, 12),
        "gate_m3": avg_at(rate_gate, 3),
        "nongate_m3": avg_at(rate_ng, 3),
        "curves": curves,
    }


def _retention_curve(df: pd.DataFrame, max_month: int = 12) -> pd.Series:
    """経過月ごとの「その月に来局した人の割合」。その月まで観測できる初回月の患者だけを分母にする。"""
    last_month = END_DATE.to_period("M")
    size = df.groupby("初回月")["患者ID"].nunique()
    active = df.groupby(["初回月", "経過月"])["患者ID"].nunique().unstack(fill_value=0)
    out = {}
    for m in range(0, max_month + 1):
        eligible = [c for c in size.index if (last_month - c).n >= m]
        if not eligible or m not in active.columns:
            continue
        out[m] = active.loc[eligible, m].sum() / size.loc[eligible].sum()
    return pd.Series(out)


def _plot_retention_curve(curves: Dict[str, pd.Series]) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.6))
    for label, color in [("門前", "#c45c26"), ("門前以外", "#2f6f9f")]:
        s = curves[label].iloc[1:] * 100
        ax.plot(s.index, s.values, marker="o", color=color, lw=2, label=f"初回が{label}")
        ax.text(s.index[-1] + 0.2, s.values[-1], f"{s.values[-1]:.0f}%", color=color, va="center", fontsize=10)
    ax.set_xlabel("初回来局からの経過月")
    ax.set_ylabel("その月にも来局した人の割合（%）")
    ax.set_ylim(0, None)
    ax.set_xticks(range(1, 13))
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False)
    ax.set_title("初回から何か月後まで来局が続いているか", loc="left")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_retention_curve.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


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
    ax.set_xticklabels([AXIS_PLAIN.get(str(t.get_text()), t.get_text()) for t in ax.get_xticklabels()], rotation=0)
    ax.set_xlabel("")
    ax.set_title(f"初回定着率（全体 {rate:.1%}）\nN={int(mask.sum())} / 初回が{cutoff.date()}以前")

    ax = axes[1]
    keys = ["log距離", "年齢", "非門前", "上位門前クリニック"]
    sub = coef.loc[[k for k in keys if k in coef.index]]
    ax.barh(sub.index, sub["OR"], color="#0f6a6a")
    ax.axvline(1, color="#333", lw=1)
    ax.set_xlabel("オッズ比")
    ax.set_title("90日定着ロジスティック OR（相関）")
    fig.suptitle(f"{PHARMACY_NAME} 初回定着（新患フラグ不使用・自前定義）", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_retention90.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    eligible = p.dropna(subset=["初回クリニック名"])
    by_clinic = (
        eligible.groupby("初回クリニック名")["定着90"].agg(人数="count", 再来率="mean")
        .query(f"人数 >= {MIN_CLINIC_PATIENTS}")
        .sort_values("再来率", ascending=False)
    )
    by_clinic.to_csv(PROCESSED_DIR / "phase4_retention90_by_clinic.csv", encoding="utf-8-sig")

    return {
        "n": int(mask.sum()),
        "rate": rate,
        "rate_all_eligible": float(p["定着90"].mean()),
        "n_eligible": len(p),
        "single_share": float((p["受診回数"] == 1).mean()),
        "by_axis_all": p.groupby("初回軸")["定着90"].mean().to_dict(),
        "by_clinic": by_clinic,
        "cutoff": cutoff,
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
        km.fit(sub, event_observed=np.ones(len(sub)), label=f"初回が{AXIS_PLAIN[label]}")
        km.plot_survival_function(ax=ax, color=color)
    ax.set_title("来局間隔のKM（観測された再来間隔）\n注: 処方日数非保有。打ち切り最終日=2026-07-31")
    ax.set_xlabel("間隔日数")
    ax.set_ylabel("まだ次の来局がない割合")

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
        ax.hist(sub, bins=40, alpha=0.55, label=f"初回が{AXIS_PLAIN[label]}", color=color)
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
    summary["タイプ"] = _name_clusters(summary, feats)
    summary.to_csv(PROCESSED_DIR / "phase4_clusters.csv", encoding="utf-8-sig")
    pd.DataFrame(scores).to_csv(PROCESSED_DIR / "phase4_cluster_silhouette.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(8, 4.8))
    colors = plt.get_cmap("tab10")
    for i, (c, r) in enumerate(summary.iterrows()):
        sub = d.loc[d["クラスタ"] == c]
        ax.scatter(sub["道路km"], sub["受診回数"].clip(upper=40), s=10, alpha=0.5, color=colors(i),
                   label=f"{r['タイプ']}（{int(r['人数']):,}人）")
    ax.set_xlabel("薬局までの道のり（km）")
    ax.set_ylabel("来局回数（40回以上は40として表示）")
    ax.set_ylim(0, 52)
    ax.set_title("患者のタイプ（薬局から30km以内の患者）", loc="left")
    ax.legend(frameon=True, facecolor="white", edgecolor="none", fontsize=9, markerscale=2, loc="upper right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase4_clusters.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"k": best_k, "silhouette": best_s, "summary": summary, "scores": scores}


CLUSTER_NAMES = {
    "来局": "よく来る常連の人",
    "クリニック数": "複数のクリニックを使う人",
    "道路km": "遠方から来る人",
    "非門前率": "門前以外から来る人",
    "年齢": "年齢が高めの人",
}
CLUSTER_DEFAULT_NAME = "近所のたまに来る人"


def _name_clusters(summary: pd.DataFrame, feats: pd.DataFrame) -> list:
    """各タイプで全体平均から最も大きく上に離れている特徴を名前にする（どれも平均並みなら既定の名前）。"""
    col_of = {"来局": "受診回数", "クリニック数": "受診クリニック数", "道路km": "道路km", "非門前率": "非門前", "年齢": "年齢"}
    names = []
    for _, r in summary.iterrows():
        z = {k: (r[k] - feats[c].mean()) / feats[c].std() for k, c in col_of.items()}
        key, val = max(z.items(), key=lambda kv: kv[1])
        name = CLUSTER_NAMES[key] if val >= 0.3 else CLUSTER_DEFAULT_NAME
        if min(z["来局"], z["クリニック数"]) >= 1.0:
            name = "近所の常連（複数のクリニックを利用）"
        while name in names:
            name += "（その2）"
        names.append(name)
    return names


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

    rate = ret["rate_all_eligible"]
    gate_rate = ret["by_axis_all"].get("門前型", float("nan"))
    nongate_rate = ret["by_axis_all"].get("非門前型", float("nan"))
    bc = ret["by_clinic"]
    clinic_gap_pt = (bc["再来率"].max() - bc["再来率"].min()) * 100
    weeks = surv["median_gap"] / 7
    single = ret["single_share"]
    c = ret["cutoff"]
    cutoff_label = f"{c.year}年{c.month}月{c.day}日"

    rep = HtmlReport(
        title="患者は定着しているか",
        subtitle="初めて来た患者が、その後も来続けているかを見ます。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 4",
        active_phase=4,
    )
    rep.add_kpi("90日以内にもう一度来た人", f"{rate:.0%}", f"初回来局から90日以上たった {ret['n_eligible']:,}人のうち",
                compare=f"初回が門前 {gate_rate:.0%} ／ 門前以外 {nongate_rate:.0%}", tone="neutral")
    rep.add_kpi("次の来局までの間隔", f"約{weeks:.0f}週間", f"真ん中の値 {surv['median_gap']:.0f}日",
                compare=f"4週間以内に次の来局があった割合は {surv['share_le28']:.0%}", tone="neutral")
    rep.add_kpi("クリニックによる再来率の差", f"最大{clinic_gap_pt:.0f}ポイント",
                f"初回の患者が{MIN_CLINIC_PATIENTS}人以上いる {len(bc)}院で比較",
                compare=f"最も高い院 {bc['再来率'].max():.0%} ／ 最も低い院 {bc['再来率'].min():.0%}", tone="bad")
    rep.add_kpi("1回だけで来なくなった人", f"{single:.0%}", f"初回来局から90日以上たった {ret['n_eligible']:,}人のうち",
                compare=f"90日以内にもう一度来た人は {rate:.0%}", tone="bad")

    rep.takeaway(
        finding=f"初めて来た人のうち、90日以内にまた来るのは{rate:.0%}です。",
        judgment=(
            f"約{1 - rate:.0%}は90日以内に戻らず、{single:.0%}は1回きりです。"
            f"経由クリニックによって再来率に最大{clinic_gap_pt:.0f}ポイントの差があります。"
        ),
        action=(
            "初回来局時の声かけ（次回の来局案内、お薬手帳・LINE登録など）を徹底し、"
            "再来率の低いクリニック経由の患者から優先して試します。"
        ),
    )

    rep.section("curve", "初回から何か月後まで来ているか")
    g = cohort["curves"]["門前"]
    ng = cohort["curves"]["門前以外"]
    rep.figure(
        FIGURES / "phase4_retention_curve.png",
        point=(
            f"初回の翌月にも来た人は、門前経由で{g.get(1, float('nan')):.0%}、門前以外経由で{ng.get(1, float('nan')):.0%}です。"
        ),
        explain=(
            "初めて来局した月から数えて、その月にも来局した人の割合です。"
            "その月まで観測できる患者だけで計算しています。"
        ),
    )

    rep.section("clinics", "クリニック別の再来率")
    rep.paragraph(
        f"初回に経由したクリニックごとの、90日以内にもう一度来た人の割合です"
        f"（初回の患者が{MIN_CLINIC_PATIENTS}人以上のクリニック）。"
    )
    rep.table(
        ["初回に経由したクリニック", "もとになった人数", "90日以内にもう一度来た人の割合"],
        [[str(n)[:24], f"{int(r['人数']):,}", f"{r['再来率']:.0%}"] for n, r in bc.iterrows()],
        numeric_cols=[1, 2],
    )

    rep.section("types", "患者のタイプ")
    rep.figure(
        FIGURES / "phase4_clusters.png",
        point="患者は、来局回数・通うクリニックの数・距離などで、いくつかのタイプに分かれます。",
        explain="点1つが患者1人です。色がタイプを表します。凡例の人数は、そのタイプの人数です。",
    )
    rep.table(
        ["タイプ", "人数", "薬局までの道のり（真ん中の値, km）", "年齢（真ん中の値）", "平均来局回数", "門前以外経由の割合"],
        [
            [
                r["タイプ"],
                f"{int(r['人数']):,}",
                f"{r['道路km']:.1f}",
                f"{r['年齢']:.0f}歳",
                f"{r['来局']:.1f}回",
                f"{r['非門前率']:.0%}",
            ]
            for _, r in clus["summary"].iterrows()
        ],
        numeric_cols=[1, 2, 3, 4, 5],
    )

    rep.section("ltv", "1人あたりの粗利の目安")
    rep.table(
        ["粗利を1回◯円と仮定した場合", "1人あたり粗利合計（全体）", "初回が門前", "初回が門前以外"],
        [
            [f"{int(r['粗利円']):,}円", f"{r['平均LTV_全体']:,.0f}円", f"{r['平均LTV_門前']:,.0f}円", f"{r['平均LTV_非門前']:,.0f}円"]
            for _, r in ltv["sens"].iterrows()
        ],
        numeric_cols=[1, 2, 3],
    )
    rep.paragraph("観測期間中の来局回数 × 1回あたりの粗利です。期間後も通い続ける人の分は含まないため、少なめの値です。")

    with rep.expert_details("専門家向けの詳細（コホート・ロジスティック・生存分析・マルチレベル・クラスタ）"):
        rep.callout(
            "データの扱いと限界",
            [
                house["reason"],
                "処方日数なし（間隔ピークが疾患周期か処方日数由来か分離できない）。",
                "LTVは打ち切り下限・粗利仮置き（config/economics.yaml）。",
                "新患フラグは使用していません（識別力なし）。初回＝期間内の最初の受診日です。",
                f"90日再来は初回が{cutoff_label}以前の患者に限定（直近の初回 {ret['excluded_recent']:,}人は観察期間不足で除外）。",
            ],
            kind="warn",
        )
        rep.section("cohort", "コホート残存")
        rep.paragraph(
            f"平均残存: 3か月後 {cohort['m3']:.1%} / 6か月 {cohort['m6']:.1%} / 12か月 {cohort['m12']:.1%}"
            f"（初回門前 3か月 {cohort['gate_m3']:.1%} / 初回門前以外 {cohort['nongate_m3']:.1%}）"
        )
        rep.figure(FIGURES / "phase4_cohort_all.png", "全体コホート残存")
        rep.figure(FIGURES / "phase4_cohort_gate.png", "初回が門前")
        rep.figure(FIGURES / "phase4_cohort_nongate.png", "初回が門前以外")

        rep.section("retention", "初回90日定着（ロジスティック回帰）")
        rep.paragraph(
            f"モデル標本 N={ret['n']:,}（道路距離30km以内）／定着率 {ret['rate']:.1%}／"
            f"McFadden擬似R²={ret['prsquared']:.3f}／AIC={ret['aic']:.1f}"
        )
        rep.figure(FIGURES / "phase4_retention90.png", "90日定着率の層別とオッズ比（相関）")

        rep.section("survival", "来局間隔（生存分析）")
        rep.paragraph(
            f"観測間隔 N={surv['n_intervals']:,} ／ 28日以内 {surv['share_le28']:.1%} ／ 56日以内 {surv['share_le56']:.1%} ／ "
            f"Cox c-index={surv['c_index']:.3f}"
        )
        rep.figure(FIGURES / "phase4_intervals.png", "再来間隔の分布と生存")

        rep.section("ltvfig", "LTV感度（来局回数分布）")
        rep.figure(FIGURES / "phase4_ltv.png", "粗利仮定ごとのLTV")

        if multi.get("ok"):
            rep.section("multi", "マルチレベル（クリニックRE）")
            rep.paragraph(
                f"ICC≈{multi.get('icc', float('nan')):.3f}（log来局、クリニック数 {multi.get('n_groups')}、N={multi.get('n'):,}）"
            )
            rep.figure(FIGURES / "phase4_multilevel.png", "クリニックランダム効果")

        rep.section("cluster", "クラスタリングの設定")
        rep.paragraph(
            f"KMeans（標準化: 道路km・年齢・受診回数・受診クリニック数・非門前）。"
            f"k=3〜6 を silhouette で比較し k={clus['k']}（silhouette={clus['silhouette']:.3f}）を採用。"
            "タイプ名は各タイプで全体平均から最も上に離れた特徴（標準化で0.3以上）から付与。"
        )

    html_path = REPORTS / "phase4_retention.html"
    rep.save(html_path)

    save_page_summary("p4", {
        "retention90": rate,
        "gate_retention90": gate_rate,
        "nongate_retention90": nongate_rate,
        "median_gap_days": surv["median_gap"],
        "clinic_gap_pt": clinic_gap_pt,
        "single_share": single,
        "conclusion": (
            f"90日以内にもう一度来た人は{rate:.0%}。クリニックによって最大{clinic_gap_pt:.0f}ポイントの差があります。"
        ),
    })
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
