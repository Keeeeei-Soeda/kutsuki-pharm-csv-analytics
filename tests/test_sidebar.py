"""サイドバーが1ファイルに集約されていることと、全ページに入っていることのテスト。"""

from pathlib import Path

import pytest

from src.apply_ui_shell import PAGE_KEYS
from src.viz.sidebar import NAV_PAGES, ROOT, extract_toc, render_sidebar

DOCS = ROOT / "docs"
PUBLISHED = [p for p in sorted(DOCS.glob("*.html"))]


def test_nav_hrefs_are_unique():
    hrefs = [p["href"] for p in NAV_PAGES]
    assert len(hrefs) == len(set(hrefs))


def test_every_nav_target_is_known_to_the_publisher():
    for page in NAV_PAGES:
        assert page["href"] in PAGE_KEYS, page["href"]


def test_blocked_page_keeps_its_link():
    html = render_sidebar("p1", [("a", "A")])
    assert 'href="phase5_causal.html"' in html
    assert "sb-badge" in html  # データ不足バッジ


def test_active_page_is_marked_once():
    html = render_sidebar("p2", [("a", "A")])
    assert html.count('aria-current="page"') == 1


def test_toc_is_dropped_when_page_has_no_sections():
    assert "sb-toc" not in render_sidebar("p1", [])


@pytest.mark.parametrize("path", PUBLISHED, ids=lambda p: p.name)
def test_published_page_has_one_sidebar(path: Path):
    text = path.read_text(encoding="utf-8")
    assert text.count('<aside class="sidebar"') == 1
    assert text.count('<main class="wrap" id="main">') == 1
    assert text.count('id="notes"') >= 1
    # 旧・上部横並びナビが残っていない
    assert '<nav class="phase-nav"' not in text


@pytest.mark.parametrize("path", PUBLISHED, ids=lambda p: p.name)
def test_sidebar_toc_anchors_exist(path: Path):
    text = path.read_text(encoding="utf-8")
    ids = set()
    for chunk in text.split('id="')[1:]:
        ids.add(chunk.split('"', 1)[0])
    for anchor, _ in extract_toc(text):
        assert anchor in ids, f"{path.name} の #{anchor} が本文にない"
