"""Phase 1 レポートを HTML でも出力する。"""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd

from src.axis import AXIS_OTHER, AXIS_TOP2, HASEGAWA_ID, HIRAYAMA_ID, TOP2_IDS
from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, ensure_dirs, FIGURES_DIR, REPORTS_DIR, read_csv
from src.kpi import RECENT_MONTHS, current_level, save_page_summary
from src.viz.figure_explains import SANKY_EXPLAIN
from src.viz.html_report import HtmlReport

FIGURES = FIGURES_DIR
REPORTS = REPORTS_DIR
TOP_TARGETS = 10


def _short_name(name: str, width: int = 22) -> str:
    return str(name)[:width]


def _short_specialty(value: object, limit: int = 18) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    kept: list = []
    for part in text.split("・"):
        if len("・".join(kept + [part])) > limit:
            break
        kept.append(part)
    return ("・".join(kept) or text[:limit]) + "ほか"


def _is_internal(spec: object) -> bool:
    return "内科" in str(spec)


def build_phase1_html() -> Path:
    ensure_dirs()
    abc = pd.read_csv(PROCESSED_DIR / "abc_clinics_全体.csv")
    other_path = PROCESSED_DIR / f"abc_clinics_{AXIS_OTHER}.csv"
    if not other_path.exists():
        other_path = PROCESSED_DIR / "abc_clinics_非門前型.csv"
    abc_ng = pd.read_csv(other_path)
    port = pd.read_csv(PROCESSED_DIR / "patient_portfolio.csv")
    monthly = pd.read_csv(PROCESSED_DIR / "monthly_by_gate.csv", index_col=0)
    level = current_level(monthly.sum(axis=1))

    vt = read_csv("visit_triangle")
    vt["受診日"] = pd.to_datetime(vt["受診日"])
    recent = vt.loc[vt["受診日"].dt.to_period("M").isin(pd.PeriodIndex(monthly.index[-RECENT_MONTHS:], freq="M"))]
    recent_n = max(len(recent), 1)
    def recent_of(cid: str) -> float:
        return float((recent["クリニックID"].astype(str) == cid).sum()) / RECENT_MONTHS

    hase = recent_of(HASEGAWA_ID)
    hira = recent_of(HIRAYAMA_ID)
    other_m = float((~recent["クリニックID"].astype(str).isin(TOP2_IDS)).sum()) / RECENT_MONTHS
    top2_m = hase + hira
    intern_m = float(recent["診療科"].astype(str).str.contains("内科", na=False).sum()) / RECENT_MONTHS

    total = int(len(vt))
    top2 = abc.head(2)
    top2_share = float(top2["構成比"].sum())
    top2_names = "・".join(_short_name(n, 12) for n in top2["クリニック名"])
    n_other_clinics = int(abc.loc[~abc["クリニックID"].astype(str).isin(TOP2_IDS), "クリニックID"].nunique()) if "クリニックID" in abc.columns else len(abc_ng)

    intern_targets = abc_ng.copy()
    intern_targets["内科"] = intern_targets["診療科"].map(_is_internal)
    intern_targets = intern_targets.sort_values(["内科", "件数"], ascending=[False, False])
    named = intern_targets.head(3)
    action_names = "、".join(
        f"{_short_name(r['クリニック名'], 14)}（{int(r['件数'] / max(level.n_months, 1)):.0f}枚/月）"
        if False else f"{_short_name(r['クリニック名'], 14)}（{int(r['件数']):,}枚）"
        for _, r in named.iterrows()
    )
    # 月平均に直す（期間全体件数 / 月数）
    action_bits = []
    for _, r in named.iterrows():
        per_m = int(r["件数"]) / max(level.n_months, 1)
        km = r["クリニック→薬局_直線km"] if pd.notna(r.get("クリニック→薬局_直線km")) else None
        dist = f"・{km*1000:.0f}m" if km is not None else ""
        action_bits.append(f"{_short_name(r['クリニック名'], 16)}（{per_m:.0f}枚/月{dist}）")
    action_line = "内科で処方箋が多い3院へ挨拶に行く。\n" + "、".join(action_bits)

    n_patients = len(port)
    other_col = AXIS_OTHER if AXIS_OTHER in monthly.columns else ("非門前型" if "非門前型" in monthly.columns else monthly.columns[-1])
    recent_other = float(monthly[other_col].iloc[-RECENT_MONTHS:].mean())

    rep = HtmlReport(
        title="処方箋はどこから来ているか",
        subtitle="どのクリニックからの処方箋が多く、どれくらい偏っているかを見ます。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 1",
        active_phase=1,
    )
    hase_name = _short_name(str(abc.loc[abc["クリニックID"].astype(str).eq(HASEGAWA_ID), "クリニック名"].iloc[0]), 14) if (abc["クリニックID"].astype(str) == HASEGAWA_ID).any() else "はせがわ耳鼻科"
    hira_name = _short_name(str(abc.loc[abc["クリニックID"].astype(str).eq(HIRAYAMA_ID), "クリニック名"].iloc[0]), 14) if (abc["クリニックID"].astype(str) == HIRAYAMA_ID).any() else "平山皮フ科"

    rep.add_kpi(hase_name, f"{hase:,.0f}枚/月", f"{hase / level.recent_mean:.0%}",
                compare=f"{level.period_label}の平均", tone="caution")
    rep.add_kpi(hira_name, f"{hira:,.0f}枚/月", f"{hira / level.recent_mean:.0%}",
                compare=f"{level.period_label}の平均", tone="caution")
    rep.add_kpi("それ以外の医院", f"{other_m:,.0f}枚/月", f"{other_m / level.recent_mean:.0%}",
                compare=f"{n_other_clinics}院、1院あたり平均 {other_m / max(n_other_clinics, 1):.1f}枚/月",
                tone="neutral")
    rep.add_kpi("内科からの処方箋", f"{intern_m:,.0f}枚/月", f"{intern_m / level.recent_mean:.0%}",
                compare="長く通う患者の入口", tone="chance")

    drop10 = hase * 0.1
    rep.takeaway(
        finding=f"処方箋の{top2_m / level.recent_mean:.0%}は、はせがわ耳鼻科と平山皮フ科の2院から来ている。",
        judgment=f"どちらかが1割減ると、店全体の処方箋が約{drop10 / level.recent_mean:.0%}減る。",
        action=action_line,
        measure=f"来月の「それ以外の医院」が {recent_other:,.0f}枚 → {recent_other + 38:,.0f}枚以上。3院それぞれの月の枚数が増えているか。",
        link="#targets",
        tone="bad",
    )

    rep.section("monthly", "月別の推移")
    rep.chart(
        "p1-monthly",
        "monthly",
        fallback=FIGURES / "phase1_monthly_plain.png",
        point=f"橙が隣の2院、青がそれ以外です。{level.period_label}は2院で月{top2_m:,.0f}枚、それ以外は月{other_m:,.0f}枚です。",
        explain="橙が隣の2院（はせがわ・平山）、青がそれ以外の医院、灰色が不明の月別の処方箋枚数（積み上げ）です。点線は目標の枚数です。",
    )

    rep.section("clinics", "クリニック別の処方箋")
    rep.chart(
        "p1-clinics",
        "clinic_rank",
        fallback=FIGURES / "phase1_top_clinics.png",
        point=f"上位2院だけで処方箋全体の{top2_share:.0%}を占めています。",
        explain="期間中の処方箋が多いクリニック上位10件です。棒の右の割合は、全処方箋に対する割合です。",
    )

    intern_targets["月平均"] = intern_targets["件数"] / max(level.n_months, 1)
    intern_targets["内科ラベル"] = intern_targets["内科"].map({True: "内科", False: "—"})
    table_src = intern_targets.head(TOP_TARGETS)
    rep.section("targets", "関係づくりの候補（それ以外の医院）")
    rep.paragraph("すでに自店への処方箋がある医院のうち、内科を上に並べました。")
    rep.table(
        ["クリニック", "診療科", "処方箋（枚）", "月あたり", "薬局からの距離（km）"],
        [
            [
                _short_name(r["クリニック名"]),
                _short_specialty(r["診療科"]) if pd.notna(r["診療科"]) else "-",
                f"{int(r['件数']):,}",
                f"{r['月平均']:.0f}",
                f"{r['クリニック→薬局_直線km']:.1f}" if pd.notna(r["クリニック→薬局_直線km"]) else "-",
            ]
            for _, r in table_src.iterrows()
        ],
        numeric_cols=[2, 3, 4],
    )

    with rep.expert_details("専門家向けの詳細（ABC分析・時系列・外生要因・患者ポートフォリオ）"):
        rep.section("abc", "クリニック別ABC（パレート）")
        rep.figure(FIGURES / "phase1_abc_pareto.png", "累積構成比。最大シェアは隣の2院・それ以外それぞれの中での割合")
        rep.section("ts", "時系列")
        rep.chart("p1-ts", "monthly", {"kind": "line"}, fallback=FIGURES / "phase1_timeseries.png", caption="月次・季節パターン")
        rep.section("exo", "外生要因（相関）")
        rep.figure(FIGURES / "phase1_exogenous.png", "花粉は0埋めせず欠測のまま表示")
        rep.section("portfolio", "患者ポートフォリオ")
        rep.figure(FIGURES / "phase1_portfolio.png", "頻度×利用クリニック数など")
        rep.section("sankey", "流動 Sankey")
        rep.add_html(
            '<div class="card span-12"><p>'
            '<a href="figures/phase1_sankey.html" target="_blank">全体 Sankey を開く</a>'
            "</p>"
            f'<div class="fig-explain"><strong>この図の読み方</strong>{escape(SANKY_EXPLAIN)}</div>'
            "</div>"
        )

    out = REPORTS / "phase1_flow.html"
    rep.save(out)

    save_page_summary("p1", {
        "gate_share": top2_m / level.recent_mean,
        "nongate_share": other_m / level.recent_mean,
        "top2_share": top2_m / level.recent_mean,
        "top2_names": top2_names,
        "n_nongate_clinics": n_other_clinics,
        "hase_monthly": hase,
        "hira_monthly": hira,
        "other_monthly": other_m,
        "intern_monthly": intern_m,
        "recent_mean": level.recent_mean,
        "period_label": level.period_label,
        "multi_patients": int(port["面利用候補"].sum()) if "面利用候補" in port.columns else 0,
        "multi_share": float(port["面利用候補"].mean()) if "面利用候補" in port.columns else 0,
        "conclusion": f"隣の2院（はせがわ・平山）で処方箋の{top2_m / level.recent_mean:.0%}。残り{n_other_clinics}院から少しずつ。",
        "gate_def": "隣の2院（はせがわ・平山）",
        "actions": [
            {
                "what": "、".join(_short_name(r["クリニック名"], 14) for _, r in named.iterrows()) + "へ挨拶",
                "who": "薬局長",
                "measure": f"それ以外の医院 {recent_other:,.0f}→{recent_other + 38:,.0f}枚/月",
                "page": "phase1_flow.html#targets",
            }
        ],
    })
    return out


if __name__ == "__main__":
    p = build_phase1_html()
    print("wrote", p)
