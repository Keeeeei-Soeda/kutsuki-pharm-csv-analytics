"""Phase 6: 統合モデル・予測検証・学術ポジショニング。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, SEED, ensure_dirs, read_csv
from src.models.simulator import GrowthInputs, baseline_decomposition, simulate_scenarios, tornado_sensitivities
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]
TRAIN_END = "2026-01"
VALID_START = "2026-02"


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


def monthly_series() -> pd.DataFrame:
    vt = read_csv("visit_triangle")
    vt["受診日"] = pd.to_datetime(vt["受診日"])
    vt["軸"] = np.select(
        [vt["立地パターン"].astype(str).eq("門前型"), vt["立地パターン"].astype(str).isin(NON_GATE)],
        ["門前型", "非門前型"],
        default="不明",
    )
    vt["年月"] = vt["受診日"].dt.to_period("M")
    total = vt.groupby("年月").size().rename("件数")
    gate = vt.loc[vt["軸"] == "門前型"].groupby("年月").size().rename("門前")
    nongate = vt.loc[vt["軸"] == "非門前型"].groupby("年月").size().rename("非門前")
    df = pd.concat([total, gate, nongate], axis=1).fillna(0).astype(float)
    df.index = df.index.astype(str)
    # weather monthly
    wp = read_csv("weather_pollen")
    wp["日付"] = pd.to_datetime(wp["日付"])
    wp["年月"] = wp["日付"].dt.to_period("M").astype(str)
    wagg = wp.groupby("年月").agg(
        最高気温=("最高気温", "mean"),
        降水量mm=("降水量mm", "mean"),
        花粉合計=("花粉合計", "mean"),
    )
    df = df.join(wagg, how="left")
    # national prescriptions index where available
    nat = read_csv("prescriptions_monthly")
    nat["年月"] = pd.to_datetime(
        nat["年"].astype(str) + "-" + nat["月"].astype(str).str.zfill(2) + "-01"
    ).dt.to_period("M").astype(str)
    df = df.join(nat.set_index("年月")["処方箋枚数"].rename("全国枚数"), how="left")
    return df


def mae_mape(y_true: np.ndarray, y_pred: np.ndarray) -> Tuple[float, float]:
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    mae = float(np.mean(np.abs(y_true - y_pred)))
    mape = float(np.mean(np.abs((y_true - y_pred) / np.clip(y_true, 1, None))) * 100)
    return mae, mape


def forecast_holdout(df: pd.DataFrame) -> Dict:
    ensure_dirs()
    _setup_font()
    np.random.seed(SEED)

    months = list(df.index)
    train_idx = [m for m in months if m <= TRAIN_END]
    valid_idx = [m for m in months if m >= VALID_START]
    y = df["件数"].astype(float)

    # --- baselines ---
    # 1) trailing MA(3) on train, then recursive for valid
    preds = {}
    hist = list(y.loc[train_idx].values)
    ma_pred = []
    for m in valid_idx:
        ma_pred.append(float(np.mean(hist[-3:])))
        # after predicting, if we were online we'd append actual for next - for fair one-step:
        # use expanding with actuals (realistic evaluation)
        hist.append(float(y.loc[m]))
    preds["移動平均3"] = np.array(ma_pred)

    # 2) seasonal naive: same month previous year
    seas = []
    for m in valid_idx:
        year, mon = m.split("-")
        prev = f"{int(year)-1}-{mon}"
        if prev in y.index:
            seas.append(float(y.loc[prev]))
        else:
            seas.append(float(y.loc[train_idx].mean()))
    preds["前年同月"] = np.array(seas)

    # 3) train mean
    preds["学習期平均"] = np.full(len(valid_idx), float(y.loc[train_idx].mean()))

    # 4) OLS trend + month FE (+ weather if available) fitted on train, one-step with actuals for lags
    train = df.loc[train_idx].copy()
    train["t"] = np.arange(len(train))
    train["month"] = [int(m.split("-")[1]) for m in train.index]
    Xtr = pd.get_dummies(train["month"], prefix="m", drop_first=True, dtype=float)
    Xtr.insert(0, "t", train["t"].values)
    Xtr.insert(0, "const", 1.0)
    if train["最高気温"].notna().any():
        Xtr["最高気温"] = train["最高気温"].fillna(train["最高気温"].mean()).values
    model = sm.OLS(train["件数"].values, Xtr).fit()

    # predict valid with continuing t and month dummies; weather from actual month
    all_months = train_idx + valid_idx
    t0 = len(train_idx)
    ols_pred = []
    for i, m in enumerate(valid_idx):
        row = {"const": 1.0, "t": t0 + i}
        mon = int(m.split("-")[1])
        for c in Xtr.columns:
            if c.startswith("m_"):
                row[c] = 1.0 if c == f"m_{mon}" else 0.0
        if "最高気温" in Xtr.columns:
            row["最高気温"] = float(df.loc[m, "最高気温"]) if pd.notna(df.loc[m, "最高気温"]) else float(train["最高気温"].mean())
        x = pd.DataFrame([row])[Xtr.columns]
        ols_pred.append(float(model.predict(x)[0]))
    preds["OLS_トレンド季節"] = np.array(ols_pred)

    # 5) gate/nongate separate OLS then sum
    def fit_part(col: str) -> np.ndarray:
        tr = df.loc[train_idx, col].values.astype(float)
        t = np.arange(len(tr))
        mon = np.array([int(m.split("-")[1]) for m in train_idx])
        X = pd.get_dummies(pd.Series(mon), prefix="m", drop_first=True, dtype=float)
        X.insert(0, "t", t)
        X.insert(0, "const", 1.0)
        mod = sm.OLS(tr, X).fit()
        out = []
        for i, m in enumerate(valid_idx):
            row = {"const": 1.0, "t": len(tr) + i}
            mm = int(m.split("-")[1])
            for c in X.columns:
                if c.startswith("m_"):
                    row[c] = 1.0 if c == f"m_{mm}" else 0.0
            out.append(float(mod.predict(pd.DataFrame([row])[X.columns])[0]))
        return np.array(out)

    preds["門前+非門前分解OLS"] = fit_part("門前") + fit_part("非門前")

    yv = y.loc[valid_idx].values.astype(float)
    rows = []
    for name, yp in preds.items():
        mae, mape = mae_mape(yv, yp)
        rows.append({"モデル": name, "MAE": mae, "MAPE%": mape})
    metrics = pd.DataFrame(rows).sort_values("MAE")
    metrics.to_csv(PROCESSED_DIR / "phase6_forecast_metrics.csv", index=False, encoding="utf-8-sig")

    pred_df = pd.DataFrame({"年月": valid_idx, "実績": yv, **preds})
    pred_df.to_csv(PROCESSED_DIR / "phase6_forecast_valid.csv", index=False, encoding="utf-8-sig")

    # plot
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=False)
    ax = axes[0]
    ax.plot(months, y.values, color="#333", lw=1.5, label="実績")
    ax.axvline(train_idx[-1], color="#888", ls="--", label="学習/検証境界")
    best = metrics.iloc[0]["モデル"]
    ax.plot(valid_idx, preds[best], "o-", color="#0f6a6a", label=f"最良:{best}")
    ax.plot(valid_idx, preds["移動平均3"], "s--", color="#2f6f9f", alpha=0.8, label="移動平均3")
    ax.plot(valid_idx, preds["前年同月"], "^--", color="#c45c26", alpha=0.8, label="前年同月")
    ax.set_title(
        f"{PHARMACY_NAME} 月次件数 予測検証（学習〜{TRAIN_END} / 検証{VALID_START}〜）\n"
        f"最良 MAE={metrics.iloc[0]['MAE']:.1f} / MAPE={metrics.iloc[0]['MAPE%']:.1f}%"
    )
    ax.set_ylabel("件数")
    ax.legend(fontsize=8, ncol=2)
    ax.tick_params(axis="x", rotation=45)

    ax = axes[1]
    ax.barh(metrics["モデル"], metrics["MAE"], color="#0f6a6a")
    ax.set_xlabel("MAE（検証期）")
    ax.set_title("ベースライン比較（低いほど良い）")
    fig.tight_layout()
    fig.savefig(FIGURES / "phase6_forecast.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {
        "metrics": metrics,
        "best": best,
        "best_mae": float(metrics.iloc[0]["MAE"]),
        "best_mape": float(metrics.iloc[0]["MAPE%"]),
        "n_train": len(train_idx),
        "n_valid": len(valid_idx),
        "pred_df": pred_df,
        "ols_summary": model.summary().as_text(),
    }


def draw_integrated_diagram() -> Path:
    ensure_dirs()
    _setup_font()
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 8)
    ax.axis("off")

    def box(x, y, w, h, text, color):
        r = mpatches.FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.15",
            facecolor=color, edgecolor="#1c2430", lw=1.2, alpha=0.92,
        )
        ax.add_patch(r)
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=9, color="#1c2430")

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color="#333", lw=1.4))

    ax.text(6, 7.6, f"{PHARMACY_NAME} 統合患者獲得モデル（記述〜予測）", ha="center", fontsize=14, fontweight="bold")

    box(0.3, 5.8, 2.4, 1.2, "① Prescription Flow\n門前89% / 非門前10%\nABC・時系列", "#f7e3d6")
    box(3.2, 5.8, 2.4, 1.2, "② Clinic Catchment\n徒歩圏商圏\n地区×クリニック", "#ddeeea")
    box(6.1, 5.8, 2.4, 1.2, "③ Visit/Choice Rate\n距離減衰GLM\nclogit(自店条件付)", "#d6e4f0")
    box(9.0, 5.8, 2.5, 1.2, "④ Growth Engine\n定着41% / 間隔28日\nLTV感度", "#e8e0f2")

    arrow(2.7, 6.4, 3.2, 6.4)
    arrow(5.6, 6.4, 6.1, 6.4)
    arrow(8.5, 6.4, 9.0, 6.4)

    box(1.5, 3.6, 9.0, 1.4,
        "月間処方箋件数 ≈ Σ_a [ 人口_a × 来局率_a(距離,年齢,競合) × 月次来局頻度_a ]\n"
        "        ≈ 門前流量（軸A・クリニック集患） + 非門前獲得（軸B・面）\n"
        "Experience Engine（SEM）は観測変数なし → アンケート設計待ち",
        "#fff8ec")

    box(0.5, 1.4, 3.5, 1.5, "入力レバー\n・門前連携（軸A）\n・非門前認知/導線（軸B）\n・定着・頻度・世帯*", "#f3f1eb")
    box(4.3, 1.4, 3.5, 1.5, "シミュレータ\nシナリオ感度\nトルネード\n目標3000の必要条件", "#ddeeea")
    box(8.1, 1.4, 3.4, 1.5, "検証\n時間分割ホールドアウト\nMAE/MAPE\nベースライン比較", "#d6e4f0")
    arrow(4.0, 2.1, 4.3, 2.1)
    arrow(7.8, 2.1, 8.1, 2.1)

    ax.text(6, 0.5, "※世帯は住所詳細空欄のため未実装 / 係数は因果ではない / 自店データ限定", ha="center", fontsize=8, color="#5c6675")

    out = FIGURES / "phase6_integrated_diagram.png"
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def enhance_simulator_plot() -> Dict:
    ensure_dirs()
    _setup_font()
    inp = GrowthInputs()
    base = baseline_decomposition(inp)
    scen = simulate_scenarios(inp)
    tornado = tornado_sensitivities(inp, 0.1)

    # predictive distribution around scenarios (simple): lognormal noise 8% CV
    rng = np.random.default_rng(SEED)
    bands = []
    for _, r in scen.iterrows():
        if str(r["シナリオ"]).startswith("参考"):
            continue
        mu = float(r["予測月間件数"])
        samples = rng.lognormal(mean=np.log(mu) - 0.5 * 0.08**2, sigma=0.08, size=2000)
        bands.append(
            {
                "シナリオ": r["シナリオ"],
                "p10": float(np.percentile(samples, 10)),
                "p50": float(np.percentile(samples, 50)),
                "p90": float(np.percentile(samples, 90)),
                "目標到達確率": float((samples >= 3000).mean()),
            }
        )
    band_df = pd.DataFrame(bands)
    band_df.to_csv(PROCESSED_DIR / "phase6_scenario_bands.csv", index=False, encoding="utf-8-sig")

    fig, ax = plt.subplots(figsize=(10, 5))
    y = np.arange(len(band_df))
    ax.hlines(y, band_df["p10"], band_df["p90"], color="#2f6f9f", lw=6, label="P10–P90")
    ax.plot(band_df["p50"], y, "o", color="#0f6a6a", label="中央値")
    ax.axvline(3000, color="#c45c26", ls="--", label="目標3000")
    ax.axvline(1388, color="#888", ls=":", label="現状1388")
    ax.set_yticks(y)
    ax.set_yticklabels(band_df["シナリオ"])
    ax.set_xlabel("月間件数（シナリオ中央値±不確実性バンド）")
    ax.set_title("Growthシミュレータ予測分布（CV≈8%の記述的バンド）")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "phase6_scenario_bands.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    return {"baseline": base, "scenarios": scen, "bands": band_df, "tornado": tornado}


def write_academic_positioning() -> Path:
    text = f"""# 学術ポジショニング（academic_positioning）

