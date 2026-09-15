"""Phase 5: イベント年表待ちのプレースホルダ HTML。"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.io import PHARMACY_NAME, ROOT, ensure_dirs
from src.viz.html_report import HtmlReport

REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"


def build_phase5_html() -> Path:
    ensure_dirs()
    DOCS.mkdir(parents=True, exist_ok=True)

    rep = HtmlReport(
        title="Phase 5 Causal Impact",
        subtitle="施策・イベントの因果効果推定。現状はイベント年表・介入日が未整備のため分析を保留しています。",
        pharmacy=PHARMACY_NAME,
        period="データ不足 · 保留中",
        eyebrow="Kutsuki DataBank / Phase 5",
        active_phase=5,
    )
    rep.add_kpi("ステータス", "データ不足", "イベント年表待ち")
    rep.add_kpi("予定手法", "ITS / DiD", "CausalImpact 想定")
    rep.add_kpi("必要データ", "介入日", "開局・施策・競合変化")
    rep.add_kpi("Phase 6", "先行実施", "統合モデルは公開済")

    rep.callout(
        "現在の状況",
        [
            "因果推定（中断時系列・差分の差分・CausalImpact）に必要なイベント年表が未入手です。",
            "開局・改装・キャンペーン・近隣競合の開閉・価格変更などの介入日が揃うまで本 Phase は実行しません。",
            "回帰係数や相関を因果効果としては解釈しない方針を維持します。",
        ],
        kind="warn",
    )

    from html import escape

    from src.viz.figure_explains import PHASE5_PLANNED_FIGURES

    rep.section("planned", "データが揃ったときに出す予定の図")
    for title, explain in PHASE5_PLANNED_FIGURES:
        rep.add_html(
            f'<div class="card span-12" style="margin-bottom:12px">'
            f"<h3>{escape(title)}</h3>"
            f'<div class="fig-explain"><strong>この図の読み方（予定）</strong>{escape(explain)}</div>'
            f"</div>"
        )

    rep.section("needed", "再開に必要なもの")
    rep.paragraph(
        "少なくとも「日付・イベント種別・対象範囲（自店/競合/地域）・備考」の年表 CSV が必要です。"
        "可能であれば施策強度（広告費・チラシ枚数など）も併記してください。"
    )
    rep.table(
        ["項目", "例", "必須"],
        [
            ["介入日", "2025-04-01", "必須"],
            ["イベント種別", "近隣クリニック新規開業", "必須"],
            ["対象", "競合 / 自店施策", "必須"],
            ["強度・メモ", "チラシ2万部", "任意"],
        ],
    )

    rep.section("next", "揃ったあとの予定")
    rep.paragraph(
        "月次処方箋枚数（門前/非門前分解）をアウトカムに、ITS または Bayesian structural time-series "
        "（CausalImpact）で介入前後の反実仮想を推定します。並行して Phase 6 の予測ベースラインと比較します。"
    )

    html_path = REPORTS / "phase5_causal.html"
    rep.save(html_path)
    shutil.copy2(html_path, DOCS / "phase5_causal.html")
    return html_path


if __name__ == "__main__":
    print(build_phase5_html())
