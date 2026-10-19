"""探索層 JSON が既存 KPI と一致し、個人情報を含まないこと。"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.export_explore_data import DOCS_DATA, export_all, json_contains_pii
from src.kpi import current_level, load_page_summaries, monthly_prescriptions

EXPECTED_RECENT_MEAN = 1768
EXPECTED_FILES = (
    "facts_monthly.json",
    "totals_monthly.json",
    "totals_weekly.json",
    "retention.json",
    "dims.json",
    "params.json",
    "events.json",
)


def _load(name: str) -> dict:
    return json.loads((DOCS_DATA / name).read_text(encoding="utf-8"))


def setup_module(_mod=None) -> None:
    export_all()


def test_export_writes_expected_files():
    for name in EXPECTED_FILES:
        assert (DOCS_DATA / name).exists(), name


def test_monthly_totals_match_kpi():
    totals = _load("totals_monthly.json")
    by_month = {}
    for ym, _axis, n in totals["by_axis"]:
        by_month[ym] = by_month.get(ym, 0) + int(n)
    expected = monthly_prescriptions()
    expected.index = pd.PeriodIndex(expected.index.astype(str), freq="M").astype(str)
    assert set(by_month) == set(expected.index.astype(str))
    for ym, n in by_month.items():
        assert n == int(expected.loc[ym]), ym


def test_recent_three_month_mean_is_1768():
    totals = _load("totals_monthly.json")
    by_month = {}
    for ym, _axis, n in totals["by_axis"]:
        by_month[ym] = by_month.get(ym, 0) + int(n)
    months = sorted(by_month)
    recent = [by_month[m] for m in months[-3:]]
    assert sum(recent) / 3 == EXPECTED_RECENT_MEAN
    assert current_level().recent_mean == EXPECTED_RECENT_MEAN


def test_retention_matches_phase4_summary():
    ret = _load("retention.json")
    p4 = load_page_summaries()["p4"]
    overall = ret["overall"]["ret90"] / ret["overall"]["first"]
    assert overall == p4["retention90"]
    assert abs(overall - 0.4067) < 1e-4


def test_no_pii_in_exported_json():
    for name in EXPECTED_FILES:
        payload = _load(name)
        hits = json_contains_pii(payload)
        assert hits == [], f"{name}: {hits[:5]}"
        raw = (DOCS_DATA / name).read_text(encoding="utf-8")
        for marker in ("患者ID", "生年月日"):
            assert marker not in raw, f"{name} contains {marker}"


def test_small_cells_are_null_not_zero():
    facts = _load("facts_monthly.json")
    values = [row[-1] for row in facts["rows"]]
    assert None in values
    assert all(v is None or v == 0 or v >= 5 for v in values)
    assert 1 not in values and 2 not in values and 3 not in values and 4 not in values
