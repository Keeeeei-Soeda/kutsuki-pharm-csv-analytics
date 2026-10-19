"""共通サイドバーのレンダラ。

マークアップの実体は ``templates/_sidebar.html`` 1ファイルのみ。
CSS / JS も ``templates/_sidebar.css`` / ``templates/_sidebar.js`` に集約する。
Phase を増やすときは :data:`NAV_PAGES` を1行足すだけでよい。
"""

from __future__ import annotations

import html
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

PathLike = Union[str, Path]

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"

PERIOD_LABEL = "受診 2024-09-02 〜 2026-07-31"

# --------------------------------------------------------------------------
# テーマ（見た目）の切り替え
#   a … クリニカル・スタンダード（ネイビーのサイドバー）
#   d … ソフト・ベント（白い浮きサイドバー＋パステルのタイル）← 既定
# 環境変数 REPORT_THEME=a / d で一時的に上書きできる。
# --------------------------------------------------------------------------
_GF = "https://fonts.googleapis.com/css2?"
THEMES = {
    "a": {
        "css": "_theme.css",
        "fonts": _GF + "family=BIZ+UDPGothic:wght@400;700&family=Zen+Kaku+Gothic+New:wght@500;700&display=swap",
    },
    "d": {
        "css": "_theme_d.css",
        "fonts": _GF + "family=Zen+Maru+Gothic:wght@500;700;900&display=swap",
    },
}
DEFAULT_THEME = "d"
THEME = os.environ.get("REPORT_THEME", DEFAULT_THEME).strip().lower()
if THEME not in THEMES:
    raise ValueError(f"REPORT_THEME は {sorted(THEMES)} のいずれか: {THEME!r}")

FONTS_LINK = f'<link rel="stylesheet" data-shell="fonts" href="{THEMES[THEME]["fonts"]}">'

# icon は viewBox 0 0 24 24 の線画パス
NAV_PAGES: List[dict] = [
    {"key": "explore", "href": "explore.html", "title": "データ探索",
     "headline": "データを絞り込んで見る",
     "desc": "枚数・推移・クリニック・距離・再来", "group": "explore", "blocked": False,
     "icon": '<circle cx="11" cy="11" r="7"/><path d="M16 16l5 5"/>'},
    {"key": "p1", "href": "phase1_flow.html", "title": "処方箋の流れ",
     "headline": "処方箋はどこから来ているか",
     "desc": "Phase 1 · 隣の2院とそれ以外", "group": "phase", "blocked": False,
     "icon": '<path d="M4 7h10M4 12h16M4 17h7"/>'},
    {"key": "p2", "href": "phase2_catchment.html", "title": "商圏とクリニック",
     "headline": "患者はどこに住み、どの医院に通っているか",
     "desc": "Phase 2 · 患者の住所と通院先", "group": "phase", "blocked": False,
     "icon": '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/>'},
    {"key": "p3", "href": "phase3_model.html", "title": "来局率と成長余地",
     "headline": "何が来局率を左右し、どこまで伸ばせるか",
     "desc": "Phase 3 · どこまで伸ばせるか", "group": "phase", "blocked": False,
     "icon": '<path d="M5 20V11M11 20V5M17 20v-6M3 20h18"/>'},
    {"key": "p4", "href": "phase4_retention.html", "title": "患者の定着",
     "headline": "患者は定着しているか",
     "desc": "Phase 4 · また来てくれているか", "group": "phase", "blocked": False,
     "icon": '<path d="M4 17l5-5 4 4 7-8"/>'},
    {"key": "p5", "href": "phase5_causal.html", "title": "施策の効果",
     "headline": "チラシや施策は効いたか",
     "desc": "Phase 5 · チラシと継続施策", "group": "phase", "blocked": False,
     "icon": '<path d="M6 12h12M13 7l5 5-5 5"/>'},
    {"key": "p6", "href": "phase6_integrated.html", "title": "今後の見込み",
     "headline": "この先の処方箋枚数はどうなるか",
     "desc": "Phase 6 · 来月の見込みと目標", "group": "phase", "blocked": False,
     "icon": '<rect x="3" y="3" width="7" height="7" rx="1.5"/>'
             '<rect x="14" y="3" width="7" height="7" rx="1.5"/>'
             '<rect x="3" y="14" width="7" height="7" rx="1.5"/>'
             '<rect x="14" y="14" width="7" height="7" rx="1.5"/>'},
    {"key": "pathways", "href": "pathways.html", "title": "来院経路",
     "desc": "耳鼻科・皮膚科から他の科へ広がるか", "group": "extra", "blocked": False,
     "icon": '<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="18" r="2.5"/><path d="M8 8l8 8"/>'},
    {"key": "map", "href": "map.html", "title": "商圏マップ",
     "desc": "患者の住まい・クリニック・競合薬局", "group": "extra", "blocked": False,
     "icon": '<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2-6-2zM9 4v14M15 6v14"/>'},
]

