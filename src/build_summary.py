"""トップページ（docs/index.html）に経営サマリーを置く。

各ページが ``data/processed/page_summaries/`` に保存した要約値だけを使い、数字は直書きしない。
サマリー欄はマーカーで囲んで差し替えるので、何度実行しても結果は同じ。

``python3 -m src.build_summary``
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Dict, List

from src.io import ROOT
from src.kpi import load_page_summaries
from src.viz.html_report import FOOTER_NOTE
from src.viz.sidebar import NAV_PAGES

INDEX = ROOT / "docs" / "index.html"

SUMMARY_BEGIN = "<!-- exec-summary:begin -->"
SUMMARY_END = "<!-- exec-summary:end -->"

NEXT_ACTIONS = [
    "門前以外のクリニック（特に内科）との関係づくり",
    "初回来局時の再来の働きかけ（声かけ・LINE登録など）",
    "次の施策から「効果を測れる形」で実施する（配布記録・QRコード）",
]

HERO_TEXT = (
    "自店の処方箋データから、処方箋の出どころ・患者の住まい・定着・施策の効果を見るレポートです。"
    "生の患者CSVは公開していません。"
)

MAP_CARD_TEXT = "患者の住まい・クリニック・競合薬局を地図に重ねて見られます。"

# カードのボタンのリンク先 → ページ要約のキー
CARD_SUMMARY_KEYS = {
    "phase1_flow.html": "p1",
    "phase2_catchment.html": "p2",
    "phase3_model.html": "p3",
    "phase4_retention.html": "p4",
    "phase5_causal.html": "p5",
    "phase6_integrated.html": "p6",
    "pathways.html": "pw",
}


def _pct(v: float) -> str:
    return f"{v:.0%}"


def summary_html(s: Dict[str, Dict[str, object]]) -> str:
    p1, p2, p4, p6, pw = s["p1"], s["p2"], s["p4"], s["p6"], s["pw"]
    status = [
        f"処方箋 <strong>{p6['recent_mean']:,.0f}枚/月</strong>（{p6['period_label']}の平均）"
        f"｜目標 {p6['target']:,.0f}枚/月まで あと<strong>{p6['gap']:,.0f}枚</strong>",
        f"処方箋の<strong>{_pct(p1['gate_share'])}</strong>が門前（{p1.get('gate_def', '')}）、上位2院に{_pct(p1['top2_share'])}が集中",
        f"初めて来た人のうち、90日以内にまた来るのは<strong>{_pct(p4['retention90'])}</strong>",
    ]
    spread = (
        f"耳鼻科・皮膚科の患者が、内科など他の科へ広がっていない（内科系へ移ったのは{_pct(pw['acute_rate'])}）"
        if pw["spread_weak"]
        else f"耳鼻科・皮膚科の患者が、内科など他の科へ広がっている（内科系へ移ったのは{_pct(pw['acute_rate'])}）"
    )
    findings = [
        f"上位2院への依存度が高い（上位2院で処方箋の{_pct(p1['top2_share'])}）",
        f"患者の多くは徒歩圏に住み、少し離れると来なくなる（薬局から1km以内に{_pct(p2['share_1km'])}）",
        spread,
    ]

    def ul(items: List[str], ordered: bool = False) -> str:
        tag = "ol" if ordered else "ul"
        return f"<{tag}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{tag}>"

    return (
        f"{SUMMARY_BEGIN}\n"
        '    <section class="exec-summary" aria-labelledby="summary">\n'
        '      <h2 id="summary">経営サマリー</h2>\n'
        '      <div class="exec-grid">\n'
        f'        <div class="exec-block"><h3>いまの状況</h3>{ul(status)}</div>\n'
        f'        <div class="exec-block"><h3>わかったこと</h3>{ul(findings, ordered=True)}</div>\n'
        f'        <div class="exec-block exec-action"><h3>次にやること</h3>'
        f"{ul([escape(a) for a in NEXT_ACTIONS], ordered=True)}</div>\n"
        "      </div>\n"
        "    </section>\n"
        f"    {SUMMARY_END}"
    )


def _insert_summary(text: str, block: str) -> str:
    pattern = re.compile(re.escape(SUMMARY_BEGIN) + r".*?" + re.escape(SUMMARY_END), re.DOTALL)
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    return text.replace("</header>", f"</header>\n\n    {block}", 1)


_CARD_RE = re.compile(r'<article class="card">.*?</article>', re.DOTALL)
_CARD_TEXT_RE = re.compile(r"(</h2>\s*<p>).*?(</p>)", re.DOTALL)
_CARD_HREF_RE = re.compile(r'<a class="btn[^"]*" href="([^"]+)"')
_CARD_H2_RE = re.compile(r"(<h2>).*?(</h2>)", re.DOTALL)
_CARD_KICKER_RE = re.compile(r'(<p class="card-kicker">).*?(</p>)', re.DOTALL)


def _kicker(page: dict) -> str:
    prefix = page["desc"].split("·")[0].strip() if page["group"] == "phase" else "追加分析"
    return f"{prefix} · {page['title']}"


def _rewrite_cards(text: str, s: Dict[str, Dict[str, object]]) -> str:
    pages = {p["href"]: p for p in NAV_PAGES}

    def one(m: "re.Match[str]") -> str:
        card = m.group(0)
        href = _CARD_HREF_RE.search(card)
        if not href:
            return card
        href = href.group(1)
        key = CARD_SUMMARY_KEYS.get(href)
        if key in s:
            body = escape(str(s[key]["conclusion"]))
        elif href == "map.html":
            body = MAP_CARD_TEXT
        else:
            return card
        card = _CARD_TEXT_RE.sub(lambda t: f"{t.group(1)}{body}{t.group(2)}", card, count=1)
        page = pages.get(href)
        if page:
            card = _CARD_KICKER_RE.sub(lambda t: f"{t.group(1)}{escape(_kicker(page))}{t.group(2)}", card, count=1)
            if page.get("headline"):
                card = _CARD_H2_RE.sub(lambda t: f"{t.group(1)}{escape(page['headline'])}{t.group(2)}", card, count=1)
        return card

    return _CARD_RE.sub(one, text)


def _rewrite_hero_and_notes(text: str) -> str:
    text = re.sub(r'\s*<span class="chip">GitHub Pages</span>', "", text)
    text = re.sub(r'(<header class="hero">.*?<p>).*?(</p>)', lambda m: f"{m.group(1)}{HERO_TEXT}{m.group(2)}",
                  text, count=1, flags=re.DOTALL)
    text = re.sub(
        r'(<div class="note" id="notes">).*?(</div>)',
        lambda m: (
            f"{m.group(1)}\n      <strong>注意:</strong> {FOOTER_NOTE}\n"
            "      個人が特定できる生データ（住所テキスト・受診明細CSV等）はリポジトリに含めていません。\n    "
            f"{m.group(2)}"
        ),
        text, count=1, flags=re.DOTALL,
    )
    text = re.sub(r"(<footer>).*?(</footer>)",
                  lambda m: f"{m.group(1)}\n      {FOOTER_NOTE}\n    {m.group(2)}", text, count=1, flags=re.DOTALL)
    return text


def build_summary(index: Path = INDEX) -> Path:
    summaries = load_page_summaries()
    missing = [k for k in ("p1", "p2", "p4", "p6", "pw") if k not in summaries]
    if missing:
        raise SystemExit(f"ページ要約がありません: {missing}（各 Phase を先に再生成してください）")
    text = index.read_text(encoding="utf-8")
    text = _insert_summary(text, summary_html(summaries))
    text = _rewrite_cards(text, summaries)
    text = _rewrite_hero_and_notes(text)
    index.write_text(text, encoding="utf-8")
    return index


if __name__ == "__main__":
    print("wrote", build_summary().relative_to(ROOT))