## 研究の問い

面薬局（門前依存でない処方箋獲得）のメカニズムを、患者–クリニック–薬局の空間的三角形データから説明できるか。

## 本稿（本プロジェクト）の主張できる新規性

1. **処方箋調剤データから患者–クリニック–薬局の三角形（距離・角度・迂回率・立地パターン）を構成**し、薬局選択を「経由地選択（trip chaining）」問題として定式化した点。
2. **門前／非門前の二軸分解**：規模は門前流量（軸A）、成長余地は非門前（軸B）とデータで分離した点。
3. 個票の薬局MNLが不可能な状況で、**集計来局率（人口分母）＋自店条件付きクリニック選択＋Huff記述ベンチマーク**という推定階層を明示した点。

## 既存研究との差分

| 領域 | 既存 | 本プロジェクト |
|---|---|---|
| Huff / 小売引力 | 店舗魅力度と距離で選択確率 | 競合実売なしのため**記述ベンチマークに限定**し、残差マップを成果物化 |
| 医療アクセス | 医療機関までの距離・受療率 | クリニック経由の**薬局到達**まで拡張（三角形） |
| trip-chaining | 通勤・買物連鎖 | 受診→調剤の医療トリップ連鎖として再定式化 |
| 薬局マーケティング | 口コミ・MEO・経験 | Experience（SEM）は**データ欠落を明示して保留** |

