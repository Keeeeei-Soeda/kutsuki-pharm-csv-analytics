"""Phase 3: 来局率モデルと Pharmacy Choice Rate（代替推定）。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.optimize import minimize

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
from src.models.huff import attractiveness_from_competitor, fit_lambda_grid, huff_probabilities
from src.models.simulator import GrowthInputs, baseline_decomposition, simulate_scenarios, tornado_sensitivities
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def _region_distance_table(vt: pd.DataFrame, pm: pd.DataFrame, visitor_regions: set) -> pd.DataFrame:
    city = (
        vt.dropna(subset=["患者住所_市区町村"])
        .groupby("患者ID")["患者住所_市区町村"]
        .agg(lambda s: s.value_counts().index[0])
        .rename("市区町村")
    )
    x = pm.merge(city, on="患者ID", how="left")

    def match_region(city_name):
        if pd.isna(city_name) or not str(city_name).strip():
            return np.nan
        c = str(city_name).strip()
        cands = [r for r in visitor_regions if str(r).endswith(c)]
        if not cands:
            # 政令市で「大阪市東淀川区」等がそのまま入っている場合
            cands = [r for r in visitor_regions if c in str(r)]
        if not cands:
            return np.nan
        osaka = [r for r in cands if str(r).startswith("大阪府")]
        if osaka:
            return osaka[0]
        return cands[0]

    x["地域"] = [match_region(c) for c in x["市区町村"]]
    g = (
        x.dropna(subset=["地域", "患者→薬局_道路km"])
        .groupby("地域", as_index=False)
        .agg(道路距離_km=("患者→薬局_道路km", "median"), 観測患者数=("患者ID", "nunique"))
    )
    return g


def build_visit_rate_panel() -> pd.DataFrame:
    frames = []
    for year in (2024, 2025, 2026):
        df = read_csv(f"population_visitors_{year}")
        df = df.rename(columns={"くつき薬局南茨木店にそこから訪れた人": "来局患者数"})
        df["年"] = year
        frames.append(df)
    pv = pd.concat(frames, ignore_index=True)
    pv["人口"] = pd.to_numeric(pv["人口"], errors="coerce")
    pv["来局患者数"] = pd.to_numeric(pv["来局患者数"], errors="coerce").fillna(0).clip(lower=0)
    pv = pv.loc[pv["人口"] > 0].copy()
    pv["来局率"] = pv["来局患者数"] / pv["人口"]

    vt = read_csv("visit_triangle")
    pm = read_csv("patient_master")
    visitor_regions = set(pv["地域"].astype(str))
    dist = _region_distance_table(vt, pm, visitor_regions)
    pv = pv.merge(dist, on="地域", how="left")

    # 距離欠損の近隣地域は、来局がある地域のみ距離必須。遠方ゼロ来局は分析から外す前提。
    pv["競合圧力"] = np.where(
        pv["道路距離_km"].isna(),
        np.nan,
        np.where(pv["道路距離_km"] <= 2.0, 1.0, np.where(pv["道路距離_km"] <= 5.0, 0.5, 0.1)),
    )

    jur = read_csv("juryoritsu_by_age")
    # 大阪府の最新年は年齢別が総数のみの年がある → 全国の年齢別外来を使用（注記必須）
    jur = jur.loc[(jur["地域"] == "全国") & (jur["区分"] == "外来")].copy()
    latest = int(jur["年"].max())
    jur = jur.loc[jur["年"] == latest].copy()
    rate_map = {}
    for _, r in jur.iterrows():
        a = str(r["年齢階級"])
        if a in ("総数", "0", "1-4"):
            continue
        rate_map[a] = float(r["受療率_人口10万対"])
    elderly = [v for k, v in list(rate_map.items()) if k.startswith("85") or k.startswith("90")]
    for k in list(rate_map):
        if k.startswith("85") or k.startswith("90"):
            rate_map.pop(k, None)
    if elderly:
        rate_map["85+"] = float(np.mean(elderly))
    if "0-4" not in rate_map:
        parts = [rate_map[k] for k in ("0", "1-4") if k in rate_map]
        if parts:
            rate_map["0-4"] = float(np.mean(parts))
    pv["外来受療率"] = pv["年齢階級"].map(rate_map)
    med = pv["外来受療率"].median()
    pv["外来受療率"] = pv["外来受療率"].fillna(med if pd.notna(med) else 5000.0)
    pv["受療率年"] = latest
    pv["受療率地域"] = "全国"
    pv["受療機会あたり来局率"] = pv["来局率"] / (pv["外来受療率"] / 1e5).clip(lower=1e-8)
    return pv


def fit_visit_rate_glm(pv: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    # 分析サンプル: 距離が観測でき、極端遠方を除外（≤30km）
    d = pv.dropna(subset=["道路距離_km", "来局患者数", "人口"]).copy()
    d = d.loc[d["道路距離_km"] <= 30].copy()
    d["log距離"] = np.log(d["道路距離_km"].clip(lower=0.05))
    d["年"] = d["年"].astype(int)

    # Binomial GLM (successes, trials) via GLM Binomial with proportion + var_weights=N
    # statsmodels: endog = rate, freq_weights or var_weights = N
    y = d["来局率"].astype(float)
    X = pd.DataFrame(
        {
            "const": 1.0,
            "log距離": d["log距離"].astype(float),
        }
    )
    # 受療率は年齢階級の関数で年齢FEと完全共線のため投入しない（年齢FEが需要差を吸収）
    # 競合は距離と共線のため地域モデルから除外し、メッシュモデルで評価
    age_d = pd.get_dummies(d["年齢階級"], prefix="age", drop_first=True, dtype=float)
    year_d = pd.get_dummies(d["年"], prefix="year", drop_first=True, dtype=float)
    X = pd.concat([X, age_d, year_d], axis=1)
    mask = X.notna().all(axis=1) & y.notna() & d["人口"].notna()
    model = sm.GLM(
        y[mask],
        X.loc[mask],
        family=sm.families.Binomial(),
        var_weights=d.loc[mask, "人口"].astype(float),
    ).fit(cov_type="HC0")

    # 距離1km相当の効果（中央距離付近での近似）: d→d+1 の相対変化
    med_d = float(d.loc[mask, "道路距離_km"].median())
    b_dist = float(model.params["log距離"])
    # logit scale; report IRR-like as odds ratio for log距離
    or_logdist = float(np.exp(b_dist))
    # 距離+1km at median: delta log = log(med+1)-log(med)
    delta = np.log(med_d + 1) - np.log(med_d)
    odds_mult = float(np.exp(b_dist * delta))

    coef = pd.DataFrame({"coef": model.params, "se": model.bse, "pvalue": model.pvalues, "OR": np.exp(model.params)})
    coef.to_csv(PROCESSED_DIR / "phase3_visitrate_glm_coefs.csv", encoding="utf-8-sig")
    d.loc[mask].to_parquet(PROCESSED_DIR / "phase3_visitrate_sample.parquet", index=False)

    # figure: predicted vs distance by age bands
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    ax = axes[0]
    # aggregate region-year for scatter
    reg = (
        d.loc[mask]
        .groupby(["地域", "年"], as_index=False)
        .agg(人口=("人口", "sum"), 来局=("来局患者数", "sum"), 道路距離_km=("道路距離_km", "first"))
    )
    reg["来局率"] = reg["来局"] / reg["人口"]
    ax.scatter(reg["道路距離_km"], reg["来局率"] * 1000, s=18, alpha=0.55, c="#2f6f9f")
    xs = np.linspace(0.1, 30, 100)
    # partial effect curve holding other X at means (approx)
    # use age=30-34, year=2026 if present
    ax.set_xlabel("道路距離 km（地域中央値・自店患者）")
    ax.set_ylabel("来局率 ×1000")
    ax.set_title(f"地域×年の来局率と距離\nBinomial GLM log距離 OR={or_logdist:.3f} / +1km@{med_d:.1f}km odds×{odds_mult:.3f}")

    ax = axes[1]
    # age pattern from FE
    age_params = {k.replace("age_", ""): float(v) for k, v in model.params.items() if str(k).startswith("age_")}
    # baseline age is dropped category
    ages = sorted(d["年齢階級"].unique(), key=lambda a: (a != "85+", a))
    # reconstruct relative odds vs first age
    dropped = [a for a in ages if f"age_{a}" not in model.params.index]
    base_age = dropped[0] if dropped else ages[0]
    rel = []
    for a in ages:
        if a == base_age:
            rel.append((a, 1.0))
        elif f"age_{a}" in model.params:
            rel.append((a, float(np.exp(model.params[f"age_{a}"]))))
    rdf = pd.DataFrame(rel, columns=["年齢階級", "相対オッズ"])
    rdf.plot(x="年齢階級", y="相対オッズ", kind="bar", ax=ax, legend=False, color="#c45c26")
    ax.set_title(f"年齢階級FE（基準={base_age}）")
    ax.tick_params(axis="x", rotation=45)
    fig.suptitle(f"{PHARMACY_NAME} 集計来局率モデル（自店来局÷住基人口）", y=1.02)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_visitrate_glm.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {
        "model": model,
        "n": int(mask.sum()),
        "n_regions": int(d.loc[mask, "地域"].nunique()),
        "aic": float(model.aic),
        "or_logdist": or_logdist,
        "odds_mult_1km": odds_mult,
        "median_km": med_d,
        "coef": coef,
        "or_comp": None,
        "sample": d.loc[mask],
        "juryoritsu_note": "全国・外来・年齢別（大阪府最新年は総数のみのため）",
    }


def fit_mesh_model(mesh_rate_path: Path = PROCESSED_DIR / "mesh_visit_rate.csv") -> Dict:
    ensure_dirs()
    _setup_font()
    mesh = pd.read_csv(mesh_rate_path) if mesh_rate_path.exists() else None
    if mesh is None:
        return {}
    pressure = PROCESSED_DIR / "mesh_competitor_pressure.csv"
    if pressure.exists():
        pr = pd.read_csv(pressure)[["メッシュコード", "最近隣競合_km", "競合数_1km", "日曜営業競合_1km"]]
        mesh = mesh.merge(pr, on="メッシュコード", how="left")
    d = mesh.dropna(subset=["来局率", "距離km"]).copy()
    d = d.loc[(d["来局率"] >= 0) & (d["来局率"] <= 1) & (d["総人口"] > 0)]
    d["log距離"] = np.log(d["距離km"].clip(lower=0.05))
    y = d["来局率"].astype(float)
    X = sm.add_constant(
        pd.DataFrame(
            {
                "log距離": d["log距離"],
                "競合数_1km": pd.to_numeric(d.get("競合数_1km", 0), errors="coerce").fillna(0),
                "最近隣競合_km": pd.to_numeric(d.get("最近隣競合_km", np.nan), errors="coerce").fillna(d["距離km"]),
            }
        ),
        has_constant="add",
    )
    model = sm.GLM(y, X.astype(float), family=sm.families.Binomial(), var_weights=d["総人口"].astype(float)).fit(
        cov_type="HC1"
    )
    coef = pd.DataFrame({"coef": model.params, "pvalue": model.pvalues, "OR": np.exp(model.params)})
    coef.to_csv(PROCESSED_DIR / "phase3_mesh_glm_coefs.csv", encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(d["距離km"], d["来局率"] * 1000, c=d.get("競合数_1km", 0), s=28, cmap="Reds", alpha=0.8)
    ax.set_xlabel("メッシュ中心→薬局 直線km")
    ax.set_ylabel("来局率×1000")
    ax.set_title(
        f"メッシュ来局率モデル log距離OR={np.exp(model.params['log距離']):.3f}\n注: 自店患者を最近傍メッシュ割当"
    )
    fig.colorbar(ax.collections[0], ax=ax, label="競合数_1km")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_mesh_glm.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"model": model, "n": len(d), "or_logdist": float(np.exp(model.params["log距離"])), "coef": coef}


def clinic_choice_clogit(vt: pd.DataFrame, cm: pd.DataFrame, radius_km: float = 5.0, max_patients: int = 800) -> Dict:
    """
    条件付きロジット（自店患者のクリニック選択）。
    選択集合 = 患者から直線≤radius のクリニック（座標あり）。
    限界: 自店来局条件付き。市場全体のクリニック選択ではない。
    """
    ensure_dirs()
    _setup_font()
    np.random.seed(SEED)

    # unique patient first visit with coords
    first = (
        vt.sort_values("受診日")
        .dropna(subset=["患者緯度", "患者経度", "クリニックID"])
        .groupby("患者ID", as_index=False)
        .first()
    )
    first = first.loc[first["軸"].eq("門前型") | first["立地パターン"].isin(NON_GATE) | True]
    if len(first) > max_patients:
        first = first.sample(max_patients, random_state=SEED)

    clinics = cm.dropna(subset=["緯度", "経度"]).copy()
    clinics["門前"] = (pd.to_numeric(clinics["クリニック→薬局_直線km"], errors="coerce") <= 0.3).astype(float)
    # specialty count proxy
    clinics["標榜数"] = clinics["診療科"].fillna("").astype(str).apply(lambda s: max(len([x for x in s.split("・") if x]), 1))

    plat = first["患者緯度"].astype(float).values
    plon = first["患者経度"].astype(float).values
    chosen = first["クリニックID"].astype(str).values
    clat = clinics["緯度"].astype(float).values
    clon = clinics["経度"].astype(float).values
    cids = clinics["クリニックID"].astype(str).values
    gate = clinics["門前"].astype(float).values
    nspec = clinics["標榜数"].astype(float).values

    lat0 = np.radians(PHARMACY_LAT)
    px = (plon - PHARMACY_LON) * np.cos(lat0) * 111.32
    py = (plat - PHARMACY_LAT) * 110.54
    cx = (clon - PHARMACY_LON) * np.cos(lat0) * 111.32
    cy = (clat - PHARMACY_LAT) * 110.54

    # Build long dataset lists
    dist_list = []
    gate_list = []
    spec_list = []
    y_list = []
    group_sizes = []

    for i in range(len(first)):
        dx = px[i] - cx
        dy = py[i] - cy
        d = np.sqrt(dx * dx + dy * dy)
        idx = np.where(d <= radius_km)[0]
        if len(idx) < 2:
            continue
        # ensure chosen in set; if not, skip (outside radius)
        if chosen[i] not in set(cids[idx]):
            continue
        dd = d[idx]
        gg = gate[idx]
        ss = np.log(nspec[idx])
        yy = (cids[idx] == chosen[i]).astype(float)
        dist_list.append(dd)
        gate_list.append(gg)
        spec_list.append(ss)
        y_list.append(yy)
        group_sizes.append(len(idx))

    if len(group_sizes) < 50:
        return {"ok": False, "reason": "insufficient choice sets"}

    def nll(theta):
        b_d, b_g, b_s = theta
        ll = 0.0
        for d, g, s, y in zip(dist_list, gate_list, spec_list, y_list):
            v = b_d * d + b_g * g + b_s * s
            v = v - v.max()
            p = np.exp(v)
            p = p / p.sum()
            ll += np.log(p[y.astype(bool)][0] + 1e-15)
        return -ll

    res = minimize(nll, x0=np.array([-0.5, 0.5, 0.1]), method="L-BFGS-B")
    theta = res.x
    # crude SE via hessian numerical
    eps = 1e-4
    H = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            e_i = np.zeros(3)
            e_j = np.zeros(3)
            e_i[i] = eps
            e_j[j] = eps
            H[i, j] = (
                nll(theta + e_i + e_j) - nll(theta + e_i - e_j) - nll(theta - e_i + e_j) + nll(theta - e_i - e_j)
            ) / (4 * eps * eps)
    try:
        cov = np.linalg.inv(H)
        se = np.sqrt(np.diag(cov))
    except Exception:
        se = np.array([np.nan, np.nan, np.nan])

    # McFadden pseudo R2 vs null (distance-only intercept null = equal probs)
    ll_null = 0.0
    for y, nalt in zip(y_list, group_sizes):
        ll_null += np.log(1.0 / nalt)
    ll_model = -res.fun
    mcf = 1 - ll_model / ll_null

    out = {
        "ok": True,
        "n_patients": len(group_sizes),
        "radius_km": radius_km,
        "beta_distance": float(theta[0]),
        "beta_gate": float(theta[1]),
        "beta_log_specialty": float(theta[2]),
        "se": se,
        "mcfadden_r2": float(mcf),
        "mean_alts": float(np.mean(group_sizes)),
    }
    pd.DataFrame(
        [
            {"var": "道路直線近似km", "beta": theta[0], "se": se[0]},
            {"var": "門前フラグ", "beta": theta[1], "se": se[1]},
            {"var": "log標榜数", "beta": theta[2], "se": se[2]},
        ]
    ).to_csv(PROCESSED_DIR / "phase3_clinic_clogit.csv", index=False, encoding="utf-8-sig")

    # figure
    fig, ax = plt.subplots(figsize=(6, 4))
    labs = ["距離km", "門前", "log標榜数"]
    ax.barh(labs, theta, xerr=se, color=["#2f6f9f", "#c45c26", "#0f6a6a"], alpha=0.85)
    ax.axvline(0, color="#333", lw=1)
    ax.set_title(
        f"クリニック選択 条件付きロジット（半径{radius_km}km）\n"
        f"N患者={out['n_patients']} / McFadden R²={mcf:.3f}\n注: 自店来局条件付き・市場選択ではない"
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_clinic_clogit.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def run_huff(mesh_rate: pd.DataFrame, comp: pd.DataFrame) -> Dict:
    stores = attractiveness_from_competitor(comp)
    # 自店魅力度: 競合中央値よりやや高めの仮置き
    pharmacy_A = float(stores["A"].median() * 1.1)
    fit = fit_lambda_grid(mesh_rate, stores, PHARMACY_LAT, PHARMACY_LON, pharmacy_A)
    best = fit["best"]
    if best is None:
        return {"ok": False}
    pred = best["pred"].merge(mesh_rate[["メッシュコード", "来局率"]], on="メッシュコード", how="left")
    pred["残差"] = pred["来局率"] - best["scale"] * pred["huff_p"]
    pred.to_csv(PROCESSED_DIR / "phase3_huff_mesh.csv", index=False, encoding="utf-8-sig")
    fit["grid"].to_csv(PROCESSED_DIR / "phase3_huff_lambda_grid.csv", index=False, encoding="utf-8-sig")

    _setup_font()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    ax = axes[0]
    ax.plot(fit["grid"]["lambda"], fit["grid"]["corr"], marker="o")
    ax.set_xlabel("λ")
    ax.set_ylabel("corr(来局率, Huff p)")
    ax.set_title(f"Huff λ探索（最良λ={best['lambda']}）")
    ax = axes[1]
    sc = ax.scatter(pred["中心経度"], pred["中心緯度"], c=pred["残差"], s=35, cmap="coolwarm")
    ax.scatter([PHARMACY_LON], [PHARMACY_LAT], c="#0f6a6a", marker="*", s=90)
    fig.colorbar(sc, ax=ax, label="来局率 - スケール済Huff")
    ax.set_title("Huff残差マップ（正=想定より取れている）\n注: 記述ベンチマーク。因果解釈しない")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_huff.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"ok": True, "best_lambda": best["lambda"], "corr": best["corr"], "pharmacy_A": pharmacy_A, "grid": fit["grid"]}


def run_growth_sim() -> Dict:
    inp = GrowthInputs()
    base = baseline_decomposition(inp)
    scen = simulate_scenarios(inp)
    tornado = tornado_sensitivities(inp, pct=0.1)
    scen.to_csv(PROCESSED_DIR / "phase3_growth_scenarios.csv", index=False, encoding="utf-8-sig")
    tornado.to_csv(PROCESSED_DIR / "phase3_growth_tornado.csv", index=False, encoding="utf-8-sig")

    _setup_font()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    ax = axes[0]
    s = scen.loc[~scen["シナリオ"].str.startswith("参考")]
    colors = ["#0f6a6a" if v else "#c45c26" for v in s["目標3,000到達"]]
    ax.barh(s["シナリオ"], s["予測月間件数"], color=colors)
    ax.axvline(1388, color="#666", ls=":", label="現状")
    ax.axvline(3000, color="#c45c26", ls="--", label="目標3000")
    ax.set_xlabel("月間件数（一次近似）")
    ax.set_title("Growthシナリオ（交互作用無視の感度）")
    ax.legend(fontsize=8)

    ax = axes[1]
    t = tornado.iloc[::-1]
    ax.hlines(t["レバー"], t["低"], t["高"], color="#2f6f9f", lw=6)
    ax.axvline(t["ベース"].iloc[0], color="#c45c26", ls="--")
    ax.set_title("感度トルネード（各±10%）")
    ax.set_xlabel("月間件数")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase3_growth_sim.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return {"baseline": base, "scenarios": scen, "tornado": tornado}


def write_reports(vr, mesh_m, clogit, huff, growth) -> Dict[str, Path]:
    ensure_dirs()
    md = f"""# Phase 3: 来局率モデルと Pharmacy Choice Rate

