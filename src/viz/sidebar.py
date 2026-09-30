"""共通サイドバーのレンダラ。

マークアップの実体は ``templates/_sidebar.html`` 1ファイルのみ。
CSS / JS も ``templates/_sidebar.css`` / ``templates/_sidebar.js`` に集約する。
Phase を増やすときは :data:`NAV_PAGES` を1行足すだけでよい。
"""

from __future__ import annotations

import html
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"

PERIOD_LABEL = "受診 2024-09-02 〜 2026-07-31"

FONTS_LINK = (
    '<link rel="stylesheet" data-shell="fonts" href="https://fonts.googleapis.com/css2?'
    'family=BIZ+UDPGothic:wght@400;700&family=Zen+Kaku+Gothic+New:wght@500;700&display=swap">'
)

# icon は viewBox 0 0 24 24 の線画パス
NAV_PAGES: List[dict] = [
    {"key": "p1", "href": "phase1_flow.html", "title": "Phase 1 Prescription Flow",
     "desc": "門前と非門前のフロー", "group": "phase", "blocked": False,
     "icon": '<path d="M4 7h10M4 12h16M4 17h7"/>'},
    {"key": "p2", "href": "phase2_catchment.html", "title": "Phase 2 Clinic Catchment",
     "desc": "商圏とクリニック分布", "group": "phase", "blocked": False,
     "icon": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>'},
    {"key": "p3", "href": "phase3_model.html", "title": "Phase 3 Choice & Growth",
     "desc": "選択モデルと成長試算", "group": "phase", "blocked": False,
     "icon": '<path d="M5 20V11M11 20V5M17 20v-6M3 20h18"/>'},
    {"key": "p4", "href": "phase4_retention.html", "title": "Phase 4 Retention & LTV",
     "desc": "残存・定着・LTV", "group": "phase", "blocked": False,
     "icon": '<path d="M4 17l5-5 4 4 7-8"/>'},
    {"key": "p5", "href": "phase5_causal.html", "title": "Phase 5 Causal Impact",
     "desc": "介入効果の推定", "group": "phase", "blocked": False,
     "icon": '<path d="M6 12h12M13 7l5 5-5 5"/>'},
    {"key": "p6", "href": "phase6_integrated.html", "title": "Phase 6 Integrated Model",
     "desc": "統合モデルと予測", "group": "phase", "blocked": False,
     "icon": '<rect x="3" y="3" width="7" height="7" rx="1.5"/>'
             '<rect x="14" y="3" width="7" height="7" rx="1.5"/>'
             '<rect x="3" y="14" width="7" height="7" rx="1.5"/>'
             '<rect x="14" y="14" width="7" height="7" rx="1.5"/>'},
    {"key": "pathways", "href": "pathways.html", "title": "来院経路",
     "desc": "1→2→3回目の診療科遷移", "group": "extra", "blocked": False,
     "icon": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8 8l8 8"/>'},
    {"key": "map", "href": "map.html", "title": "地図",
     "desc": "商圏・競合・来局率マップ", "group": "extra", "blocked": False,
     "icon": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/>'},
]

_PHASE_TO_KEY = {1: "p1", 2: "p2", 3: "p3", 4: "p4", 5: "p5", 6: "p6"}


def _esc(text: object) -> str:
    return html.escape("" if text is None else str(text))


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


_BEGIN = "/* === サイドバーシェル BEGIN === (templates/_sidebar.html と対) */"
_END = "/* === サイドバーシェル END === */"


def sidebar_css() -> str:
    body = "\n".join(
        _read(n).replace(_BEGIN, "").replace(_END, "").strip()
        for n in ("_sidebar.css", "_theme.css")
    )
    return f"{_BEGIN}\n{body}\n{_END}"


def sidebar_js() -> str:
    return _read("_sidebar.js")


def key_for_phase(phase: Optional[int]) -> Optional[str]:
    return _PHASE_TO_KEY.get(phase) if phase is not None else None


def _nav_items(group: str, active_key: Optional[str]) -> str:
    out = []
    for page in NAV_PAGES:
        if page["group"] != group:
            continue
        classes = ["is-blocked"] if page["blocked"] else []
        current = ' aria-current="page"' if page["key"] == active_key else ""
        badge = '<span class="sb-badge">データ不足</span>' if page["blocked"] else ""
        cls = f' class="{" ".join(classes)}"' if classes else ""
        icon = (
            '<svg class="sb-icon" viewBox="0 0 24 24" width="18" height="18" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round" aria-hidden="true">{page["icon"]}</svg>'
            if page.get("icon") else ""
        )
        out.append(
            f'<li><a href="{_esc(page["href"])}"{cls}{current}>'
            f"{icon}"
            f'<span class="sb-item-text">'
            f'<span class="sb-item-title">{_esc(page["title"])}{badge}</span>'
            f'<span class="sb-item-desc">{_esc(page["desc"])}</span>'
            f"</span></a></li>"
        )
    return "\n      ".join(out)


def _toc_items(toc: Sequence[Tuple[str, str]]) -> str:
    return "\n      ".join(
        f'<li><a href="#{_esc(anchor)}">{_esc(label)}</a></li>' for anchor, label in toc
    )


def render_sidebar(
    active_key: Optional[str] = None,
    toc: Optional[Sequence[Tuple[str, str]]] = None,
    *,
    breadcrumb: str = "Kutsuki DataBank",
    home_href: str = "index.html",
    period: str = PERIOD_LABEL,
    generated: Optional[str] = None,
) -> str:
    """``templates/_sidebar.html`` を埋めて返す。全ページこれ1本を使う。"""
    # テンプレート冒頭の開発用コメントは出力へ持ち込まない
    tmpl = re.sub(r"\A\s*<!--.*?-->\s*", "", _read("_sidebar.html"), flags=re.DOTALL)
    values = {
        "{{HOME_HREF}}": _esc(home_href),
        "{{PERIOD}}": _esc(period or PERIOD_LABEL),
        "{{GENERATED}}": _esc(generated or datetime.now().strftime("%Y-%m-%d %H:%M")),
        "{{BREADCRUMB}}": _esc(breadcrumb),
        "{{PHASE_ITEMS}}": _nav_items("phase", active_key),
        "{{EXTRA_ITEMS}}": _nav_items("extra", active_key),
        "{{PAGE_TOC}}": _toc_items(toc or []),
    }
    for token, value in values.items():
        tmpl = tmpl.replace(token, value)
    if not (toc or []):
        # 見出しのないページ（index など）では目次ブロックごと落とす
        tmpl = re.sub(r'<nav class="sb-toc".*?</nav>\s*', "", tmpl, count=1, flags=re.DOTALL)
    return tmpl


# --------------------------------------------------------------------------
# 既存 HTML へのレトロフィット（再分析せずにシェルだけ差し替える）
# --------------------------------------------------------------------------

_OLD_NAV_RE = re.compile(r'<nav class="phase-nav".*?</nav>\s*', re.DOTALL)
_SIDEBAR_RE = re.compile(r'<a class="skip-link".*?</aside>\s*', re.DOTALL)
_H2_RE = re.compile(r'<h2[^>]*\bid="([^"]+)"[^>]*>(.*?)</h2>', re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SHELL_CSS_RE = re.compile(
    r"\n*/\* === サイドバーシェル BEGIN === .*?/\* === サイドバーシェル END === \*/\s*",
    re.DOTALL,
)
_SHELL_JS_RE = re.compile(
    r'<script data-shell="sidebar">.*?</script>\s*', re.DOTALL
)


def extract_toc(text: str) -> List[Tuple[str, str]]:
    """本文の ``<h2 id=...>`` から目次を組み立てる（既存アンカーを流用）。"""
    toc: List[Tuple[str, str]] = []
    for anchor, raw_label in _H2_RE.findall(text):
        label = html.unescape(_TAG_RE.sub("", raw_label)).strip()
        if label:
            toc.append((anchor, label))
    return toc


def _breadcrumb_of(text: str) -> str:
    m = re.search(r'<div class="eyebrow">(.*?)</div>', text, re.DOTALL)
    if m:
        return html.unescape(_TAG_RE.sub("", m.group(1))).strip()
    return "Kutsuki DataBank"


def apply_shell(html_path: PathLike, active_key: Optional[str] = None) -> Path:
    """既存レポート HTML を「サイドバー + main」構成へ差し替える（冪等）。"""
    path = Path(html_path)
    original = path.read_text(encoding="utf-8")
    text = original

    # 1) 旧ナビ・旧シェルを取り除く
    text = _OLD_NAV_RE.sub("", text)
    text = _SIDEBAR_RE.sub("", text)
    text = _SHELL_JS_RE.sub("", text)
    text = _SHELL_CSS_RE.sub("", text)

    # 2) CSS を注入（既存 <style> の末尾へ）
    if "</style>" in text:
        text = text.replace("</style>", "\n" + sidebar_css() + "\n</style>", 1)
    else:
        text = text.replace("</head>", f"<style>{sidebar_css()}</style>\n</head>", 1)

    # 3) 本文コンテナを <main id="main"> にする
    text = text.replace('<div class="wrap">', '<main class="wrap" id="main">', 1)
    if '<main class="wrap" id="main">' in text:
        idx = text.rfind("</div>\n</body>")
        if idx != -1:
            text = text[:idx] + "</main>\n</body>" + text[idx + len("</div>\n</body>"):]

    # 4) 本文側の旧ピル目次は撤去（サイドバーに集約）
    text = re.sub(
        r'<div class="card span-12 toc"[^>]*>.*?</div>\s*', "", text, count=1, flags=re.DOTALL
    )

    # 5) 注意事項アンカー
    text = text.replace('<footer class="footer">', '<footer class="footer" id="notes">', 1)
    if 'id="notes"' not in text:
        text = text.replace('<div class="note">', '<div class="note" id="notes">', 1)

    # 6) サイドバーを差し込む
    toc = extract_toc(text)
    sidebar = render_sidebar(active_key, toc, breadcrumb=_breadcrumb_of(text))
    text = re.sub(r"<body([^>]*)>", lambda m: f"<body{m.group(1)}>\n{sidebar}", text, count=1)

    # 7) JS を差し込む
    text = text.replace(
        "</body>", f'<script data-shell="sidebar">\n{sidebar_js()}\n</script>\n</body>', 1
    )
    if "</html>" not in text or len(text) < len(original) * 0.5:
        raise RuntimeError(f"shell 適用で本文が失われた可能性があります: {path}")
    path.write_text(text, encoding="utf-8")
    return path
