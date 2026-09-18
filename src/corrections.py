"""生データ補正の適用。

``data/raw/`` は読み取り専用のまま、``config/corrections.yaml`` の定義を
読み込み後の DataFrame に適用する（生データ + 補正定義 = 分析用データ）。

CLI::

    python3 -m src.corrections            # 影響レポートを生成
    python3 -m src.corrections --verify   # 名前突合だけ実行（適用しない）
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "corrections.yaml"
IMPACT_PATH = ROOT / "reports" / "correction_impact.md"

# 名前突合に使う列（クリニック系ファイル共通）
NAME_COLUMNS = ("クリニック名",)


class CorrectionError(RuntimeError):
    """補正定義が実データと噛み合っていないときに送出する。"""


@dataclass
class Correction:
    id: str
    target: str
    column: str
    key: Dict[str, object]
    to: object
    reason: str = ""
    expect_name: Optional[str] = None
    enabled: bool = False
    applied_at: Optional[str] = None
    propagate_to: List[str] = field(default_factory=list)

    @property
    def targets(self) -> List[str]:
        return [self.target, *self.propagate_to]

    def describe(self) -> str:
        keys = ", ".join(f"{k}={v}" for k, v in self.key.items())
        return f"[{self.id}] {keys} / {self.column} → {self.to}"


@dataclass
class AppliedChange:
    correction_id: str
    logical_name: str
    column: str
    key: Dict[str, object]
    before: object
    after: object
    n_rows: int


def load_corrections(path: Path = CONFIG_PATH) -> List[Correction]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for item in raw.get("corrections") or []:
        known = {f for f in Correction.__dataclass_fields__}
        unknown = set(item) - known
        if unknown:
            raise CorrectionError(f"未知のキー {sorted(unknown)} が corrections.yaml にあります")
        out.append(Correction(**item))
    return out


def _mask(df: pd.DataFrame, key: Dict[str, object]) -> pd.Series:
    mask = pd.Series(True, index=df.index)
    for col, value in key.items():
        if col not in df.columns:
            return pd.Series(False, index=df.index)
        mask &= df[col].astype(str).str.strip() == str(value)
    return mask


def verify_key(df: pd.DataFrame, corr: Correction, logical_name: str) -> str:
    """ID の解釈違いを防ぐため、キーがどのクリニック名に当たるかを返す。"""
    mask = _mask(df, corr.key)
    if not mask.any():
        raise CorrectionError(
            f"{corr.describe()}: {logical_name} に該当レコードがありません（キーの綴りを確認）"
        )
    names: Sequence[str] = []
    for col in NAME_COLUMNS:
        if col in df.columns:
            names = sorted(df.loc[mask, col].dropna().astype(str).unique())
            break
    actual = " / ".join(names) if len(names) else "(名前列なし)"
    if corr.expect_name and names and corr.expect_name not in names:
        raise CorrectionError(
            f"{corr.describe()}: {logical_name} のキーは「{actual}」を指しています。"
            f"期待した「{corr.expect_name}」と一致しません。ID の解釈を確認してください。"
        )
    return actual


def apply_corrections(
    df: pd.DataFrame,
    logical_name: str,
    corrections: Optional[Sequence[Correction]] = None,
    *,
    log: Optional[List[AppliedChange]] = None,
    force: bool = False,
) -> pd.DataFrame:
    """``logical_name`` に対する有効な補正を当てた **コピー** を返す。

    ``force=True`` のときは enabled が false の定義も当てる（影響試算用）。
    """
    corrections = load_corrections() if corrections is None else corrections
    relevant = [
        c for c in corrections if logical_name in c.targets and (c.enabled or force)
    ]
    if not relevant:
        return df

    out = df.copy()
    for corr in relevant:
        if corr.column not in out.columns:
            continue
        verify_key(out, corr, logical_name)
        mask = _mask(out, corr.key)
        before = out.loc[mask, corr.column]
        before_value = before.dropna().unique()
        # キー指定の該当行のみ更新（全置換は行わない）
        out.loc[mask, corr.column] = corr.to
        if log is not None:
            log.append(
                AppliedChange(
                    correction_id=corr.id,
                    logical_name=logical_name,
                    column=corr.column,
                    key=dict(corr.key),
                    before=before_value[0] if len(before_value) == 1 else list(before_value),
                    after=corr.to,
                    n_rows=int(mask.sum()),
                )
            )
    return out


# --------------------------------------------------------------------------
# 影響レポート
# --------------------------------------------------------------------------

GATE_LINE_KM = 0.3  # 門前判定（直線km）。config/economics.yaml の gate_distance_km と対。


def _gate_counts(vt: pd.DataFrame) -> Dict[str, int]:
    counts = vt["立地パターン"].astype(str).value_counts(dropna=False).to_dict()
    flag = vt["門前フラグ"].astype(str).str.upper().value_counts(dropna=False).to_dict()
    return {f"立地パターン:{k}": int(v) for k, v in counts.items()} | {
        f"門前フラグ:{k}": int(v) for k, v in flag.items()
    }


def _road_gate_counts(df: pd.DataFrame, column: str) -> Dict[str, int]:
    km = pd.to_numeric(df[column], errors="coerce")
    return {
        f"{column}<=0.3km": int((km <= GATE_LINE_KM).sum()),
        f"{column}>0.3km": int((km > GATE_LINE_KM).sum()),
        f"{column}欠損": int(km.isna().sum()),
    }


def _distance_coef(vt: pd.DataFrame) -> Optional[float]:
    """距離を説明変数に含む単純モデルの係数（クリニック単位の件数 ~ 道路km）。"""
    import numpy as np

    agg = (
        vt.assign(km=pd.to_numeric(vt["クリニック→薬局_道路km"], errors="coerce"))
        .groupby("クリニックID", dropna=True)
        .agg(件数=("受診ID", "size"), km=("km", "median"))
        .dropna()
    )
    agg = agg[agg["件数"] > 0]
    if len(agg) < 3:
        return None
    x = np.log1p(agg["km"].to_numpy(dtype=float))
    y = np.log(agg["件数"].to_numpy(dtype=float))
    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def _fmt(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def build_impact_report(path: Path = IMPACT_PATH, *, force: bool = False) -> Path:
    """補正前後の比較を ``reports/correction_impact.md`` に書き出す。"""
    from src.io import read_csv

    corrections = load_corrections()
    active = [c for c in corrections if c.enabled or force]

    lines: List[str] = [
        "# 補正の影響",
        "",
        f"生成: {date.today().isoformat()}  ",
        f"定義: `config/corrections.yaml`（全 {len(corrections)} 件 / 今回反映 {len(active)} 件）",
        "",
    ]

    if not corrections:
        lines += ["補正定義がありません。", ""]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # 1) 定義一覧と名前突合
    lines += ["## 1. 補正定義とキーの突合", "", "| ID | 対象 | キー | 列 | → | 状態 | キーが指すクリニック |", "|---|---|---|---|---|---|---|"]
    master = read_csv("clinic_master", corrections=False)
    for corr in corrections:
        try:
            actual = verify_key(master, corr, "clinic_master")
        except CorrectionError as exc:  # 突合エラーは落とさず表に出す
            actual = f"**要確認: {exc}**"
        state = "適用" if corr.enabled else ("試算のみ" if force else "未適用")
        keys = ", ".join(f"{k}={v}" for k, v in corr.key.items())
        lines.append(
            f"| {corr.id} | {corr.target} | {keys} | {corr.column} | {corr.to} | {state} | {actual} |"
        )
    lines.append("")

    if not active:
        lines += [
            "## 2. 変化",
            "",
            "**変化なし。** 有効化された補正がありません（すべて `enabled: false`）。",
            "北川氏のテキスト到着後に `enabled: true` にして再実行してください。",
            "",
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    # 2) 実際に書き換わったレコード
    changes: List[AppliedChange] = []
    vt_before = read_csv("visit_triangle", corrections=False)
    cm_before = read_csv("clinic_master", corrections=False)
    vt_after = apply_corrections(vt_before, "visit_triangle", corrections, log=changes, force=force)
    cm_after = apply_corrections(cm_before, "clinic_master", corrections, log=changes, force=force)

    lines += ["## 2. 書き換わったレコード", "", "| 補正ID | ファイル | 列 | 前 | 後 | 行数 |", "|---|---|---|---|---|---|"]
    for ch in changes:
        lines.append(
            f"| {ch.correction_id} | {ch.logical_name} | {ch.column} | "
            f"{_fmt(ch.before)} | {_fmt(ch.after)} | {ch.n_rows:,} |"
        )
    lines.append("")

    # 3) 門前フラグ・立地パターンの件数変化
    lines += ["## 3. 門前フラグ・立地パターンの件数変化", ""]
    before_counts = _gate_counts(vt_before) | _road_gate_counts(vt_before, "クリニック→薬局_道路km")
    after_counts = _gate_counts(vt_after) | _road_gate_counts(vt_after, "クリニック→薬局_道路km")
    diffs = {k: (before_counts.get(k, 0), after_counts.get(k, 0)) for k in sorted(set(before_counts) | set(after_counts))}
    changed = {k: v for k, v in diffs.items() if v[0] != v[1]}
    if changed:
        lines += ["| 区分 | 補正前 | 補正後 | 差 |", "|---|---|---|---|"]
        for k, (b, a) in changed.items():
            lines.append(f"| {k} | {b:,} | {a:,} | {a - b:+,} |")
    else:
        lines.append(
            "**変化なし。** 立地パターン・門前フラグは visit_triangle に実体値として "
            "格納済みで、道路km の補正では再計算されません（再計算が必要なら派生列の "
            "再生成が別途必要）。"
        )
    lines.append("")

    # 4) 距離を説明変数に含むモデルの係数変化
    lines += ["## 4. 距離を説明変数に含むモデルの係数変化", "",
              "log(件数) ~ log1p(クリニック→薬局_道路km) の単回帰（クリニック単位）。", ""]
    b = _distance_coef(vt_before)
    a = _distance_coef(vt_after)
    if b is None or a is None:
        lines.append("係数を推定できませんでした（サンプル不足）。")
    elif abs(a - b) < 1e-9:
        lines.append(f"**変化なし。** 係数 {b:.4f}（補正前後で同一）。")
    else:
        lines += ["| | 補正前 | 補正後 | 差 |", "|---|---|---|---|",
                  f"| 距離係数 | {b:.4f} | {a:.4f} | {a - b:+.4f} |"]
    lines.append("")

    # 5) clinic_master 側の該当行
    lines += ["## 5. clinic_master の該当行", "", "| クリニックID | クリニック名 | 補正前 | 補正後 |", "|---|---|---|---|"]
    for corr in active:
        mask = _mask(cm_before, corr.key)
        for idx in cm_before.index[mask]:
            lines.append(
                f"| {cm_before.loc[idx, 'クリニックID']} | {cm_before.loc[idx, 'クリニック名']} | "
                f"{cm_before.loc[idx, corr.column]} | {cm_after.loc[idx, corr.column]} |"
            )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="補正の適用と影響レポート生成")
    parser.add_argument("--verify", action="store_true", help="名前突合のみ（適用しない）")
    parser.add_argument(
        "--force", action="store_true",
        help="enabled: false の定義も当てて影響を試算する（ファイルは書き換えない）",
    )
    args = parser.parse_args()

    corrections = load_corrections()
    if args.verify:
        from src.io import read_csv

        master = read_csv("clinic_master", corrections=False)
        for corr in corrections:
            print(f"{corr.describe()} → {verify_key(master, corr, 'clinic_master')}")
        return

    out = build_impact_report(force=args.force)
    print("wrote", out)


if __name__ == "__main__":
    main()
