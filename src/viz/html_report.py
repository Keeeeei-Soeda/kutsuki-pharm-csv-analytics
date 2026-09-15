"""分析レポート用の HTML レンダラ（単一ファイル・印刷対応）。"""

from __future__ import annotations

import base64
import html
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

PathLike = Union[str, Path]


CSS = """
:root {
  --bg: #f3f1eb;
  --surface: #fffcf7;
  --ink: #1c2430;
  --muted: #5c6675;
  --line: #d9d2c5;
  --accent: #0f6a6a;
  --accent-2: #c45c26;
  --gate: #c45c26;
  --nongate: #2f6f9f;
  --ok: #2f7d4a;
  --warn: #a15c12;
  --shadow: 0 10px 30px rgba(28, 36, 48, 0.08);
  --radius: 18px;
  --mono: "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace;
  --sans: "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Segoe UI", sans-serif;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: var(--sans);
  color: var(--ink);
  background:
    radial-gradient(1200px 600px at 10% -10%, #e7f2f1 0%, transparent 55%),
    radial-gradient(900px 500px at 100% 0%, #f8e8dc 0%, transparent 50%),
    var(--bg);
  line-height: 1.65;
}
a { color: var(--accent); }
.wrap { max-width: 1120px; margin: 0 auto; padding: 32px 20px 80px; }
.hero {
  background: linear-gradient(135deg, #103a3a 0%, #0f6a6a 55%, #2f6f9f 100%);
  color: #f7fffe;
  border-radius: 28px;
  padding: 36px 36px 28px;
  box-shadow: var(--shadow);
  position: relative;
  overflow: hidden;
}
.hero::after {
  content: "";
  position: absolute;
  right: -80px; top: -80px;
  width: 260px; height: 260px;
  border-radius: 50%;
  background: rgba(255,255,255,0.08);
}
.hero .eyebrow {
  letter-spacing: 0.14em;
  text-transform: uppercase;
  font-size: 12px;
  opacity: 0.8;
  margin-bottom: 10px;
}
.hero h1 {
  margin: 0 0 10px;
  font-size: clamp(28px, 4vw, 40px);
  line-height: 1.2;
  font-weight: 700;
}
.hero p { margin: 0; max-width: 48rem; opacity: 0.92; }
.meta {
  display: flex; flex-wrap: wrap; gap: 10px;
  margin-top: 18px;
}
.chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px;
  border-radius: 999px;
  background: rgba(255,255,255,0.14);
  font-size: 12px;
}
.grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 16px;
  margin-top: 22px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 18px 18px 16px;
  box-shadow: var(--shadow);
}
.span-3 { grid-column: span 3; }
.span-4 { grid-column: span 4; }
.span-6 { grid-column: span 6; }
.span-8 { grid-column: span 8; }
.span-12 { grid-column: span 12; }
@media (max-width: 900px) {
  .span-3, .span-4, .span-6, .span-8 { grid-column: span 12; }
}
.kpi .label { color: var(--muted); font-size: 12px; letter-spacing: 0.04em; }
.kpi .value {
  font-size: 28px; font-weight: 700; margin-top: 6px;
  font-variant-numeric: tabular-nums;
}
.kpi .sub { color: var(--muted); font-size: 12px; margin-top: 4px; }
h2 {
  margin: 36px 0 12px;
  font-size: 22px;
  border-left: 4px solid var(--accent);
  padding-left: 12px;
}
h3 { margin: 18px 0 8px; font-size: 16px; }
.section-note {
  color: var(--muted);
  font-size: 13px;
  margin: 0 0 14px;
}
.figure {
  margin: 8px 0 4px;
  border-radius: 14px;
  overflow: hidden;
  border: 1px solid var(--line);
  background: #fff;
}
.figure img { display: block; width: 100%; height: auto; }
.caption {
  color: var(--muted);
  font-size: 12px;
  margin: 6px 0 0;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  background: #fff;
  border-radius: 12px;
  overflow: hidden;
}
th, td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}
th {
  background: #efeae1;
  font-weight: 600;
  white-space: nowrap;
}
tr:last-child td { border-bottom: none; }
.num { text-align: right; font-variant-numeric: tabular-nums; font-family: var(--mono); font-size: 12px; }
.callout {
  border-radius: 14px;
  padding: 14px 16px;
  border: 1px solid var(--line);
  background: #fff;
}
.callout.ok { border-color: #b9d8c4; background: #f2faf5; }
.callout.warn { border-color: #e6d0a8; background: #fff8ec; }
.callout ul { margin: 8px 0 0; padding-left: 1.2rem; }
.toc a {
  display: inline-block;
  margin: 0 10px 8px 0;
  padding: 6px 10px;
  border-radius: 999px;
  background: #fff;
  border: 1px solid var(--line);
  text-decoration: none;
  font-size: 12px;
  color: var(--ink);
}
.footer {
  margin-top: 40px;
  color: var(--muted);
  font-size: 12px;
  border-top: 1px solid var(--line);
  padding-top: 16px;
}
.tag-gate { color: var(--gate); font-weight: 700; }
.tag-nongate { color: var(--nongate); font-weight: 700; }
iframe.map {
  width: 100%;
  height: 520px;
  border: 0;
  border-radius: 14px;
}
@media print {
  body { background: #fff; }
  .hero { break-inside: avoid; }
  .card, .figure { box-shadow: none; }
}
"""


def _esc(text: object) -> str:
    return html.escape("" if text is None else str(text))


def img_to_data_uri(path: PathLike) -> str:
    p = Path(path)
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    suffix = p.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(
        suffix, "application/octet-stream"
    )
    return f"data:{mime};base64,{b64}"


