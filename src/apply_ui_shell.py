"""既存レポート HTML に共通サイドバーシェルを適用する。

分析を再実行せずに UI だけ更新するためのエントリポイント。
``python3 -m src.apply_ui_shell``

修正前（``reports/before``・``docs/before``）と修正後（``reports``・``docs``）の
両方にシェルを当てる。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from src.snapshot_academic import remove_main_banner
from src.viz.explore_assets import copy_explore_assets
from src.viz.sidebar import FONTS_LINK, apply_shell

ROOT = Path(__file__).resolve().parents[1]

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
    "explore.html": "explore",
}

# 修正後 → 修正前の順で適用（どちらも独立）
SHELL_TREES = (
    ROOT / "reports",
    ROOT / "docs",
    ROOT / "reports" / "before",
    ROOT / "docs" / "before",
)


_FONTS_RE = re.compile(r'<link[^>]*data-shell="fonts"[^>]*>\s*')


def inject_fonts(path: Path) -> None:
    """テーマ用 Web フォントの <link> を </head> 直前へ1本だけ入れる（冪等）。"""
    text = _FONTS_RE.sub("", path.read_text(encoding="utf-8"))
    text = text.replace("</head>", f"{FONTS_LINK}\n</head>", 1)
    path.write_text(text, encoding="utf-8")


def apply_tree(directory: Path) -> List[Path]:
    touched: List[Path] = []
    if not directory.exists():
        return touched
    for name, key in PAGE_KEYS.items():
        path = directory / name
        if path.exists():
            apply_shell(path, key or None)
            inject_fonts(path)
            touched.append(path)
    return touched


def apply_all() -> List[Path]:
    touched: List[Path] = []
    for directory in SHELL_TREES:
        touched.extend(apply_tree(directory))
    # 学術版への導線はサイドバー下部のリンクに移したので、旧バナーが残っていれば外す（冪等）
    remove_main_banner()
    # 修正後・修正前それぞれに explore アセットを同期
    copy_explore_assets(docs_dir=ROOT / "docs", reports_dir=ROOT / "reports")
    if (ROOT / "docs" / "before").exists():
        copy_explore_assets(docs_dir=ROOT / "docs" / "before", reports_dir=ROOT / "reports" / "before")
    return touched


if __name__ == "__main__":
    for p in apply_all():
        print("shell applied:", p.relative_to(ROOT))
