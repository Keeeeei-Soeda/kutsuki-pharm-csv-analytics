"""表示軸「隣の2院／それ以外」。門前フラグとは独立。"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence, Tuple

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
_CFG = yaml.safe_load((ROOT / "config" / "clinics.yaml").read_text(encoding="utf-8")) or {}

TOP2_IDS: Tuple[str, ...] = tuple(str(x) for x in _CFG.get("top2_clinic_ids", ["C001", "C002"]))
HASEGAWA_ID = str(_CFG.get("hasegawa_id", "C001"))
HIRAYAMA_ID = str(_CFG.get("hirayama_id", "C002"))
AXIS_TOP2 = str(_CFG.get("axis_top2", "隣の2院"))
AXIS_OTHER = str(_CFG.get("axis_other", "それ以外"))
AXIS_UNKNOWN = str(_CFG.get("axis_unknown", "不明"))
AXES: Sequence[str] = (AXIS_TOP2, AXIS_OTHER, AXIS_UNKNOWN)
AXIS_PLAIN = {AXIS_TOP2: "隣の2院", AXIS_OTHER: "それ以外の医院", AXIS_UNKNOWN: "不明"}


def axis_from_clinic_id(clinic_id: pd.Series) -> pd.Series:
    ids = clinic_id.astype(str)
    known = clinic_id.notna() & ~ids.isin(["", "nan", "None", "<NA>"])
    return pd.Series(
        np.select(
            [ids.isin(TOP2_IDS), known.to_numpy()],
            [AXIS_TOP2, AXIS_OTHER],
            default=AXIS_UNKNOWN,
        ),
        index=clinic_id.index,
    )


def is_top2(clinic_id: pd.Series) -> pd.Series:
    return clinic_id.astype(str).isin(TOP2_IDS)
