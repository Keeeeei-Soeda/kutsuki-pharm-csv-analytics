"""探索層用の集計 JSON を ``docs/data/`` に出す。

患者単位の行は出さない。件数が 1〜4 のセルは ``null``（0 にはしない）。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
import yaml

from src.corrections import gate_distance_km
from src.io import ROOT, read_csv
from src.kpi import RECENT_MONTHS, TARGET_MONTHLY, current_level, monthly_prescriptions
from src.models.simulator import growth_inputs_from_current, simulate_scenarios
from src.pathways import load_sequences
from src.phase1_flow import _axis_label
from src.phase4_retention import END_DATE, RETENTION_DAYS, attach_first_attrs
from src.specialty_taxonomy import STANDARD_LABELS, build_specialty_map

DOCS_DATA = ROOT / "docs" / "data"
EVENTS_PATH = ROOT / "config" / "events.yaml"
ECONOMICS_PATH = ROOT / "config" / "economics.yaml"

DIMS = ["ym", "axis", "clinic", "dept", "dist", "visit_type"]
DIST_BINS = [-0.01, 0.5, 1.0, 2.0, 1e9]
DIST_LABELS = ["0-0.5", "0.5-1", "1-2", "2+"]
DIST_DISPLAY = {
    "0-0.5": "0〜0.5km",
    "0.5-1": "0.5〜1km",
    "1-2": "1〜2km",
    "2+": "2km以上",
    "unknown": "不明",
}
AXES = ["門前型", "非門前型", "不明"]
TOP_N_CLINICS = 20
UNKNOWN = "不明"
OTHER = "OTHER"
PII_MARKERS = ("患者ID", "住所", "緯度", "経度", "生年月日")


def suppress_count(n: int) -> Optional[int]:
    """1〜4 は秘匿。0 と 5 以上はそのまま。"""
    value = int(n)
    if 1 <= value <= 4:
        return None
    return value


def _dist_band(km: pd.Series) -> pd.Series:
    num = pd.to_numeric(km, errors="coerce")
    out = pd.cut(num, bins=DIST_BINS, labels=DIST_LABELS).astype(object)
    out = out.where(num.notna(), "unknown")
    return out


def _load_visits() -> pd.DataFrame:
    seq = load_sequences()
    visits = seq["visits"].copy()
    visits["ym"] = pd.to_datetime(visits["受診日"]).dt.to_period("M").astype(str)
    visits["axis"] = _axis_label(visits["立地パターン"])
    visits["dept"] = visits["主科"].fillna(UNKNOWN).replace("", UNKNOWN)
    visits["visit_type"] = visits["受診順"].eq(1).map({True: "初回", False: "再来"})
    pm = read_csv("patient_master")[["患者ID", "患者→薬局_道路km"]]
    if "患者→薬局_道路km" in visits.columns:
        visits = visits.drop(columns=["患者→薬局_道路km"])
    visits = visits.merge(pm, on="患者ID", how="left")
    visits["dist"] = _dist_band(visits["患者→薬局_道路km"])
    counts = visits.groupby("クリニックID").size().sort_values(ascending=False)
    top = set(counts.head(TOP_N_CLINICS).index.astype(str))
    cid = visits["クリニックID"].astype(str)
    visits["clinic"] = cid.where(cid.isin(top) & visits["クリニックID"].notna(), OTHER)
    visits.attrs["top_clinics"] = [str(x) for x in counts.head(TOP_N_CLINICS).index]
    visits.attrs["specialty_map"] = seq["specialty_map"]
    return visits


def _rows(df: pd.DataFrame, cols: Sequence[str], value_col: str, suppress: bool) -> List[list]:
    out: List[list] = []
    for rec in df.itertuples(index=False):
        row = [getattr(rec, c) for c in cols]
        n = int(getattr(rec, value_col))
        row.append(suppress_count(n) if suppress else n)
        out.append(row)
    return out


def build_facts_monthly(visits: pd.DataFrame) -> Dict:
    g = (
        visits.groupby(list(DIMS), dropna=False)
        .size()
        .rename("n")
        .reset_index()
    )
    return {"dims": list(DIMS), "rows": _rows(g, DIMS, "n", suppress=True)}


def build_totals_monthly(visits: pd.DataFrame) -> Dict:
    def one(dim: str) -> List[list]:
        g = visits.groupby(["ym", dim], dropna=False).size().rename("n").reset_index()
        return _rows(g, ["ym", dim], "n", suppress=False)

    return {
        "by_axis": one("axis"),
        "by_dept": one("dept"),
        "by_clinic": one("clinic"),
        "by_dist": one("dist"),
        "by_visit_type": one("visit_type"),
    }


def build_totals_weekly(visits: pd.DataFrame) -> Dict:
    """施策の前後比較用。週始まり（月曜）× 区分の正確な合計。"""
    v = visits.copy()
    day = pd.to_datetime(v["受診日"])
    v["week"] = (day - pd.to_timedelta(day.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
    by_axis = v.groupby(["week", "axis"], dropna=False).size().rename("n").reset_index()
    total = v.groupby("week").size().rename("n").reset_index()
    return {
        "by_axis": _rows(by_axis, ["week", "axis"], "n", suppress=False),
        "total": _rows(total, ["week"], "n", suppress=False),
    }


def build_retention(visits: pd.DataFrame) -> Dict:
    """Phase 4 と同じ定義: 初回受診日 ≤ END_DATE-90 の患者の 90 日再来。"""
    vt = read_csv("visit_triangle")
    vt["軸"] = _axis_label(vt["立地パターン"])
    pm = read_csv("patient_master")
    vh = read_csv("visit_history")
    patients = attach_first_attrs(pm, vt)
    smap = visits.attrs.get("specialty_map")
    if smap is None:
        smap = build_specialty_map(read_csv("clinic_master"))
    patients = patients.merge(
        smap[["クリニックID", "主科"]].rename(columns={"クリニックID": "初回クリニックID", "主科": "dept"}),
        on="初回クリニックID",
        how="left",
    )
    patients["dept"] = patients["dept"].fillna(UNKNOWN).replace("", UNKNOWN)
    patients["axis"] = patients["初回軸"].fillna(UNKNOWN)
    patients["dist"] = _dist_band(patients["道路km"])
    patients["初回受診日"] = pd.to_datetime(patients["初回受診日"])
    cutoff = END_DATE - pd.Timedelta(days=RETENTION_DAYS)
    eligible = patients.loc[patients["初回受診日"] <= cutoff].copy()

    vh = vh.copy()
    vh["受診日"] = pd.to_datetime(vh["受診日"])
    joined = vh.merge(eligible[["患者ID", "初回受診日"]], on="患者ID", how="inner")
    joined["日差"] = (joined["受診日"] - joined["初回受診日"]).dt.days
    second = (
        joined.loc[joined["日差"] > 0]
        .groupby("患者ID")["日差"]
        .min()
        .rename("再来日数")
    )
    eligible = eligible.merge(second, on="患者ID", how="left")
    eligible["ret90"] = (eligible["再来日数"] <= RETENTION_DAYS).fillna(False).astype(int)
    eligible["ym"] = eligible["初回受診日"].dt.to_period("M").astype(str)

    g = (
        eligible.groupby(["ym", "axis", "dept", "dist"], dropna=False)
        .agg(first=("患者ID", "count"), ret90=("ret90", "sum"))
        .reset_index()
    )
    rows = []
    for rec in g.itertuples(index=False):
        rows.append(
            {
                "ym": rec.ym,
                "axis": rec.axis,
                "dept": rec.dept,
                "dist": rec.dist,
                "first": suppress_count(int(rec.first)),
                "ret90": suppress_count(int(rec.ret90)),
            }
        )
    return {
        "cutoff": cutoff.strftime("%Y-%m-%d"),
        "days": RETENTION_DAYS,
        "overall": {"first": int(len(eligible)), "ret90": int(eligible["ret90"].sum())},
        "rows": rows,
    }


def build_dims(visits: pd.DataFrame) -> Dict:
    cm = read_csv("clinic_master")
    smap = visits.attrs.get("specialty_map")
    if smap is None:
        smap = build_specialty_map(cm)
    gate_km = gate_distance_km()
    top = list(visits.attrs.get("top_clinics") or [])
    clinics_src = cm.merge(smap[["クリニックID", "主科"]], on="クリニックID", how="left")
    clinics_src["門前判定"] = (
        pd.to_numeric(clinics_src["クリニック→薬局_直線km"], errors="coerce") <= gate_km + 1e-9
    )
    clinics: Dict[str, dict] = {}
    for cid in top:
        row = clinics_src.loc[clinics_src["クリニックID"].astype(str).eq(cid)]
        if row.empty:
            clinics[cid] = {"name": cid, "dept": UNKNOWN, "gate": False}
            continue
        r = row.iloc[0]
        clinics[cid] = {
            "name": None if pd.isna(r.get("クリニック名")) else str(r["クリニック名"]),
            "dept": UNKNOWN if pd.isna(r.get("主科")) or str(r.get("主科")) == "" else str(r["主科"]),
            "gate": bool(r["門前判定"]) if pd.notna(r["門前判定"]) else False,
        }
    clinics[OTHER] = {"name": "その他", "dept": None, "gate": None}

    day = pd.to_datetime(visits["受診日"])
    depts = [d for d in STANDARD_LABELS if d in set(visits["dept"])] + (
        [UNKNOWN] if UNKNOWN in set(visits["dept"]) else []
    )
    extra = sorted(set(visits["dept"]) - set(depts))
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period": {
            "min": day.min().strftime("%Y-%m-%d"),
            "max": day.max().strftime("%Y-%m-%d"),
        },
        "gate_km": gate_km,
        "clinics": clinics,
        "clinic_order": top + [OTHER],
        "dept_order": depts + extra,
        "axes": AXES,
        "dist_order": DIST_LABELS + ["unknown"],
        "dist_labels": DIST_DISPLAY,
        "visit_types": ["初回", "再来"],
    }


def build_params(visits: pd.DataFrame) -> Dict:
    econ = yaml.safe_load(ECONOMICS_PATH.read_text(encoding="utf-8")) or {}
    level = current_level()
    inp = growth_inputs_from_current(level.recent_mean, level.target)
    scen = simulate_scenarios(inp)
    scenarios = []
    for _, r in scen.iterrows():
        scenarios.append(
            {
                "name": str(r["シナリオ"]),
                "visits": float(r["予測月間件数"]),
                "ratio": float(r["対ベース倍率"]),
                "reaches_target": bool(r["目標3,000到達"]),
                "note": str(r["注記"]),
            }
        )
    unknown = max(0.0, 1.0 - float(inp.gate_share) - float(inp.nongate_share))
    return {
        "target_monthly": TARGET_MONTHLY,
        "recent_months": RECENT_MONTHS,
        "gross_margin_yen": int(econ.get("gross_margin_per_visit_yen", 2000)),
        "current": {
            "monthly_visits": float(inp.monthly_visits),
            "gate_share": float(inp.gate_share),
            "nongate_share": float(inp.nongate_share),
            "unknown_share": float(unknown),
            "unique_patients": float(inp.unique_patients),
            "mean_visits_per_patient": float(inp.mean_visits_per_patient),
            "months": float(inp.months),
            "period_label": level.period_label,
            "all_mean": float(level.all_mean),
        },
        "default_scenarios": scenarios,
    }


def _json_ready(obj):
    if isinstance(obj, dict):
        return {str(k): _json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_ready(v) for v in obj]
    if isinstance(obj, (pd.Timestamp, datetime, date)):
        return obj.strftime("%Y-%m-%d")
    if hasattr(obj, "item"):
        try:
            return obj.item()
        except Exception:
            return obj
    return obj


def build_events() -> Dict:
    raw = yaml.safe_load(EVENTS_PATH.read_text(encoding="utf-8")) or {}
    return _json_ready(raw)


def json_contains_pii(obj) -> List[str]:
    """キーまたは文字列値に個人情報マーカーが含まれる箇所。"""
    hits: List[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k)
                here = f"{path}.{key}" if path else key
                for marker in PII_MARKERS:
                    if marker in key:
                        hits.append(here)
                walk(v, here)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            for marker in PII_MARKERS:
                if marker in node:
                    hits.append(path or "<root>")

    walk(obj, "")
    return hits


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return path


def export_all(out_dir: Optional[Path] = None) -> Dict[str, Path]:
    dest = Path(out_dir) if out_dir is not None else DOCS_DATA
    dest.mkdir(parents=True, exist_ok=True)
    visits = _load_visits()
    payloads = {
        "facts_monthly.json": build_facts_monthly(visits),
        "totals_monthly.json": build_totals_monthly(visits),
        "totals_weekly.json": build_totals_weekly(visits),
        "retention.json": build_retention(visits),
        "dims.json": build_dims(visits),
        "params.json": build_params(visits),
        "events.json": build_events(),
    }
    paths = {name: write_json(dest / name, data) for name, data in payloads.items()}
    return paths


def main() -> None:
    paths = export_all()
    for name, path in paths.items():
        print("wrote", path.relative_to(ROOT), "bytes", path.stat().st_size)


if __name__ == "__main__":
    main()
