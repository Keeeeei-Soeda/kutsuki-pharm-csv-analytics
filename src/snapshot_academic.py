"""旧UI版（学術用）を docs/academic/ に凍結して残す。

薬局向けの最新版は docs/ 直下、学術用の旧版は docs/academic/ に置き、
GitHub Pages 上で **両方を同時に公開**する。

    /                 … 薬局向け（サイドバーUI・来院経路・商圏マップ）
    /academic/        … 学術用（サイドバー導入前の凍結版）

旧版は「再生成しない凍結スナップショット」として扱う。内容を変えたくなったら
別の git ref を指定して取り直す。

    python3 -m src.snapshot_academic            # 既定の ref から取得
    python3 -m src.snapshot_academic <git-ref>  # ref を指定
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ACADEMIC = DOCS / "academic"

# サイドバー導入直前のコミット（旧UIの正本）
DEFAULT_REF = "33efca2"

BANNER_ID = "version-switch"


def _tracked_files(ref: str) -> List[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "docs/"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def _read_blob(ref: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout


BANNER_ACADEMIC = """<div id="version-switch" style="background:#103a3a;color:#f7fffe;padding:10px 16px;font-size:13px;font-family:'Hiragino Sans',sans-serif;text-align:center">
<strong>学術用（旧UI）版</strong>です。サイドバー・来院経路・商圏マップを含む薬局向けの最新版は
<a href="../index.html" style="color:#9fe3dd">こちら</a>。
</div>"""

BANNER_MAIN = """<div id="version-switch" class="version-switch">
<strong>薬局向け最新版</strong>を表示しています。サイドバー導入前の学術用（旧UI）版は
<a href="academic/index.html">こちら</a>で凍結保存しています。
</div>"""

BANNER_MAIN_CSS = """
.version-switch {
  background: #eef5f4;
  border: 1px solid #bcd9d5;
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 13px;
  color: #17423f;
  margin: 0 0 16px;
}
.version-switch a { color: #0f6a6a; font-weight: 600; }
@media print { .version-switch { display: none; } }
"""


def snapshot(ref: str = DEFAULT_REF) -> List[Path]:
    """``ref`` 時点の docs/ を docs/academic/ に取り出す。"""
    written: List[Path] = []
    for rel in _tracked_files(ref):
        sub = rel[len("docs/"):]
        if not sub or sub.startswith("academic/"):
            continue
        target = ACADEMIC / sub
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = _read_blob(ref, rel)
        if sub.endswith(".html"):
            text = blob.decode("utf-8")
            # 旧版から持ち越している壊れたリンクだけは直す（地図は figures/ 配下）
            text = text.replace('href="phase2_map.html"', 'href="figures/phase2_map.html"')
            if BANNER_ID not in text:
                text = text.replace("<body>", "<body>\n" + BANNER_ACADEMIC, 1)
            target.write_text(text, encoding="utf-8")
        else:
            target.write_bytes(blob)
        written.append(target)
    return written


def add_main_banner() -> List[Path]:
    """最新版（docs/ 直下）に学術版への導線を入れる。"""
    touched: List[Path] = []
    for path in sorted(DOCS.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if BANNER_ID in text:
            continue
        if ".version-switch" not in text and "</style>" in text:
            text = text.replace("</style>", BANNER_MAIN_CSS + "\n</style>", 1)
        marker = '<main class="wrap" id="main">'
        if marker not in text:
            continue
        idx = text.index(marker) + len(marker)
        text = text[:idx] + "\n  " + BANNER_MAIN + text[idx:]
        path.write_text(text, encoding="utf-8")
        touched.append(path)
    return touched


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REF
    files = snapshot(ref)
    print(f"snapshot {ref} -> docs/academic/ ({len(files)} files)")
    for p in add_main_banner():
        print("banner:", p.relative_to(ROOT))


if __name__ == "__main__":
    main()
