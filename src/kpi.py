"""複数ページで共有する経営指標。

- 「現状の処方箋枚数」は直近3か月の平均で定義する（全期間平均は開局直後の少ない月を含み、実態より低く出るため）。
- 各ページが出した要約値を ``data/processed/page_summaries/`` に JSON で残し、トップページの経営サマリーが読む。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd

from src.io import PROCESSED_DIR, read_csv

RECENT_MONTHS = 3
TARGET_MONTHLY = 3000
SUMMARY_DIR = PROCESSED_DIR / "page_summaries"


@dataclass(frozen=True)
class CurrentLevel:
    """現状の月間処方箋枚数（直近 ``RECENT_MONTHS`` か月平均）と参考値。"""

    recent_mean: float
    period_start: pd.Period
    period_end: pd.Period
    all_mean: float
    n_months: int
    target: float = TARGET_MONTHLY

    @property
    def period_label(self) -> str:
        s, e = self.period_start, self.period_end
        if s.year == e.year:
            return f"{s.year}年{s.month}〜{e.month}月"
        return f"{s.year}年{s.month}月〜{e.year}年{e.month}月"

    @property
    def gap(self) -> float:
        return self.target - self.recent_mean

    @property
    def ratio(self) -> float:
        return self.target / self.recent_mean


def monthly_prescriptions() -> pd.Series:
    """月別の処方箋枚数（1受診＝1枚）。"""
    vt = read_csv("visit_triangle")
    month = pd.to_datetime(vt["受診日"]).dt.to_period("M")
    return month.value_counts().sort_index().rename("処方箋枚数")


def current_level(monthly: Optional[pd.Series] = None) -> CurrentLevel:
    m = monthly if monthly is not None else monthly_prescriptions()
    m = m.sort_index()
    recent = m.iloc[-RECENT_MONTHS:]
    index = pd.PeriodIndex(recent.index.astype(str), freq="M")
    return CurrentLevel(
        recent_mean=float(recent.mean()),
        period_start=index[0],
        period_end=index[-1],
        all_mean=float(m.mean()),
        n_months=int(len(m)),
    )


def save_page_summary(key: str, values: Dict[str, object]) -> None:
    """ページの要約値（経営サマリー用）を保存する。"""
    SUMMARY_DIR.mkdir(parents=True, exist_ok=True)
    path = SUMMARY_DIR / f"{key}.json"
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2, default=float), encoding="utf-8")


def load_page_summaries() -> Dict[str, Dict[str, object]]:
    if not SUMMARY_DIR.exists():
        return {}
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SUMMARY_DIR.glob("*.json"))}
