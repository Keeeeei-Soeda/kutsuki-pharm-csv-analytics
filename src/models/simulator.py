"""Growth Engine 分解シミュレータ（シナリオ感度）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np
import pandas as pd


@dataclass
class GrowthInputs:
    monthly_visits: float = 1388.0
    target_monthly: float = 3000.0
    unique_patients: float = 8885.0
    months: float = 23.0
    mean_visits_per_patient: float = 3.59
    gate_share: float = 0.893
    nongate_share: float = 0.096


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

    add("現状ベース", base, "実測平均")

    # 門前+5%（クリニック流量増の代理）
    add(
        "門前需要+10%",
        base * (1 + 0.10 * inp.gate_share),
        "軸A: 直近クリニック流量増。薬局施策の寄与は限定的",
    )
    add(
        "門前需要+20%",
        base * (1 + 0.20 * inp.gate_share),
        "軸A",
    )

    # 非門前を倍・3倍
    add(
        "非門前×2",
        base * (inp.gate_share + inp.nongate_share * 2 + (1 - inp.gate_share - inp.nongate_share)),
        "軸B: 面獲得の拡大",
    )
    add(
        "非門前×3",
        base * (inp.gate_share + inp.nongate_share * 3 + (1 - inp.gate_share - inp.nongate_share)),
        "軸B",
    )

    # 来局頻度（継続）+10/+20%
    add("来局頻度+10%", base * 1.10, "継続率・処方間隔の改善代理")
    add("来局頻度+20%", base * 1.20, "継続")

    # 新規流入（ストック増）
    add("活動患者+15%", base * 1.15, "新規獲得（門前+非門前合算）")
    add("活動患者+30%", base * 1.30, "新規獲得")

    # 組み合わせ例
    combo = base * (inp.gate_share * 1.05 + inp.nongate_share * 2.5 + (1 - inp.gate_share - inp.nongate_share)) * 1.10
    add("複合:門前+5%×非門前×2.5×頻度+10%", combo, "同時施策の粗い積")

    # 目標到達に必要な非門前倍率（他固定）
    # base * (g + n*m + u) = target  => m = (target/base - g - u) / n
    u = 1 - inp.gate_share - inp.nongate_share
    need_m = (inp.target_monthly / base - inp.gate_share - u) / max(inp.nongate_share, 1e-9)
    add(
        f"参考:非門前のみで目標→×{need_m:.1f}が必要",
        inp.target_monthly,
        "他条件一定のときの必要条件（実現可能性の目安）",
    )

    return pd.DataFrame(rows)


def tornado_sensitivities(inp: GrowthInputs, pct: float = 0.1) -> pd.DataFrame:
    """各レバー ±pct の影響幅（トルネード用）。"""
    base = inp.monthly_visits
    levers = {
        "門前需要": inp.gate_share,
        "非門前需要": inp.nongate_share,
        "来局頻度": 1.0,
        "活動患者ストック": 1.0,
    }
    rows = []
    for name, w in levers.items():
        if name == "門前需要":
            low = base * (1 - pct * inp.gate_share)
            high = base * (1 + pct * inp.gate_share)
        elif name == "非門前需要":
            low = base * (1 - pct * inp.nongate_share)
            high = base * (1 + pct * inp.nongate_share)
        else:
            low = base * (1 - pct)
            high = base * (1 + pct)
        rows.append({"レバー": name, "低": low, "高": high, "振れ幅": high - low, "ベース": base})
    return pd.DataFrame(rows).sort_values("振れ幅", ascending=False)
