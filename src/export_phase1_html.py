"""Phase 1 レポートを HTML でも出力する。"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd

from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, ensure_dirs
from src.kpi import RECENT_MONTHS, current_level, save_page_summary
from src.viz.figure_explains import SANKY_EXPLAIN
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
TOP_TARGETS = 10


def _gate_label(flag: object) -> str:
    return "門前" if str(flag) == "True" else "門前以外"


def _short_name(name: str, width: int = 22) -> str:
    return str(name)[:width]


def build_phase1_html() -> Path:
    ensure_dirs()
    abc = pd.read_csv(PROCESSED_DIR / "abc_clinics_全体.csv")
    abc_g = pd.read_csv(PROCESSED_DIR / "abc_clinics_門前型.csv")
    abc_ng = pd.read_csv(PROCESSED_DIR / "abc_clinics_非門前型.csv")
    port = pd.read_csv(PROCESSED_DIR / "patient_portfolio.csv")
    gate_summary = pd.read_csv(PROCESSED_DIR / "gate_stratified_summary.csv").set_index("区分")

    total = int(gate_summary.loc["全体", "受診件数"])
    gate_n = int(gate_summary.loc["門前型", "受診件数"])
    nongate_n = int(gate_summary.loc["非門前型", "受診件数"])
    gate_share = gate_n / total
    nongate_share = nongate_n / total
    n_nongate_clinics = len(abc_ng)

    top2 = abc.head(2)
    top2_share = float(top2["構成比"].sum())
    top2_names = "・".join(_short_name(n, 12) for n in top2["クリニック名"])
    top1_share_all = float(abc.iloc[0]["構成比"])
    top1_share_gate = float(abc_g.iloc[0]["構成比"])

    n_patients = len(port)
    multi = int(port["面利用候補"].sum())

    n80 = min(int((abc["累積構成比"] <= 0.8).sum()) + 1, len(abc))
    n80_g = min(int((abc_g["累積構成比"] <= 0.8).sum()) + 1, len(abc_g))
    n80_ng = min(int((abc_ng["累積構成比"] <= 0.8).sum()) + 1, len(abc_ng))

    targets = abc_ng.head(TOP_TARGETS)
    monthly = pd.read_csv(PROCESSED_DIR / "monthly_by_gate.csv", index_col=0)
    level = current_level(monthly.sum(axis=1))
    recent_nongate = float(monthly["非門前型"].iloc[-RECENT_MONTHS:].mean())

    rep = HtmlReport(
        title="処方箋はどこから来ているか",
        subtitle="どのクリニックからの処方箋が多く、どれくらい偏っているかを見ます。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 1",
        active_phase=1,
    )
    rep.add_kpi("門前からの処方箋", f"{gate_share:.0%}", f"{gate_n:,}枚 / 全{total:,}枚",
                compare=f"門前以外は {nongate_share:.0%}。門前への依存が大きい", tone="bad")
    rep.add_kpi("門前以外からの処方箋", f"{nongate_share:.0%}", f"{nongate_n:,}枚",
                compare=f"{n_nongate_clinics}施設に分散（1施設あたり平均 {nongate_n / n_nongate_clinics:.0f}枚）",
                tone="neutral")
    rep.add_kpi("上位2院の割合", f"{top2_share:.0%}", top2_names,
                compare=f"3位以下の全クリニックを合わせても {1 - top2_share:.0%}", tone="bad")
    rep.add_kpi("2か所以上のクリニックから来た患者", f"{multi:,}人",
                compare=f"全患者 {n_patients:,}人の {multi / n_patients:.0%}", tone="neutral")

    rep.takeaway(
        finding=(
            f"処方箋の約{gate_share:.0%}が門前、特に上位2院（{top2_names}）に{top2_share:.0%}が集中しています。"
            f"門前以外は{n_nongate_clinics}か所のクリニックに少しずつ分散しています。"
        ),
        judgment="2院への依存度が高く、どちらかの患者数が減ると店全体に直結します。",
        action=f"門前以外のうち処方箋の多いクリニック上位{TOP_TARGETS}件を優先して、関係づくりを進めます。",
    )

    rep.section("monthly", "月別の推移")
    rep.figure(
        FIGURES / "phase1_monthly_plain.png",
        point=(
            f"毎月の処方箋の大半は門前で、門前以外は月{recent_nongate:,.0f}枚ほど"
            f"（{level.period_label}の平均）にとどまっています。"
        ),
        explain="橙が門前、青が門前以外の月別の処方箋枚数です。線の右端の数字が直近月の枚数です。",
    )

    rep.section("clinics", "クリニック別の処方箋")
    rep.figure(
        FIGURES / "phase1_top_clinics.png",
        point=f"上位2院だけで処方箋全体の{top2_share:.0%}を占めています。",
        explain="期間中の処方箋が多いクリニック上位10件です。棒の右の割合は、全処方箋に対する割合です。",
    )

    rep.section("targets", f"関係づくりの候補（門前以外の上位{TOP_TARGETS}件）")
    rep.paragraph("門前以外のクリニックのうち、すでに自店への処方箋が多い順に並べました。")
    rep.table(
        ["クリニック", "診療科", "処方箋（枚）", "門前以外の中での割合", "薬局からの距離（km）"],
        [
            [
                _short_name(r["クリニック名"]),
                str(r["診療科"])[:18] if pd.notna(r["診療科"]) else "-",
                f"{int(r['件数']):,}",
                f"{r['構成比']:.1%}",
                f"{r['クリニック→薬局_直線km']:.1f}" if pd.notna(r["クリニック→薬局_直線km"]) else "-",
            ]
            for _, r in targets.iterrows()
        ],
        numeric_cols=[2, 3, 4],
    )

    with rep.expert_details("専門家向けの詳細（ABC分析・時系列・外生要因・患者ポートフォリオ）"):
        rep.section("abc", "クリニック別ABC（パレート）")
        rep.figure(FIGURES / "phase1_abc_pareto.png", "累積構成比（パレート）。最大シェアは門前・門前以外それぞれの中での割合")
        rep.table(
            ["クリニック", "処方箋（枚）", "全体に対する割合", "薬局からの距離（km）", "区分（0.3km基準）"],
            [
                [
                    _short_name(r["クリニック名"]),
                    int(r["件数"]),
                    f"{r['構成比']:.1%}",
                    f"{r['クリニック→薬局_直線km']:.3f}",
                    _gate_label(r["門前_0.3km"]),
                ]
                for _, r in abc.head(8).iterrows()
            ],
            numeric_cols=[1, 2, 3],
        )
        rep.paragraph(
            f"最大シェア: 全体に対する割合 {top1_share_all:.1%}（KPIの分母）／門前の中での割合 {top1_share_gate:.1%}（パレート図の分母）。"
        )
        rep.paragraph(f"80%到達施設数: 全体 {n80} ／ 門前 {n80_g} ／ 門前以外 {n80_ng}。")

        rep.section("ts", "時系列")
        rep.figure(FIGURES / "phase1_timeseries.png", "月次・季節パターン")

        rep.section("exo", "外生要因（相関）")
        rep.figure(FIGURES / "phase1_exogenous.png", "花粉は0埋めせず欠測のまま表示")

        rep.section("portfolio", "患者ポートフォリオ")
        rep.figure(FIGURES / "phase1_portfolio.png", "頻度×利用クリニック数など")

        rep.section("sankey", "流動 Sankey")
        rep.add_html(
            '<div class="card span-12"><p>'
            '<a href="figures/phase1_sankey.html" target="_blank">全体 Sankey を開く</a> ／ '
            '<a href="figures/phase1_sankey_nongate.html" target="_blank">門前以外のみ Sankey</a>'
            "</p>"
            f'<div class="fig-explain"><strong>この図の読み方</strong>{escape(SANKY_EXPLAIN)}</div>'
            "</div>"
        )
        rep.callout(
            "データの扱いと限界",
            [
                "門前＝立地パターン「門前型」、門前以外＝患者近接型・経由型・遠隔型。",
                "花粉欠損は0埋めしていません。新患フラグは使用していません。",
                "クリニックの総発行処方箋数がないため、各クリニックに対する自店シェアは分かりません。",
            ],
            kind="warn",
        )

    out = REPORTS / "phase1_flow.html"
    rep.save(out)

    save_page_summary("p1", {
        "gate_share": gate_share,
        "nongate_share": nongate_share,
        "top2_share": top2_share,
        "top2_names": top2_names,
        "n_nongate_clinics": n_nongate_clinics,
        "multi_patients": multi,
        "multi_share": multi / n_patients,
        "conclusion": f"処方箋の{gate_share:.0%}が門前。上位2院だけで{top2_share:.0%}を占めています。",
    })
    return out


if __name__ == "__main__":
    p = build_phase1_html()
    print("wrote", p)
