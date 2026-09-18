"""DataBank CSV 読み込み（dtype・encoding・欠損規則の一元管理）。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
INTERIM_DIR = ROOT / "data" / "interim"
PROCESSED_DIR = ROOT / "data" / "processed"

SEED = 42

# くつき薬局南茨木店（データ辞書 §4-1）
PHARMACY_LAT = 34.801298494906895
PHARMACY_LON = 135.56540221590993
PHARMACY_NAME = "くつき薬局南茨木店"

# 論理ファイル名 → 読み込みオプション
FILE_SPECS: Dict[str, dict] = {
    "patient_master": {"parse_dates": ["生年月日", "初回受診日", "最終受診日"]},
    "patient_clinic_with_distance": {"parse_dates": ["初回受診日"]},
    "visit_history": {"parse_dates": ["受診日"]},
    "visit_history_with_weather_pollen": {"parse_dates": ["受診日"]},
    "visit_triangle": {"parse_dates": ["受診日"]},
    "clinic_master": {"parse_dates": ["取得日"]},
    "clinic_master_from_prescriptions": {},
    "competitor_pharmacy": {},
    "weather_pollen": {"parse_dates": ["日付"]},
    "infectious_disease_osaka_weekly": {
        "parse_dates": ["週開始日", "週終了日"]
    },
    "mesh_population": {},
    "population_by_age": {},
    "population_visitors_2024": {},
    "population_visitors_2025": {},
    "population_visitors_2026": {},
    "prescriptions_monthly": {},
    "prescriptions_by_age": {},
    "juryoritsu_by_age": {},
}

AGE_CLASS_EXCEL_FIX = {"5月9日": "5-9", "10月14日": "10-14"}


def raw_path(logical_name: str) -> Path:
    path = RAW_DIR / f"{logical_name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"raw CSV not found: {path}")
    return path


def _normalize_age_class(series: pd.Series) -> pd.Series:
    return series.replace(AGE_CLASS_EXCEL_FIX)


def read_csv(
    logical_name: str,
    *,
    apply_age_fix: bool = True,
    corrections: bool = True,
) -> pd.DataFrame:
    """data/raw から論理名で読み込む。raw 自体は上書きしない。

    ``config/corrections.yaml`` の有効な補正は読み込み直後に適用される
    （生データ + 補正定義 = 分析用データ）。
    """
    spec = FILE_SPECS.get(logical_name, {})
    parse_dates = spec.get("parse_dates")
    df = pd.read_csv(
        raw_path(logical_name),
        encoding="utf-8-sig",
        parse_dates=parse_dates if parse_dates else None,
        low_memory=False,
    )
    if apply_age_fix and "年齢階級" in df.columns:
        df["年齢階級"] = _normalize_age_class(df["年齢階級"].astype(str))
    if corrections:
        from src.corrections import apply_corrections

        df = apply_corrections(df, logical_name)
    return df


def load_all(names: Optional[list] = None) -> Dict[str, pd.DataFrame]:
    targets = names or list(FILE_SPECS.keys())
    return {name: read_csv(name) for name in targets}


def ensure_dirs() -> None:
    for d in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, ROOT / "reports" / "figures", ROOT / "docs"):
        d.mkdir(parents=True, exist_ok=True)
