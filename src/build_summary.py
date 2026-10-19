"""トップページ（docs/index.html）に経営サマリーを置く。"""

from __future__ import annotations

import json
import re
from html import escape
from pathlib import Path
from typing import Dict, List

from src.io import ROOT, DOCS_DIR
from src.kpi import load_page_summaries
from src.viz.html_report import FOOTER_NOTE
from src.viz.sidebar import NAV_PAGES

INDEX = DOCS_DIR / "index.html"

SUMMARY_BEGIN = "<!-- exec-summary:begin -->"
SUMMARY_END = "<!-- exec-summary:end -->"

HERO_TEXT = (
    "自店の処方箋データから、処方箋の出どころ・患者の住まい・定着・施策の効果を見るレポートです。"
    "生の患者CSVは公開していません。"
)

MAP_CARD_TEXT = "患者の住まい・クリニック・競合薬局を地図に重ねて見られます。"

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


def _collect_actions(s: Dict[str, Dict[str, object]]) -> List[dict]:
    out: List[dict] = []
    for key in ("p1", "p2", "p4", "p5", "p3", "pw"):
        for a in s.get(key, {}).get("actions") or []:
            if isinstance(a, dict):
                out.append(a)
            elif isinstance(a, str):
                out.append({"what": a, "page": ""})
        if len(out) >= 4:
            break
    return out[:4]


def summary_html(s: Dict[str, Dict[str, object]]) -> str:
    p1, p2, p4, p6, pw = s["p1"], s["p2"], s["p4"], s["p6"], s["pw"]
    hase = float(p1.get("hase_monthly") or 0)
    hira = float(p1.get("hira_monthly") or 0)
    other = float(p1.get("other_monthly") or 0)
    recent = float(p6["recent_mean"])
    top2 = hase + hira if hase else recent * float(p1.get("top2_share") or 0)
    other = other or recent * (1 - float(p1.get("top2_share") or 0))
    period = p1.get("period_label") or p6.get("period_label") or ""
    status = [
        f"処方箋 <strong>{recent:,.0f}枚/月</strong>（{period}の平均）"
        f"｜目標 {p6['target']:,.0f}枚/月まで あと<strong>{p6['gap']:,.0f}枚</strong>",
        f"はせがわ・平山の2院で <strong>{top2 / recent:.0%}</strong>（{top2:,.0f}枚）、"
        f"それ以外 <strong>{other / recent:.0%}</strong>（{other:,.0f}枚）",
        f"初めて来た人のうち、3か月以内にまた来る人は<strong>{_pct(p4['retention90'])}</strong>"
        f"（初回の人数は各ページに記載）",
    ]
    spread = (
        f"耳鼻科・皮膚科で来た人は、内科の処方箋をうちに持ってきていない（{_pct(pw['acute_rate'])}）"
        if pw["spread_weak"]
        else f"耳鼻科・皮膚科で来た人が、内科の処方箋も持ってくるようになっている（{_pct(pw['acute_rate'])}）"
    )
    findings = [
        f"注意：2院に頼りすぎ。はせがわが1割減ると店全体で約{hase * 0.1:,.0f}枚/月減る"
        if hase else f"注意：上位2院で処方箋の{_pct(p1['top2_share'])}",
        f"良い：近所（1km以内）には強い（患者の{_pct(p2['share_1km'])}）",
        f"チャンス：{spread}",
    ]
    actions = _collect_actions(s)
    action_items = []
    for i, a in enumerate(actions):
        what = escape(str(a.get("what", "")))
        href = escape(str(a.get("page") or ""))
        link = f' <a href="{href}">くわしく</a>' if href else ""
        action_items.append(
            f'<label class="todo-item"><input type="checkbox" data-todo="{i}"/> {what}{link}</label>'
        )
    measure = escape(str((actions[0] or {}).get("measure") or "2院以外の枚数が増えているか")) if actions else ""

    def ul(items: List[str], ordered: bool = False) -> str:
        tag = "ol" if ordered else "ul"
        return f"<{tag}>" + "".join(f"<li>{i}</li>" for i in items) + f"</{tag}>"

    todos = "<div class='todo-list'>" + "".join(action_items) + "</div>" if action_items else ul(["各ページの今月やることを実行する"], True)

    return (
        f"{SUMMARY_BEGIN}\n"
        '    <section class="exec-summary" aria-labelledby="summary">\n'
        '      <h2 id="summary">今月の1枚</h2>\n'
        '      <div class="exec-grid">\n'
        f'        <div class="exec-block"><h3>いまの状況</h3>{ul(status)}</div>\n'
        f'        <div class="exec-block"><h3>判断</h3>{ul(findings, ordered=True)}</div>\n'
        f'        <div class="exec-block exec-action"><h3>今月やること</h3>{todos}'
        f'<p class="caption">来月、ここを見る：{measure}</p></div>\n'
        "      </div>\n"
        '      <p class="print-actions"><button type="button" class="btn" data-print="1">今月のやることリストを印刷</button></p>\n'
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