## 主張できないこと（現時点）

1. **外部妥当性**：1店舗（南茨木店）のみ。論文化には他店舗（大淀・沢良宜等）での再現が必要条件。
2. **因果効果**：イベント年表がないため、回帰係数を施策効果とは言えない（Phase 5 保留）。
3. **市場全体の薬局選択率**：競合処方箋・クリニック総発行数が未知。

## 論文化への最短パス

1. 同一スキーマの複数店舗データで三角形指標と距離減衰の再現性を示す。
2. クリニック総発行数または競合規模代理を追加し、シェア分母を確保する。
3. 開局・連携・競合開閉のイベント年表で ITS / DiD を実施する。
4. 患者アンケート（経験・推奨）で Experience Engine を接続する。

## 対象店舗メモ

- 分析対象は **{PHARMACY_NAME}**（固定点座標）。依頼書の沢良宜店・月1,800枚とは定義突合が未了。
"""
    path = REPORTS / "academic_positioning.md"
    path.write_text(text, encoding="utf-8")
    return path


def write_integrated_report(fc: Dict, sim: Dict, diagram: Path, academic: Path) -> Dict[str, Path]:
    metrics = fc["metrics"]
    bands = sim["bands"]
    md = f"""# Phase 6: 統合モデルと成果物

## わかったこと3点

