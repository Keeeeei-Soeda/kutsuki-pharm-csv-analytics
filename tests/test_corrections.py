"""補正適用の安全性（キー指定のみ・全置換しない）を守るテスト。"""

import pandas as pd
import pytest

from src.corrections import (
    GATE_LINE_KM,
    Correction,
    CorrectionError,
    apply_corrections,
    load_corrections,
    rederive_gate,
    verify_key,
)
from src.io import read_csv


def _sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "クリニックID": ["C001", "C002", "C003"],
            "クリニック名": ["はせがわ耳鼻科", "平山皮フ科", "藤井クリニック"],
            "クリニック→薬局_道路km": [0.146, 0.044, 0.069],
        }
    )


def _corr(**kw) -> Correction:
    base = dict(
        id="t",
        target="clinic_master",
        column="クリニック→薬局_道路km",
        key={"クリニックID": "C001"},
        to=0.04,
        enabled=True,
    )
    base.update(kw)
    return Correction(**base)


def test_only_keyed_row_changes():
    df = _sample()
    out = apply_corrections(df, "clinic_master", [_corr()])
    assert out.loc[0, "クリニック→薬局_道路km"] == 0.04
    # 他のレコードは一切動かない（全置換の検出）
    assert out.loc[1, "クリニック→薬局_道路km"] == 0.044
    assert out.loc[2, "クリニック→薬局_道路km"] == 0.069
    # 元の DataFrame も書き換えない
    assert df.loc[0, "クリニック→薬局_道路km"] == 0.146


def test_disabled_correction_is_not_applied():
    df = _sample()
    out = apply_corrections(df, "clinic_master", [_corr(enabled=False)])
    assert out.loc[0, "クリニック→薬局_道路km"] == 0.146


def test_name_mismatch_raises():
    """ID の解釈違いを静かに通さない。"""
    with pytest.raises(CorrectionError):
        apply_corrections(
            _sample(), "clinic_master", [_corr(expect_name="平山皮フ科クリニック")]
        )


def test_missing_key_raises():
    with pytest.raises(CorrectionError):
        apply_corrections(_sample(), "clinic_master", [_corr(key={"クリニックID": "C999"})])


def test_rederive_gate_reproduces_raw_with_raw_threshold():
    """補正なし・生データの閾値なら、門前フラグと立地パターンは生データと一致する。"""
    raw = read_csv("visit_triangle", corrections=False)
    out = rederive_gate(raw, GATE_LINE_KM)
    assert out["立地パターン"].fillna("NA").equals(raw["立地パターン"].fillna("NA"))
    assert (out["門前フラグ"].astype(str).str.upper() == raw["門前フラグ"].astype(str).str.upper()).all()


def test_rederive_gate_moves_only_rows_beyond_threshold():
    raw = read_csv("visit_triangle", corrections=False)
    out = rederive_gate(raw, 0.04)
    km = pd.to_numeric(raw["クリニック→薬局_直線km"], errors="coerce")
    assert out.loc[km <= 0.04, "立地パターン"].dropna().eq("門前型").all()
    assert not out.loc[km > 0.04, "立地パターン"].eq("門前型").any()
    # もともと非門前の行は生データのまま
    was_non_gate = raw["立地パターン"].notna() & raw["立地パターン"].ne("門前型")
    assert out.loc[was_non_gate, "立地パターン"].equals(raw.loc[was_non_gate, "立地パターン"])


def test_config_keys_resolve_to_expected_clinics():
    """config/corrections.yaml のキーが実データの想定クリニックを指しているか。"""
    master = read_csv("clinic_master", corrections=False)
    for corr in load_corrections():
        actual = verify_key(master, corr, "clinic_master")
        assert actual, corr.describe()
        if corr.expect_name:
            assert corr.expect_name in actual, f"{corr.describe()} → {actual}"
