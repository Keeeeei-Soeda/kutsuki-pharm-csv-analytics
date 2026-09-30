"""既存レポート HTML に共通サイドバーシェルを適用する。

分析を再実行せずに UI だけ更新するためのエントリポイント。
``python3 -m src.apply_ui_shell``
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from src.snapshot_academic import add_main_banner
from src.viz.sidebar import FONTS_LINK, apply_shell

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

# ファイル名 → サイドバーの active key
PAGE_KEYS: Dict[str, str] = {
    "index.html": "",
    "phase1_flow.html": "p1",
    "phase2_catchment.html": "p2",
    "phase3_model.html": "p3",
    "phase4_retention.html": "p4",
    "phase5_causal.html": "p5",
    "phase6_integrated.html": "p6",
    "integrated_model.html": "p6",
    "pathways.html": "pathways",
    "map.html": "map",
}


_FONTS_RE = re.compile(r'<link[^>]*data-shell="fonts"[^>]*>\s*')


def inject_fonts(path: Path) -> None:
    """テーマ用 Web フォントの <link> を </head> 直前へ1本だけ入れる（冪等）。"""
    text = _FONTS_RE.sub("", path.read_text(encoding="utf-8"))
    text = text.replace("</head>", f"{FONTS_LINK}\n</head>", 1)
    path.write_text(text, encoding="utf-8")


def apply_all() -> List[Path]:
    touched: List[Path] = []
    for directory in (REPORTS, DOCS):
        if not directory.exists():
            continue
        for name, key in PAGE_KEYS.items():
            path = directory / name
            if path.exists():
                apply_shell(path, key or None)
                inject_fonts(path)
                touched.append(path)
    # 再生成されたページから学術版への導線が落ちないよう、毎回入れ直す（冪等）
    add_main_banner()
    return touched


if __name__ == "__main__":
    for p in apply_all():
        print("shell applied:", p.relative_to(ROOT))