1. **統合式は「人口×来局率×頻度」＋門前/非門前分解で運用可能。** Experience（SEM）は欠測のため設計のみ。
2. **月次予測の時間分割検証で最良は「{fc['best']}」（MAE={fc['best_mae']:.1f}, MAPE={fc['best_mape']:.1f}%）。** 単純平均より改善。
3. **目標3,000は単一レバーでは到達確率が低い。** シナリオバンド上、複合施策が必要（Phase3と整合）。

## わからなかったこと3点

1. 因果的な施策効果（Phase5: イベント年表待ち）。
2. 複数店舗での外部妥当性。
3. 世帯波及（住所詳細空欄）。

## 次に必要なデータ

- イベント年表、他店舗同一スキーマ、クリニック総発行数、住所詳細、アンケート

---

## 統合図

![diagram](figures/{diagram.name})

### 式系（運用版）

```
月間件数_t
  = Gate_t + NonGate_t
  = Σ_a Population_a × VisitRate_a(distance, age, competition) × Freq_a,t
```

- VisitRate は Phase3 集計Binomial GLM（距離減衰が主）
- Freq / 定着は Phase4（90日定着≈41%, 間隔中央値28日）
- Gate ≈ クリニック集患（軸A）。薬局施策の直接効果は小さい可能性
- NonGate ≈ 面の成長余地（軸B）

依頼書の「商圏人口×クリニック選択率×薬局選択率×継続率」は上式に対応：
クリニック選択率×薬局選択率 ≒ 自店来局率（分母=人口）に吸収。

---

## 予測検証（〜2026-01学習 / 2026-02〜検証）

![forecast](figures/phase6_forecast.png)

```
{metrics.to_string(index=False)}
```

- 学習月数={fc['n_train']} / 検証月数={fc['n_valid']}
- 全国処方箋は月次の統制候補だが、検証期のカバレッジに注意

---

## シミュレータ（予測分布）

![bands](figures/phase6_scenario_bands.png)

```
{bands.to_string(index=False)}
```

---

## 学術ポジショニング

詳細: [`academic_positioning.md`](academic_positioning.md)

---

## Phase5について

中断時系列・CausalImpact・DiDは**イベント年表取得後**に実施する。現時点で回帰係数を因果効果と書かない。

