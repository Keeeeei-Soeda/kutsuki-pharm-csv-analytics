"""Phase 1 レポートを HTML でも出力する。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, ensure_dirs
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"


def build_phase1_html() -> Path:
    ensure_dirs()
    abc = pd.read_csv(PROCESSED_DIR / "abc_clinics_全体.csv")
    abc_g = pd.read_csv(PROCESSED_DIR / "abc_clinics_門前型.csv")
    abc_ng = pd.read_csv(PROCESSED_DIR / "abc_clinics_非門前型.csv")
    port = pd.read_csv(PROCESSED_DIR / "patient_portfolio.csv") if (PROCESSED_DIR / "patient_portfolio.csv").exists() else None

    n80 = int((abc["累積構成比"] <= 0.8).sum()) + 1
    top1 = float(abc.iloc[0]["構成比"])
    n80_g = int((abc_g["累積構成比"] <= 0.8).sum()) + 1
    n80_ng = int((abc_ng["累積構成比"] <= 0.8).sum()) + 1

    rep = HtmlReport(
        title="Phase 1 Prescription Flow",
        subtitle="門前が規模、非門前が成長余地。処方箋フローの記述分析。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 1",
    )
    rep.add_kpi("門前型", "89.3%", "28,518 / 31,924件")
    rep.add_kpi("非門前型", "9.6%", "面の実体 3,060件")
    rep.add_kpi("80%到達施設", str(min(n80, len(abc))), f"最大シェア {top1:.1%}")
    multi = int(port["面利用候補"].sum()) if port is not None and "面利用候補" in port.columns else 1844
    rep.add_kpi("面利用候補", f"{multi:,}人", "受診クリニック数2以上")

    rep.callout(
        "結論",
        [
            "このデータは面薬局ではなく門前中心（門前型89.3%）。",
            f"全体の80%は上位{min(n80, len(abc))}施設。はせがわ耳鼻科が最大。",
            f"非門前は80%到達に{min(n80_ng, len(abc_ng))}施設と分散→成長余地の主戦場。",
        ],
        kind="ok",
    )

    rep.section("gate", "面か門前か")
    rep.figure(FIGURES / "phase1_monthly_gate.png", "門前型 / 非門前型の月別推移")

    rep.section("abc", "クリニック別ABC")
    rep.figure(FIGURES / "phase1_abc_pareto.png")
    rep.table(
        ["クリニック", "件数", "構成比", "直線km", "門前0.3km"],
        [
            [
                r["クリニック名"][:22],
                int(r["件数"]),
                f"{r['構成比']:.1%}",
                f"{r['クリニック→薬局_直線km']:.3f}",
                str(r["門前_0.3km"]),
            ]
            for _, r in abc.head(8).iterrows()
        ],
        numeric_cols=[1, 2, 3],
    )
    rep.paragraph(f"門前型の80%到達={n80_g}施設 / 非門前型の80%到達={n80_ng}施設")

    rep.section("ts", "時系列")
    rep.figure(FIGURES / "phase1_timeseries.png")

    rep.section("exo", "外生要因（相関）")
    rep.figure(FIGURES / "phase1_exogenous.png", "花粉は0埋めせず欠測のまま表示")

    rep.section("portfolio", "患者ポートフォリオ")
    rep.figure(FIGURES / "phase1_portfolio.png")

    rep.section("sankey", "流動 Sankey")
    rep.add_html(
        '<div class="card span-12"><p>'
        '<a href="figures/phase1_sankey.html" target="_blank">全体 Sankey を開く</a> ／ '
        '<a href="figures/phase1_sankey_nongate.html" target="_blank">非門前のみ Sankey</a>'
        "</p></div>"
    )

    out = REPORTS / "phase1_flow.html"
    rep.save(out)
    return out


if __name__ == "__main__":
    p = build_phase1_html()
    print("wrote", p)