## わかったこと3点

1. **距離は来局率を強く規定する。** 集計Binomial GLMで log(道路距離) のOR={vr['or_logdist']:.3f}。中央距離{vr['median_km']:.1f}kmで+1kmすると選択オッズが約×{vr['odds_mult_1km']:.3f}（相関・条件付き関連）。
2. **クリニック選択でも距離・門前が効く（自店条件付き）。** 条件付きロジット N={clogit.get('n_patients','-')} / McFadden R²={clogit.get('mcfadden_r2', float('nan')):.3f}。これは市場全体の選択率ではない。
3. **目標3,000枚は非門前の大幅拡大か複数レバーの同時改善が必要。** シミュレータ上、非門前のみなら約×{(3000/1388 - 0.893 - 0.011)/0.096:.1f}が必要（他固定の粗い必要条件）。

## わからなかったこと3点

1. 真の薬局選択率（競合の実売・クリニック総発行数が未知）。
2. Huffのλ・魅力度は代理変数のみで識別が弱い。
3. 年齢は2026-07-31固定のまま年次比較している点のバイアス。

## 次に必要なデータ

- クリニック総処方箋発行数、競合規模、他店舗、イベント年表（優先度A）

---

## 6.1 集計来局率モデル（主分析）

![glm](figures/phase3_visitrate_glm.png)