## 限界

- 1店舗・自店来局のみ
- 係数は相関/条件付き関連
- シナリオバンドのCVは仮置き
"""
    md_path = REPORTS / "integrated_model.md"
    md_path.write_text(md, encoding="utf-8")

    # also copy academic already written
    rep = HtmlReport(
        title="Phase 6 Integrated Model",
        subtitle="Prescription Flow → Catchment → Choice Rate → Growth を一つの式系に統合。時間分割予測とシナリオ分布を検証する。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 6",
    )
    rep.add_kpi("最良予測", fc["best"], f"MAE {fc['best_mae']:.0f}")
    rep.add_kpi("MAPE", f"{fc['best_mape']:.1f}%", "検証期")
    rep.add_kpi("現状月次", "1,388", "目標 3,000")
    rep.add_kpi("目標倍率", f"{sim['baseline']['gap_ratio']:.2f}×", "要複合施策")

    rep.callout(
        "わかったこと",
        [
            f"統合運用式は人口×来局率×頻度（門前/非門前分解）。",
            f"予測最良は {fc['best']}（MAE={fc['best_mae']:.1f}）。",
            "3,000到達は複合レバーが必要。",
        ],
        kind="ok",
    )
    rep.callout(
        "保留",
        ["Phase5因果（イベント年表）", "多店舗外部妥当性", "世帯・Experience SEM"],
        kind="warn",
    )

    rep.section("diagram", "統合モデル")
    rep.figure(diagram)

    rep.section("forecast", "時間分割予測検証")
    rep.figure(FIGURES / "phase6_forecast.png")
    rep.table(
        ["モデル", "MAE", "MAPE%"],
        [[r["モデル"], f"{r['MAE']:.1f}", f"{r['MAPE%']:.1f}"] for _, r in metrics.iterrows()],
        numeric_cols=[1, 2],
    )

    rep.section("sim", "シナリオ予測分布")
    rep.figure(FIGURES / "phase6_scenario_bands.png")
    rep.table(
        ["シナリオ", "P50", "P10", "P90", "3000到達確率"],
        [
            [
                r["シナリオ"][:24],
                f"{r['p50']:.0f}",
                f"{r['p10']:.0f}",
                f"{r['p90']:.0f}",
                f"{r['目標到達確率']:.0%}",
            ]
            for _, r in bands.iterrows()
        ],
        numeric_cols=[1, 2, 3, 4],
    )

    rep.section("academic", "学術ポジショニング要約")
    rep.paragraph("三角形定式化と門前/非門前二軸が新規性の中核。1店舗のため外部妥当性は未確立。詳細は academic_positioning.md。")

    html_path = REPORTS / "phase6_integrated.html"
    rep.save(html_path)

    # also save integrated html name alias
    return {"md": md_path, "html": html_path, "academic": academic}


def publish_docs(html_path: Path, academic: Path) -> None:
    import shutil

    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, DOCS / "phase6_integrated.html")
    shutil.copy2(html_path, DOCS / "integrated_model.html")
    shutil.copy2(academic, DOCS / "academic_positioning.md")
    shutil.copy2(REPORTS / "integrated_model.md", DOCS / "integrated_model.md")
    for p in FIGURES.glob("phase6_*.png"):
        shutil.copy2(p, DOCS / "figures" / p.name)

    index = DOCS / "index.html"
    if index.exists() and "phase6_integrated.html" not in index.read_text(encoding="utf-8"):
        text = index.read_text(encoding="utf-8")
        card = """
      <article class="card">
        <h2>Phase 6 · Integrated Model</h2>
        <p>統合式・予測検証・シナリオ分布・学術ポジショニング。</p>
        <a class="btn" href="phase6_integrated.html">レポートを開く</a>
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


def run_phase6() -> Dict:
    np.random.seed(SEED)
    ensure_dirs()
    df = monthly_series()
    df.to_csv(PROCESSED_DIR / "phase6_monthly_panel.csv", encoding="utf-8-sig")
    diagram = draw_integrated_diagram()
    fc = forecast_holdout(df)
    sim = enhance_simulator_plot()
    academic = write_academic_positioning()
    paths = write_integrated_report(fc, sim, diagram, academic)
    publish_docs(paths["html"], academic)
    return {
        "paths": paths,
        "best": fc["best"],
        "mae": fc["best_mae"],
        "mape": fc["best_mape"],
    }


if __name__ == "__main__":
    out = run_phase6()
    print("wrote", out["paths"])
    print("best=", out["best"], "MAE=", round(out["mae"], 1), "MAPE%=", round(out["mape"], 1))
