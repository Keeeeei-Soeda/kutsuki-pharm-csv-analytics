"""既存レポート HTML に共通サイドバーシェルを適用する。

分析を再実行せずに UI だけ更新するためのエントリポイント。
``python3 -m src.apply_ui_shell``
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from src.viz.sidebar import apply_shell

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


def apply_all() -> List[Path]:
    touched: List[Path] = []
    for directory in (REPORTS, DOCS):
        if not directory.exists():
            continue
        for name, key in PAGE_KEYS.items():
            path = directory / name
            if path.exists():
                apply_shell(path, key or None)
                touched.append(path)
    return touched


if __name__ == "__main__":
    for p in apply_all():
        print("shell applied:", p.relative_to(ROOT))