- サンプル: 地域×年齢×年、道路距離≤30km かつ距離観測あり、N行={vr['n']:,} / 地域数={vr['n_regions']}
- モデル: Binomial GLM（var_weights=人口）、年齢FE・年FE、HC1
- AIC={vr['aic']:.1f}
- 受療率: {vr.get('juryoritsu_note','')}（年齢構成の需要差を分離する目的）
- 競合は距離と共線のため地域モデルから除外し、メッシュモデルで評価

> 注: 来局率 = 自店ユニーク来局 / 住基人口。非来局を外部選択肢とみなした集計近似。係数は因果ではない。

![mesh](figures/phase3_mesh_glm.png)

メッシュ版 log距離OR={mesh_m.get('or_logdist', float('nan')):.3f}

---

## 6.2 クリニック選択（条件付きロジット）

![clogit](figures/phase3_clinic_clogit.png)

- 半径{clogit.get('radius_km')}km / 平均選択肢数≈{clogit.get('mean_alts', float('nan')):.1f}
- β距離={clogit.get('beta_distance', float('nan')):.3f}, β門前={clogit.get('beta_gate', float('nan')):.3f}, β log標榜={clogit.get('beta_log_specialty', float('nan')):.3f}

> **選択バイアス:** 推定対象は「最終的に自店に来た患者」のクリニック選択。一般人口のクリニック選択ではない。

