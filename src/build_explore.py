"""データ探索ページ ``docs/explore.html`` を生成する。"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.io import PHARMACY_NAME, ROOT, ensure_dirs, FIGURES_DIR, REPORTS_DIR, DOCS_DIR
from src.viz.html_report import HtmlReport
from src.viz.sidebar import PERIOD_LABEL

FIGURES = FIGURES_DIR
REPORTS = REPORTS_DIR
DOCS = DOCS_DIR


def build_explore() -> Path:
    ensure_dirs()
    (DOCS / "js").mkdir(parents=True, exist_ok=True)
    rep = HtmlReport(
        title="データを絞り込んで見る",
        subtitle="期間や区分を変えると、下の数字とグラフが連動します。Phase 3〜6 の見込みの数字は、ここで絞り込んでも変わりません。",
        pharmacy=PHARMACY_NAME,
        period=PERIOD_LABEL,
        eyebrow="Kutsuki DataBank / データ探索",
        nav_key="explore",
        page_kind="explore",
    )
    rep.takeaway(
        finding="期間・医院・診療科を絞ると、枚数と推移がすぐに変わります。",
        judgment="ここは「何枚あったか」を見る画面で、効いたかどうかの判定ではありません。",
        action="下の「よくある見方」から、はせがわ・平山を除く／内科だけ／直近の初回、を試す。",
        measure="判定は Phase 5。見込みは Phase 3。",
        link="phase5_causal.html",
        tone="good",
    )
    rep.add_html(
        '<div class="toolbar-row" id="explore-presets">'
        '<span class="sim-label">よくある見方</span>'
        '<button type="button" data-preset="other">はせがわ・平山を除いて見る</button>'
        '<button type="button" data-preset="intern">内科だけ見る</button>'
        '<button type="button" data-preset="first6">直近6か月の初めて来た人</button>'
        "</div>"
    )
    rep.add_html('<p id="explore-suppress-note" class="caption" hidden></p>')
    rep.add_html('<div id="explore-kpis" class="grid"></div>')

    rep.section("monthly", "月次推移")
    rep.add_html(
        '<div class="toolbar-row">'
        '<button type="button" data-stack="axis">区分別</button>'
        '<button type="button" data-stack="dept">診療科別</button>'
        '<button type="button" id="toggle-events">施策の線を表示切替</button>'
        '<button type="button" id="save-monthly">画像として保存</button>'
        "</div>"
        '<p id="monthly-note" class="caption"></p>'
    )
    rep.chart("chart-monthly", "monthly", fallback=FIGURES / "phase1_monthly_plain.png")

    rep.section("clinics", "クリニック別ランキング")
    rep.add_html(
        '<div class="toolbar-row"><label>表示件数 <input id="rank-n" type="range" min="5" max="21" value="10"/> '
        '<span id="rank-n-label">10</span></label>'
        '<button type="button" id="save-clinics">画像として保存</button></div>'
        '<p id="clinic-note" class="caption"></p>'
        '<p class="caption">棒をクリックすると、そのクリニックに絞り込みます。</p>'
    )
    rep.chart("chart-clinics", "clinic_rank", fallback=FIGURES / "phase1_top_clinics.png")

    rep.section("depts", "診療科構成")
    rep.add_html(
        '<div class="toolbar-row"><button type="button" id="save-depts">画像として保存</button></div>'
        '<p id="dept-note" class="caption"></p>'
        '<p class="caption">棒をクリックすると、その診療科に絞り込みます。</p>'
    )
    rep.chart("chart-depts", "dept_rank")

    rep.section("distance", "距離帯別")
    rep.add_html(
        '<div class="toolbar-row"><button type="button" id="save-distance">画像として保存</button></div>'
        '<p id="dist-note" class="caption"></p>'
    )
    rep.chart("chart-distance", "distance", fallback=FIGURES / "phase2_distance_plain.png")

    rep.section("events", "施策の前後")
    rep.add_html(
        '<div class="toolbar-row">'
        '<label>施策 <select id="event-select"></select></label>'
        '<button type="button" data-event-weeks="4">前4週 / 後4週</button>'
        '<button type="button" data-event-weeks="8">前8週 / 後8週</button>'
        '<button type="button" data-event-weeks="12">前12週 / 後12週</button>'
        "</div>"
        '<div id="event-compare" class="card span-12"></div>'
    )

    rep.section("table", "明細")
    rep.add_html(
        '<div class="toolbar-row"><button type="button" id="explore-csv">CSVをダウンロード</button></div>'
        '<div id="explore-table" class="card span-12 table-scroll" style="padding:0"></div>'
    )

    reports_path = REPORTS / "explore.html"
    docs_path = DOCS / "explore.html"
    rep.save(reports_path)
    shutil.copy2(reports_path, docs_path)
    return docs_path


if __name__ == "__main__":
    print("wrote", build_explore())
