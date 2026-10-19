"""探索層の JS / 図の差し込み（HtmlReport と apply_ui_shell が共有）。"""

from __future__ import annotations

import json
import re
import shutil
from html import escape
from pathlib import Path
from typing import Optional

from src.io import ROOT, REPORTS_DIR, DOCS_DIR

DOCS = DOCS_DIR
REPORTS = REPORTS_DIR


def _default_docs() -> Path:
    return DOCS_DIR


def _default_reports() -> Path:
    return REPORTS_DIR

EXPLORE_CHARTS = {
    "phase1_monthly_plain.png": {"id": "p1-monthly", "kind": "monthly"},
    "phase1_monthly_gate.png": {"id": "p1-monthly-gate", "kind": "monthly"},
    "phase1_top_clinics.png": {"id": "p1-clinics", "kind": "clinic_rank"},
    "phase1_timeseries.png": {"id": "p1-ts", "kind": "monthly", "options": {"kind": "line"}},
    "phase4_retention90.png": {"id": "p4-ret", "kind": "retention90"},
    "phase5_timeline.png": {"id": "p5-timeline", "kind": "timeline"},
}

# 枚数チャートに差し替えてしまった図を、元の PNG（来局率）に戻す
UNWRAP_CHART_IDS = {"p2-dist"}

MODEL_FIGURES = {
    "phase3_visitrate_glm.png",
    "phase3_mesh_glm.png",
    "phase3_clinic_clogit.png",
    "phase3_huff.png",
    "phase4_intervals.png",
    "phase4_multilevel.png",
    "phase5_flyer_effects.png",
    "phase5_its.png",
    "phase6_forecast.png",
    "phase6_forecast_plain.png",
}

_SCRIPTS_RE = re.compile(
    r'\n*<script data-shell="(?:echarts|explore|inline-charts|explore-page|map-page)"[\s\S]*?</script>'
)
_HASJS_RE = re.compile(r'<script data-shell="has-js">.*?</script>\s*', re.DOTALL)
_SIM_RE = re.compile(r'\s*<section[^>]*id="growth-simulator"[^>]*>.*?</section>', re.DOTALL)
_BADGE_RE = re.compile(r'<span class="model-badge">.*?</span>')

SIMULATOR_HTML = """
<section class="card span-12" id="growth-simulator" data-simulator="1">
  <h3>条件を動かして試す</h3>
</section>
"""


def explore_script_tags(*, explore_page: bool = False, map_page: bool = False) -> str:
    tags = [
        '<script data-shell="has-js">document.documentElement.classList.add("has-js");</script>',
        '<script data-shell="echarts" src="vendor/echarts.min.js"></script>',
        '<script data-shell="explore" type="module" src="js/filters-ui.js"></script>',
        '<script data-shell="inline-charts" type="module" src="js/pages/inline-charts.js"></script>',
    ]
    if explore_page:
        tags.append('<script data-shell="explore-page" type="module" src="js/pages/explore.js"></script>')
    if map_page:
        tags.append('<script data-shell="map-page" type="module" src="js/pages/map.js"></script>')
    return "\n".join(tags)


def chart_markup(
    chart_id: str,
    kind: str,
    options: Optional[dict] = None,
    *,
    fallback_html: str = "",
) -> str:
    payload = {"id": chart_id, "kind": kind}
    if options:
        payload.update(options)
    raw = json.dumps(payload, ensure_ascii=False)
    return (
        f'<div class="chart-wrap" data-chart="{escape(raw, quote=True)}">'
        f'<div class="chart-canvas" id="{escape(chart_id)}" style="height:360px"></div>'
        f"{fallback_html}</div>"
    )


def copy_explore_assets(
    *,
    docs_dir: Path | None = None,
    reports_dir: Path | None = None,
) -> None:
    """docs の js・vendor・data を reports にも置き、ローカルの reports HTML でも読めるようにする。"""
    docs = docs_dir or _default_docs()
    reports = reports_dir or _default_reports()
    reports.mkdir(parents=True, exist_ok=True)
    for name in ("js", "vendor", "data"):
        src = docs / name
        dest = reports / name
        if not src.exists():
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)