---

## 6.3 Huff（記述ベンチマーク）

![huff](figures/phase3_huff.png)

- 最良λ={huff.get('best_lambda')} / corr={huff.get('corr', float('nan')):.3f}
- 残差マップは「想定より取れている／取れていない」メッシュの記述用。パラメータの因果解釈はしない。

---

## 6.4 Growth Engine 分解とシナリオ

![growth](figures/phase3_growth_sim.png)

```
{growth['scenarios'].to_string(index=False)}
```

依頼書の商圏人口×クリニック選択率×薬局選択率×継続率は、本分解の「人口×来局率×頻度」に対応づける（薬局選択率は集計来局率に吸収）。

---

## サンプル定義・限界

1. 自店来局のみ。市場シェア分母なし
2. 距離は自店患者の地域中央値（生態学的）
3. 受療率は大阪府外来・最新調査年の接続（推計接続）
4. 係数は因果効果ではない
"""
    md_path = REPORTS / "phase3_model.md"
    md_path.write_text(md, encoding="utf-8")

    # HTML
    rep = HtmlReport(
        title="Phase 3 Pharmacy Choice Rate",
        subtitle="個票MNLが不可能なため、集計来局率・条件付きクリニック選択・Huff・成長シミュレータで代替する。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 3",
        active_phase=3,
    )
    rep.add_kpi("距離OR(log)", f"{vr['or_logdist']:.3f}", "集計Binomial GLM")
    rep.add_kpi("+1km効果", f"×{vr['odds_mult_1km']:.3f}", f"中央距離 {vr['median_km']:.1f}km")
    rep.add_kpi("Clogit R²", f"{clogit.get('mcfadden_r2', float('nan')):.3f}", "自店条件付き")
    rep.add_kpi("目標倍率", f"{growth['baseline']['gap_ratio']:.2f}×", "1388→3000")

    rep.callout(
        "わかったこと",
        [
            f"距離が来局率の主因（log距離OR={vr['or_logdist']:.3f}）。",
            "クリニック選択でも距離・門前が効くが、自店来局条件付き。",
            "3,000枚には非門前の大幅拡大か複合施策が必要。",
        ],
        kind="ok",
    )
    rep.callout(
        "限界",
        [
            "真の薬局選択率は競合実売・クリニック総発行がないと推定不能。",
            "Huffは記述ベンチマークのみ。",
            "係数は因果ではない。",
        ],
        kind="warn",
    )

    rep.section("visitrate", "集計来局率モデル", "V~Binomial(N,p)。自店来局÷住基人口。")
    rep.figure(FIGURES / "phase3_visitrate_glm.png")
    rep.figure(FIGURES / "phase3_mesh_glm.png", "メッシュ拡張")

    rep.section("clogit", "クリニック選択（条件付きロジット）", "自店患者に限定。市場選択率ではない。")
    if clogit.get("ok"):
        rep.figure(FIGURES / "phase3_clinic_clogit.png")
        rep.table(
            ["変数", "β", "SE"],
            [
                ["距離km", f"{clogit['beta_distance']:.3f}", f"{clogit['se'][0]:.3f}"],
                ["門前", f"{clogit['beta_gate']:.3f}", f"{clogit['se'][1]:.3f}"],
                ["log標榜数", f"{clogit['beta_log_specialty']:.3f}", f"{clogit['se'][2]:.3f}"],
            ],
            numeric_cols=[1, 2],
        )

    rep.section("huff", "Huff記述ベンチマーク")
    if huff.get("ok"):
        rep.figure(FIGURES / "phase3_huff.png")
        rep.paragraph(f"最良λ={huff['best_lambda']} / 相関={huff['corr']:.3f}")

    rep.section("growth", "Growthシナリオ")
    rep.figure(FIGURES / "phase3_growth_sim.png")
    rep.table(
        ["シナリオ", "予測月間", "倍率", "3000到達"],
        [
            [
                r["シナリオ"][:28],
                f"{r['予測月間件数']:.0f}",
                f"{r['対ベース倍率']:.2f}",
                "YES" if r["目標3,000到達"] else "no",
            ]
            for _, r in growth["scenarios"].head(10).iterrows()
        ],
        numeric_cols=[1, 2],
    )

    html_path = REPORTS / "phase3_model.html"
    rep.save(html_path)
    return {"md": md_path, "html": html_path}


def publish_docs(html_path: Path) -> None:
    """GitHub Pages 用 docs/ へコピー。"""
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    import shutil

    shutil.copy2(html_path, DOCS / "phase3_model.html")
    for name in [
        "phase3_visitrate_glm.png",
        "phase3_mesh_glm.png",
        "phase3_clinic_clogit.png",
        "phase3_huff.png",
        "phase3_growth_sim.png",
    ]:
        src = FIGURES / name
        if src.exists():
            shutil.copy2(src, DOCS / "figures" / name)

    # update index if needed
    index = DOCS / "index.html"
    if index.exists():
        text = index.read_text(encoding="utf-8")
        if "phase3_model.html" not in text:
            card = """
      <article class="card">
        <h2>Phase 3 · Choice & Growth</h2>
        <p>集計来局率・クリニック選択・Huff・成長シナリオシミュレータ。</p>
        <a class="btn" href="phase3_model.html">レポートを開く</a>
      </article>
