"""Growth Engine 分解シミュレータ（シナリオ感度）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd


@dataclass
class GrowthInputs:
    # 現状の月間処方箋枚数。固定値は置かず、src.kpi.current_level()（直近3か月平均）を渡す。
    monthly_visits: float
    target_monthly: float = 3000.0
    unique_patients: float = 8885.0
    months: float = 23.0
    mean_visits_per_patient: float = 3.59
    # gate_share = 隣の2院（はせがわ・平山）、nongate_share = それ以外
    gate_share: float = 0.67
    nongate_share: float = 0.33
    hasegawa_share: float = 0.39
    hirayama_share: float = 0.28
    retention90: float = 0.41


def axis_visit_shares(vt: Optional[pd.DataFrame] = None) -> Dict[str, float]:
    """受診件数ベースの隣の2院／それ以外シェア。"""
    from src.axis import AXIS_OTHER, AXIS_TOP2, HASEGAWA_ID, HIRAYAMA_ID, axis_from_clinic_id
    from src.io import read_csv

    if vt is None:
        vt = read_csv("visit_triangle")
    axis = axis_from_clinic_id(vt["クリニックID"])
    n = max(len(axis), 1)
    ids = vt["クリニックID"].astype(str)
    gate = float((axis == AXIS_TOP2).sum() / n)
    nongate = float((axis == AXIS_OTHER).sum() / n)
    n_patients = int(vt["患者ID"].nunique()) if "患者ID" in vt.columns else 0
    n_months = (
        int(pd.to_datetime(vt["受診日"]).dt.to_period("M").nunique())
        if "受診日" in vt.columns
        else 0
    )
    return {
        "gate_share": gate,
        "nongate_share": nongate,
        "hasegawa_share": float((ids == HASEGAWA_ID).sum() / n),
        "hirayama_share": float((ids == HIRAYAMA_ID).sum() / n),
        "unknown_share": float(max(0.0, 1.0 - gate - nongate)),
        "n_visits": int(len(axis)),
        "unique_patients": float(n_patients),
        "mean_visits_per_patient": float(len(vt) / n_patients) if n_patients else 0.0,
        "months": float(n_months),
    }


def growth_inputs_from_current(
    monthly_visits: float,
    target_monthly: float = 3000.0,
    vt: Optional[pd.DataFrame] = None,
) -> GrowthInputs:
    """現行データからシミュレータ入力を組む（隣の2院／それ以外）。"""
    shares = axis_visit_shares(vt)
    return GrowthInputs(
        monthly_visits=monthly_visits,
        target_monthly=target_monthly,
        unique_patients=shares["unique_patients"],
        months=shares["months"],
        mean_visits_per_patient=shares["mean_visits_per_patient"],
        gate_share=shares["gate_share"],
        nongate_share=shares["nongate_share"],
        hasegawa_share=shares["hasegawa_share"],
        hirayama_share=shares["hirayama_share"],
    )


def baseline_decomposition(inp: GrowthInputs) -> Dict[str, float]:
    """
    月間件数 ≈ 月間ユニーク来局 × 月あたり来局頻度 の近似分解。
    実測から逆算したベースラインを返す（因果モデルではない）。
    """
    monthly_unique_approx = inp.monthly_visits / max(inp.mean_visits_per_patient / (inp.months / 12.0), 1e-6)
    # より直感的な定常近似:
    # 月間件数 = 活動患者ストック × 月次来局率
    stock = inp.unique_patients
    monthly_rate = inp.monthly_visits / stock  # 患者あたり月間来局回数の粗い代理
    return {
        "monthly_visits": inp.monthly_visits,
        "target": inp.target_monthly,
        "gap_ratio": inp.target_monthly / inp.monthly_visits,
        "patient_stock": stock,
        "monthly_visits_per_patient": monthly_rate,
        "gate_visits": inp.monthly_visits * inp.gate_share,
        "nongate_visits": inp.monthly_visits * inp.nongate_share,
    }


def simulate_scenarios(inp: GrowthInputs) -> pd.DataFrame:
    """
    施策レバーを独立に動かしたときの到達月間件数（一次近似）。
    交互作用は無視。感度比較用。
    """
    base = inp.monthly_visits
    rows = []

    def add(name, visits, note):
        rows.append(
            {
                "シナリオ": name,
                "予測月間件数": visits,
                "対ベース倍率": visits / base,
                "目標3,000到達": visits >= inp.target_monthly,
                "注記": note,
            }
        )

    add("現状", base, "直近3か月平均")
    h = inp.hasegawa_share
    n = inp.nongate_share
    add("はせがわが1割減る", base * (1 - 0.10 * h), "2院依存のリスク。1院の1割で店全体が動く")
    add("はせがわが3割減る", base * (1 - 0.30 * h), "医師交代・移転などの最悪ケース")
    add("面が1.5倍になる", base * (1 + 0.50 * n), "2院以外の医院からの処方箋")
    # 再来 41%→50% の粗い増分（初回の約1割が余分に戻り、その後も通う）
    ret_lift = base * 0.06
    add("再来が41%から50%になる", base + ret_lift, "初回患者のうち戻る人が増える概算")
    combo = base * (1 + 0.50 * n) + ret_lift + 200
    add("面1.5倍＋再来50%＋内科2院（各100枚）", combo, "全部やっても目標との差が残る")

    return pd.DataFrame(rows)


def tornado_sensitivities(inp: GrowthInputs, pct: float = 0.1) -> pd.DataFrame:
    """各レバー ±pct の影響幅（トルネード用）。"""
    base = inp.monthly_visits
    levers = {
        "隣の2院": inp.gate_share,
        "それ以外": inp.nongate_share,
        "来局頻度": 1.0,
        "活動患者ストック": 1.0,
    }
    rows = []
    for name, w in levers.items():
        if name == "隣の2院":
            low = base * (1 - pct * inp.gate_share)
            high = base * (1 + pct * inp.gate_share)
        elif name == "それ以外":
            low = base * (1 - pct * inp.nongate_share)
            high = base * (1 + pct * inp.nongate_share)
        else:
            low = base * (1 - pct)
            high = base * (1 + pct)
        rows.append({"レバー": name, "低": low, "高": high, "振れ幅": high - low, "ベース": base})
    return pd.DataFrame(rows).sort_values("振れ幅", ascending=False)