class HtmlReport:
    def __init__(
        self,
        title: str,
        subtitle: str = "",
        pharmacy: str = "",
        period: str = "",
        eyebrow: str = "DataBank Analytics",
    ):
        self.title = title
        self.subtitle = subtitle
        self.pharmacy = pharmacy
        self.period = period
        self.eyebrow = eyebrow
        self.kpis: List[dict] = []
        self.toc: List[tuple] = []
        self.blocks: List[str] = []

    def add_kpi(self, label: str, value: str, sub: str = "") -> None:
        self.kpis.append({"label": label, "value": value, "sub": sub})

    def add_toc(self, anchor: str, label: str) -> None:
        self.toc.append((anchor, label))

    def add_html(self, chunk: str) -> None:
        self.blocks.append(chunk)

    def section(self, anchor: str, title: str, note: str = "") -> None:
        self.add_toc(anchor, title)
        note_html = f'<p class="section-note">{_esc(note)}</p>' if note else ""
        self.blocks.append(f'<h2 id="{_esc(anchor)}">{_esc(title)}</h2>{note_html}')

    def callout(self, title: str, items: Sequence[str], kind: str = "ok") -> None:
        lis = "".join(f"<li>{_esc(x)}</li>" for x in items)
        self.blocks.append(
            f'<div class="callout { _esc(kind) }"><strong>{_esc(title)}</strong><ul>{lis}</ul></div>'
        )

    def paragraph(self, text: str) -> None:
        self.blocks.append(f"<p>{_esc(text)}</p>")

    def markdownish(self, text: str) -> None:
        """極簡易: 段落をそのまま。"""
        self.blocks.append(f"<p>{_esc(text)}</p>")

    def figure(self, image_path: PathLike, caption: str = "", embed: bool = True) -> None:
        p = Path(image_path)
        if not p.exists():
            self.blocks.append(f'<p class="caption">（図なし: {_esc(p.name)}）</p>')
            return
        src = img_to_data_uri(p) if embed else str(p)
        cap = f'<p class="caption">{_esc(caption)}</p>' if caption else ""
        self.blocks.append(
            f'<div class="figure"><img src="{src}" alt="{_esc(caption or p.name)}"/></div>{cap}'
        )

    def table(self, headers: Sequence[str], rows: Iterable[Sequence[object]], numeric_cols: Optional[Sequence[int]] = None) -> None:
        numeric_cols = set(numeric_cols or [])
        thead = "".join(f"<th>{_esc(h)}</th>" for h in headers)
        body = []
        for row in rows:
            tds = []
            for i, cell in enumerate(row):
                cls = ' class="num"' if i in numeric_cols else ""
                tds.append(f"<td{cls}>{_esc(cell)}</td>")
            body.append("<tr>" + "".join(tds) + "</tr>")
        self.blocks.append(
            f'<div class="card span-12" style="padding:0;overflow:auto"><table><thead><tr>{thead}</tr></thead>'
            f"<tbody>{''.join(body)}</tbody></table></div>"
        )

    def folium_iframe(self, folium_html_path: PathLike, caption: str = "") -> None:
        p = Path(folium_html_path)
        if not p.exists():
            self.blocks.append(f'<p class="caption">（地図なし: {_esc(p.name)}）</p>')
            return
        # embed as iframe srcdoc for single-file portability is huge; link relative instead
        rel = p.name
        cap = f'<p class="caption">{_esc(caption)} <a href="{_esc(rel)}" target="_blank">別窓で開く</a></p>'
        self.blocks.append(
            f'<iframe class="map" src="{_esc(rel)}" title="{_esc(caption or "map")}"></iframe>{cap}'
        )

    def render(self) -> str:
        kpi_html = ""
        if self.kpis:
            cards = []
            span = 3 if len(self.kpis) >= 4 else (4 if len(self.kpis) == 3 else 6)
            for k in self.kpis:
                cards.append(
                    f'<div class="card span-{span} kpi">'
                    f'<div class="label">{_esc(k["label"])}</div>'
                    f'<div class="value">{_esc(k["value"])}</div>'
                    f'<div class="sub">{_esc(k.get("sub",""))}</div></div>'
                )
            kpi_html = f'<div class="grid">{"".join(cards)}</div>'

        toc_html = ""
        if self.toc:
            links = "".join(f'<a href="#{_esc(a)}">{_esc(lab)}</a>' for a, lab in self.toc)
            toc_html = f'<div class="card span-12 toc" style="margin-top:18px">{links}</div>'

        chips = []
        if self.pharmacy:
            chips.append(f'<span class="chip">{_esc(self.pharmacy)}</span>')
        if self.period:
            chips.append(f'<span class="chip">{_esc(self.period)}</span>')
        chips.append(f'<span class="chip">生成 {datetime.now().strftime("%Y-%m-%d %H:%M")}</span>')

        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_esc(self.title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div class="eyebrow">{_esc(self.eyebrow)}</div>
    <h1>{_esc(self.title)}</h1>
    <p>{_esc(self.subtitle)}</p>
    <div class="meta">{''.join(chips)}</div>
  </header>
  {kpi_html}
  {toc_html}
  {''.join(self.blocks)}
  <footer class="footer">
    自店受診データに基づく記述分析です。市場全体の選択率・因果効果としては解釈しないでください。
    花粉欠損は0埋めしていません。新患フラグは使用していません。
  </footer>
</div>
</body>
</html>
"""

    def save(self, path: PathLike) -> Path:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(self.render(), encoding="utf-8")
        return out