_PHASE_TO_KEY = {1: "p1", 2: "p2", 3: "p3", 4: "p4", 5: "p5", 6: "p6"}


def headline_for(key: Optional[str]) -> Optional[str]:
    """ページ見出し（経営者向けの問いの形）。未定義なら None。"""
    for page in NAV_PAGES:
        if page["key"] == key:
            return page.get("headline")
    return None


def _esc(text: object) -> str:
    return html.escape("" if text is None else str(text))


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


_BEGIN = "/* === サイドバーシェル BEGIN === (templates/_sidebar.html と対) */"
_END = "/* === サイドバーシェル END === */"


def sidebar_css() -> str:
    body = "\n".join(
        _read(n).replace(_BEGIN, "").replace(_END, "").strip()
        for n in ("_sidebar.css", THEMES[THEME]["css"])
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


def html_databank_variant(html_path: Path) -> str:
    """HTML の配置から DataBank バリアント（after / before）を判定する。"""
    try:
        rel = Path(html_path).resolve().relative_to(ROOT)
    except ValueError:
        return "after"
    parts = rel.parts
    if len(parts) >= 2 and parts[1] == "before":
        return "before"
    return "after"


def render_version_switch(html_path: PathLike) -> str:
    """各ページ上部の「修正後／修正前」セグメント。"""
    path = Path(html_path)
    name = path.name
    variant = html_databank_variant(path)
    if variant == "before":
        after_href, before_href = f"../{name}", name
        hint = "Chatwork受領前の DataBank"
    else:
        after_href, before_href = name, f"before/{name}"
        hint = "今回取り込んだ修正後 DataBank"
    tmpl = _read("_version_switch.html")
    values = {
        "{{AFTER_HREF}}": _esc(after_href),
        "{{BEFORE_HREF}}": _esc(before_href),
        "{{AFTER_CURRENT}}": ' aria-current="page"' if variant == "after" else "",
        "{{BEFORE_CURRENT}}": ' aria-current="page"' if variant == "before" else "",
        "{{HINT}}": _esc(hint),
    }
    for token, value in values.items():
        tmpl = tmpl.replace(token, value)
    return tmpl


def render_sidebar(
    active_key: Optional[str] = None,
    toc: Optional[Sequence[Tuple[str, str]]] = None,
    *,
    breadcrumb: str = "Kutsuki DataBank",
    home_href: str = "index.html",
    academic_href: str = "academic/index.html",
    period: str = PERIOD_LABEL,
    generated: Optional[str] = None,
) -> str:
    """``templates/_sidebar.html`` を埋めて返す。全ページこれ1本を使う。"""
    # テンプレート冒頭の開発用コメントは出力へ持ち込まない
    tmpl = re.sub(r"\A\s*<!--.*?-->\s*", "", _read("_sidebar.html"), flags=re.DOTALL)
    values = {
        "{{HOME_HREF}}": _esc(home_href),
        "{{ACADEMIC_HREF}}": _esc(academic_href),
        "{{PERIOD}}": _esc(period or PERIOD_LABEL),
        # 日付までにして、同じ日に何度適用しても差分が出ないようにする
        "{{GENERATED}}": _esc(generated or datetime.now().strftime("%Y-%m-%d")),
        "{{BREADCRUMB}}": _esc(breadcrumb),
        "{{EXPLORE_ITEMS}}": _nav_items("explore", active_key),
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
_VERSION_SWITCH_RE = re.compile(
    r'<nav class="version-switch"[^>]*>.*?</nav>\s*', re.DOTALL
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


_TABLE_RE = re.compile(r"<table\b.*?</table>", re.DOTALL)
_HERO_H1_RE = re.compile(r'(<header class="hero">.*?<h1[^>]*>)(.*?)(</h1>)', re.DOTALL)
_TITLE_RE = re.compile(r"<title>.*?</title>", re.DOTALL)


def align_numeric_headers(text: str) -> str:
    """数値列（先頭行の td.num）に対応する th にも num を付け、見出しを右揃えにする（冪等）。"""

    def _fix(match: re.Match) -> str:
        table = match.group(0)
        head = re.search(r"<thead>.*?</thead>", table, re.DOTALL)
        row = re.search(r"<tbody>\s*<tr>(.*?)</tr>", table, re.DOTALL)
        if not head or not row:
            return table
        num_idx = {i for i, td in enumerate(re.findall(r"<td([^>]*)>", row.group(1))) if 'class="num"' in td}
        counter = iter(range(10_000))

        def _th(m: re.Match) -> str:
            i = next(counter)
            attrs = m.group(1) or ""
            if i in num_idx and "class=" not in attrs:
                return f'<th class="num"{attrs}>'
            return m.group(0)

        new_head = re.sub(r"<th(\s[^>]*)?>", _th, head.group(0))
        return table.replace(head.group(0), new_head, 1)

    return _TABLE_RE.sub(_fix, text)


def apply_headline(text: str, key: Optional[str]) -> str:
    """ヒーローの h1 と <title> を経営者向けの見出しに差し替える（冪等）。"""
    headline = headline_for(key)
    if not headline:
        return text
    text = _HERO_H1_RE.sub(lambda m: m.group(1) + _esc(headline) + m.group(3), text, count=1)
    phase = next((n for n, k in _PHASE_TO_KEY.items() if k == key), None)
    title = f"Phase {phase}｜{headline}" if phase else headline
    return _TITLE_RE.sub(f"<title>{_esc(title)}</title>", text, count=1)


UI_TEXT_FIXES: Tuple[Tuple[str, str], ...] = (
    # Phase 1: 図を積み上げ棒に替えたので「線の右端」の説明を合わせる
    ("橙が門前、青が門前以外の月別の処方箋枚数です。線の右端の数字が直近月の枚数です。",
     "橙が門前、青が門前以外、灰色が不明の月別の処方箋枚数（積み上げ）です。点線は目標の枚数で、棒にカーソルを合わせると内訳が出ます。"),
    # Phase 1: 診療科の途中切れ
    ("<td>内科・呼吸器内科・アレルギー科・リハ</td>", "<td>内科・呼吸器内科・アレルギー科ほか</td>"),
    ("<td>内科・消化器内科・外科・消化器外科・</td>", "<td>内科・消化器内科・外科・消化器外科ほか</td>"),
    ("<td>整形外科・リハビリテーション科・リウ</td>", "<td>整形外科・リハビリテーション科ほか</td>"),
    ("<td>内科・脳神経外科・放射線科・リハビリ</td>", "<td>内科・脳神経外科・放射線科ほか</td>"),
    # Phase 5: 上位2院（はせがわ・平山）は40m基準では門前ではない
    ("黒が処方箋全体、橙が門前2院、青が門前以外、緑の点線が新患の月別の数です。縦の点線と網掛けが施策の時期で、番号は下の注記に対応します。",
     "黒が処方箋全体、橙が上位2院（はせがわ・平山）、青が上位2院以外、緑の点線が新患（初めて来局した人）の月別の数です。縦の点線と網掛けが施策の時期で、丸数字は図の下の一覧に対応します。"),
)

_HALFWIDTH_KANA_RE = re.compile(r"[｡-ﾟ]+")


def fix_display_text(text: str) -> str:
    """表示文言の誤りを直し、元データ由来の半角カナを全角にそろえる（冪等）。"""
    for old, new in UI_TEXT_FIXES:
        text = text.replace(old, new)
    return _HALFWIDTH_KANA_RE.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


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

    # 5.5) 見出しを経営者向けの問いに、数値列の見出しを右揃えに
    text = apply_headline(text, active_key)
    text = align_numeric_headers(text)

    # 6) サイドバーを差し込む（before/ 配下は学術リンクを一段上げる）
    toc = extract_toc(text)
    variant = html_databank_variant(path)
    academic_href = "../academic/index.html" if variant == "before" else "academic/index.html"
    sidebar = render_sidebar(
        active_key,
        toc,
        breadcrumb=_breadcrumb_of(text),
        academic_href=academic_href,
    )
    text = re.sub(r"<body([^>]*)>", lambda m: f"<body{m.group(1)}>\n{sidebar}", text, count=1)

    # 6.5) DataBank 修正前／修正後タブ（#main 直下・冪等）
    text = _VERSION_SWITCH_RE.sub("", text)
    switch = render_version_switch(path)
    text = text.replace(
        '<main class="wrap" id="main">',
        f'<main class="wrap" id="main">\n{switch}\n',
        1,
    )

    # 7) JS を差し込む
    text = text.replace(
        "</body>", f'<script data-shell="sidebar">\n{sidebar_js()}\n</script>\n</body>', 1
    )
    from src.viz.explore_assets import enhance_html

    name = path.name
    text = enhance_html(
        text,
        explore_page=name == "explore.html",
        phase3=name == "phase3_model.html",
        map_page=name == "map.html",
    )
    text = fix_display_text(text)
    if "</html>" not in text or len(text) < len(original) * 0.5:
        raise RuntimeError(f"shell 適用で本文が失われた可能性があります: {path}")
    path.write_text(text, encoding="utf-8")
    return path