def _find_div_end(text: str, start: int) -> int:
    """``start`` 位置の ``<div ...>`` に対応する閉じタグの直後を返す。"""
    i = text.find(">", start) + 1
    depth = 1
    while i < len(text) and depth:
        next_open = text.find("<div", i)
        next_close = text.find("</div>", i)
        if next_close < 0:
            return len(text)
        if next_open >= 0 and next_open < next_close:
            depth += 1
            i = text.find(">", next_open) + 1
        else:
            depth -= 1
            i = next_close + len("</div>")
    return i


def unwrap_charts(text: str) -> str:
    """誤って対話チャート化した図を、印刷用 PNG の figure に戻す（冪等）。"""
    for cid in UNWRAP_CHART_IDS:
        pos = 0
        needle = f'id="{cid}"'
        while True:
            id_pos = text.find(needle, pos)
            if id_pos < 0:
                break
            wrap_start = text.rfind('<div class="chart-wrap"', 0, id_pos)
            if wrap_start < 0:
                pos = id_pos + 1
                continue
            wrap_end = _find_div_end(text, wrap_start)
            block = text[wrap_start:wrap_end]
            fig = re.search(
                r'<div class="figure(?: chart-print-fallback)?"[^>]*>.*?</div>',
                block,
                re.DOTALL,
            )
            if not fig:
                pos = wrap_end
                continue
            restored = fig.group(0).replace(
                'class="figure chart-print-fallback"', 'class="figure"', 1
            )
            text = text[:wrap_start] + restored + text[wrap_end:]
            pos = wrap_start + len(restored)
    return text


def wrap_explore_charts(text: str) -> str:
    for filename, spec in EXPLORE_CHARTS.items():
        if f'id="{spec["id"]}"' in text and "data-chart=" in text:
            continue
        marker = f'data-fig="{filename}"'
        pos = text.find(marker)
        if pos < 0:
            alt_pos = text.find(f'alt="{filename}"')
            if alt_pos < 0:
                continue
            fig_start = text.rfind('<div class="figure">', 0, alt_pos)
        else:
            fig_start = text.rfind('<div class="figure">', 0, pos)
        if fig_start < 0:
            continue
        fig_end = text.find("</div>", fig_start)
        if fig_end < 0:
            continue
        fig_end += len("</div>")
        original = text[fig_start:fig_end]
        fallback = original.replace('<div class="figure">', '<div class="figure chart-print-fallback">', 1)
        insert = chart_markup(spec["id"], spec["kind"], spec.get("options"), fallback_html=fallback)
        text = text[:fig_start] + insert + text[fig_end:]
    return text


def inject_model_badges(text: str) -> str:
    for name in MODEL_FIGURES:
        marker = f'data-fig="{name}"'
        pos = text.find(marker)
        if pos < 0:
            pos = text.find(f'alt="{name}"')
        if pos < 0:
            continue
        fig_start = text.rfind('<div class="figure">', 0, pos)
        if fig_start < 0:
            continue
        chunk = text[fig_start : fig_start + 80]
        if "model-badge" in chunk:
            continue
        text = (
            text[:fig_start]
            + text[fig_start:].replace(
                '<div class="figure">',
                '<div class="figure"><span class="model-badge">全期間・全患者で推定</span>',
                1,
            )
        )
    return text


def inject_simulator(text: str) -> str:
    if 'id="growth-simulator"' in text:
        return text
    needle = '<h2 id="scenarios">'
    pos = text.find(needle)
    if pos < 0:
        return text
    # 見出しの直後（fig-point の前）に置く
    end = text.find("</h2>", pos)
    if end < 0:
        return text
    end += len("</h2>")
    return text[:end] + SIMULATOR_HTML + text[end:]


def inject_explore_scripts(
    text: str, *, explore_page: bool = False, map_page: bool = False
) -> str:
    text = _SCRIPTS_RE.sub("", text)
    text = _HASJS_RE.sub("", text)
    tags = explore_script_tags(explore_page=explore_page, map_page=map_page)
    if "</body>" in text:
        text = text.replace("</body>", tags + "\n</body>", 1)
    return text


def enhance_html(
    text: str, *, explore_page: bool = False, phase3: bool = False, map_page: bool = False
) -> str:
    text = unwrap_charts(text)
    text = wrap_explore_charts(text)
    text = inject_model_badges(text)
    if phase3:
        text = inject_simulator(text)
    text = inject_explore_scripts(text, explore_page=explore_page, map_page=map_page)
    return text