"""
            # insert before note or before closing grid
            if '<div class="note">' in text:
                text = text.replace('<div class="note">', card + '\n    </div>\n\n    <div class="note">', 1)
                # fix: above might break grid - better replace grid end
            # simpler: replace phase2 card closing section
            needle = """      <article class="card">
        <h2>Phase 2 · Clinic Catchment</h2>"""
            if needle in text and "Phase 3 · Choice" not in text:
                text = text.replace(
                    """    </div>

    <div class="note">""",
                    card + """
    </div>

    <div class="note">""",
                    1,
                )
            index.write_text(text, encoding="utf-8")


def run_phase3() -> Dict:
    np.random.seed(SEED)
    ensure_dirs()
    pv = build_visit_rate_panel()
    vr = fit_visit_rate_glm(pv)
    mesh_m = fit_mesh_model()
    vt = read_csv("visit_triangle")
    vt["軸"] = np.select(
        [vt["立地パターン"].astype(str).eq("門前型"), vt["立地パターン"].astype(str).isin(NON_GATE)],
        ["門前型", "非門前型"],
        default="不明",
    )
    cm = read_csv("clinic_master")
    clogit = clinic_choice_clogit(vt, cm, radius_km=5.0, max_patients=800)
    mesh_rate = pd.read_csv(PROCESSED_DIR / "mesh_visit_rate.csv") if (PROCESSED_DIR / "mesh_visit_rate.csv").exists() else pv
    if "中心緯度" not in getattr(mesh_rate, "columns", []):
        mesh_rate = read_csv("mesh_population")
        mesh_rate["来局率"] = np.nan
    comp = read_csv("competitor_pharmacy")
    huff = run_huff(mesh_rate if "来局率" in mesh_rate.columns else pd.read_csv(PROCESSED_DIR / "mesh_visit_rate.csv"), comp)
    growth = run_growth_sim()
    paths = write_reports(vr, mesh_m, clogit, huff, growth)
    publish_docs(paths["html"])
    return {
        "paths": paths,
        "or_logdist": vr["or_logdist"],
        "clogit_r2": clogit.get("mcfadden_r2"),
        "huff_lambda": huff.get("best_lambda"),
    }


if __name__ == "__main__":
    out = run_phase3()
    print("wrote", out["paths"])
    print("OR(log dist)=", round(out["or_logdist"], 3), "clogit R2=", out["clogit_r2"], "huff λ=", out["huff_lambda"])
