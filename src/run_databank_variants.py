"""DataBank 修正前／修正後を同一補正設定で二重生成する。

用法::

    python3 -m src.run_databank_variants           # before → after
    python3 -m src.run_databank_variants --only after
    python3 -m src.run_databank_variants --only before

各バリアントは環境変数 ``DATABANK_VARIANT`` で ``src.io`` の入出力パスを切替える。
分析補正（``config/corrections.yaml``）は両側で同じ定義を使う。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence

ROOT = Path(__file__).resolve().parents[1]

# README の実行列に揃えたステップ（バリアントごとに同じ順序）
PIPELINE: List[List[str]] = [
    [sys.executable, "-m", "src.validate"],
    [sys.executable, "-m", "src.run_early_phases"],
    [sys.executable, "-m", "src.phase1_flow"],
    [sys.executable, "-m", "src.export_phase1_html"],
    [sys.executable, "-m", "src.phase2_catchment"],
    [sys.executable, "-m", "src.phase3_model"],
    [sys.executable, "-m", "src.phase4_retention"],
    [sys.executable, "-m", "src.phase5_causal"],
    [sys.executable, "-m", "src.phase6_integrated"],
    [sys.executable, "-m", "src.pathways"],
    [sys.executable, "-m", "src.build_map"],
    [sys.executable, "-m", "src.export_explore_data"],
    [sys.executable, "-m", "src.build_explore"],
    [sys.executable, "-m", "src.build_summary"],
]

# phase1/2 は reports に出し docs へ手コピーが必要なものがある
COPY_AFTER_PHASES = [
    ("phase1_flow.html", True),
    ("phase2_catchment.html", True),
]


def _run(cmd: Sequence[str], *, variant: str) -> None:
    env = os.environ.copy()
    env["DATABANK_VARIANT"] = variant
    print(f"\n=== [{variant}] {' '.join(cmd)} ===", flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def _copy_reports_to_docs(variant: str) -> None:
    """phase1/2 HTML と figures を docs ツリーへ送る（他Phaseは各モジュールが自動コピー）。"""
    env = os.environ.copy()
    env["DATABANK_VARIANT"] = variant
    # パス解決は子プロセスで io を読む
    script = r"""
import shutil
from pathlib import Path
from src.io import REPORTS_DIR, DOCS_DIR, FIGURES_DIR
DOCS_DIR.mkdir(parents=True, exist_ok=True)
(DOCS_DIR / "figures").mkdir(parents=True, exist_ok=True)
for name in ("phase1_flow.html", "phase2_catchment.html"):
    src = REPORTS_DIR / name
    if src.exists():
        shutil.copy2(src, DOCS_DIR / name)
        print("copied", src, "->", DOCS_DIR / name)
if FIGURES_DIR.exists():
    for p in FIGURES_DIR.iterdir():
        if p.is_file():
            shutil.copy2(p, DOCS_DIR / "figures" / p.name)
    print("copied figures ->", DOCS_DIR / "figures")
"""
    subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env, check=True)


def run_variant(variant: str) -> None:
    if variant == "before":
        raw = ROOT / "data" / "raw_before"
        if not raw.exists():
            raise SystemExit(
                f"missing {raw}. Chatwork受領前スナップショットを先に用意してください。"
            )
    for cmd in PIPELINE:
        _run(cmd, variant=variant)
        # phase2 の直後に HTML/figures を docs へ（README の cp に相当）
        if cmd[-1] == "src.phase2_catchment":
            _copy_reports_to_docs(variant)
    # 最終的にもう一度 figures/HTML を揃える
    _copy_reports_to_docs(variant)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=("before", "after", "both"),
        default="both",
        help="生成するバリアント（既定: both = before → after）",
    )
    parser.add_argument(
        "--shell-only",
        action="store_true",
        help="分析を回さず UI シェルだけ両ツリーへ適用",
    )
    args = parser.parse_args(argv)

    if args.shell_only:
        _run([sys.executable, "-m", "src.apply_ui_shell"], variant="after")
        return 0

    order = ["before", "after"] if args.only == "both" else [args.only]
    for variant in order:
        run_variant(variant)

    # シェルは両ツリーへ（apply_ui_shell が before/after 両方を見る）
    _run([sys.executable, "-m", "src.apply_ui_shell"], variant="after")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
