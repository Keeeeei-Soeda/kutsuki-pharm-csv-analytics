"""診療科フリーテキストの標準タキソノミーへのマルチラベル正規化。

``visit_triangle`` / ``clinic_master`` の ``診療科`` は 258 種のフリーテキストで、
そのまま集計すると遷移行列が散らばって読めない。ここでは

    1. 区切り文字でトークンに割る
    2. トークンごとに標準ラベルへ写像（1トークン→複数ラベル可）
    3. クリニック単位でラベル集合と「主科」を決める

という順で正規化し、結果を ``data/processed/specialty_map.csv`` に人手レビュー
できる形で書き出す。主科は**先頭トークンのラベル**とする（標榜順の先頭が
その施設の主たる診療科という慣行に従う）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pandas as pd

STANDARD_LABELS = [
    "内科",
    "小児科",
    "耳鼻咽喉科",
    "皮膚科",
    "整形外科",
    "眼科",
    "精神科",
    "産婦人科",
    "外科",
    "泌尿器科",
    "歯科",
    "リハビリテーション科",
    "その他",
]

SPLIT_RE = re.compile(r"[・,、/／\s]+")
# 「ほか（総合病院）」「29診療科10センター）」のような注記を落とす
NOISE_RE = re.compile(r"[（(].*?[）)]|ほか|など|等")

# トークン → 標準ラベル（複数可）。上から順に「完全一致」→「部分一致」で当てる。
EXACT_RULES: Dict[str, Tuple[str, ...]] = {
    "小児外科": ("小児科", "外科"),
    "小児整形外科": ("小児科", "整形外科"),
    "小児皮膚科": ("小児科", "皮膚科"),
    "小児眼科": ("小児科", "眼科"),
    "小児歯科": ("小児科", "歯科"),
    "小児循環器": ("小児科", "内科"),
    "小児循環器内科": ("小児科", "内科"),
    "児童精神科": ("小児科", "精神科"),
    "女性内科": ("内科",),
    "甲状腺": ("内科",),
    "アレルギー科": ("その他",),
    "性病科": ("その他",),
    "海外渡航外来": ("その他",),
    "ペインクリニック": ("その他",),
    "救急科": ("その他",),
    "病理診断科": ("その他",),
    "麻酔科": ("その他",),
    "全診療科": ("その他",),
}

# 部分一致ルール（長いものから順に評価する）
SUBSTRING_RULES: Sequence[Tuple[str, Tuple[str, ...]]] = (
    ("歯科", ("歯科",)),
    ("耳鼻", ("耳鼻咽喉科",)),
    ("皮膚", ("皮膚科",)),
    ("眼科", ("眼科",)),
    ("整形外科", ("整形外科",)),
    ("手外科", ("整形外科",)),
    ("リウマチ", ("整形外科",)),
    ("リハビリテーション", ("リハビリテーション科",)),
    ("心療内科", ("精神科",)),
    ("精神", ("精神科",)),
    ("神経科", ("精神科",)),
    ("産科", ("産婦人科",)),
    ("婦人科", ("産婦人科",)),
    ("泌尿器", ("泌尿器科",)),
    ("小児", ("小児科",)),
    ("放射線", ("その他",)),
    ("緩和ケア", ("その他",)),
    ("内科", ("内科",)),       # 〜内科 はすべて内科系（脳神経内科・糖尿病内科など）
    ("総合診療", ("内科",)),
    ("外科", ("外科",)),       # 内科判定のあと。消化器外科・脳神経外科などを外科へ
    ("センター", ("その他",)),
)

# 「急性期 → 慢性期」の読み筋で使う区分
ACUTE_LABELS = ("耳鼻咽喉科", "皮膚科")
CHRONIC_LABELS = ("内科",)


def normalize_token(token: str) -> Tuple[str, ...]:
    """1トークンを標準ラベルの組に写像する。"""
    t = NOISE_RE.sub("", token).strip()
    if not t:
        return ()
    if t in EXACT_RULES:
        return EXACT_RULES[t]
    for needle, labels in SUBSTRING_RULES:
        if needle in t:
            return labels
    return ("その他",)


def split_tokens(text: object) -> List[str]:
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    return [t for t in SPLIT_RE.split(str(text)) if t.strip()]


def normalize_text(text: object) -> Tuple[List[str], str]:
    """フリーテキスト → (ラベル集合, 主科)。主科は先頭トークンのラベル。"""
    tokens = split_tokens(text)
    labels: List[str] = []
    for tok in tokens:
        for lab in normalize_token(tok):
            if lab not in labels:
                labels.append(lab)
    if not labels:
        return [], "不明"
    primary_candidates = normalize_token(tokens[0]) if tokens else ()
    primary = primary_candidates[0] if primary_candidates else labels[0]
    return labels, primary


# 施設名から診療科が読み取れる語（診療科列が空のときだけ使う補助）
NAME_HINTS: Sequence[Tuple[str, str]] = (
    ("耳鼻", "耳鼻咽喉科"),
    ("歯科", "歯科"),
    ("皮フ", "皮膚科"),
    ("皮膚", "皮膚科"),
    ("眼科", "眼科"),
    ("整形", "整形外科"),
    ("産婦人", "産婦人科"),
    ("泌尿", "泌尿器科"),
    ("こども", "小児科"),
    ("小児", "小児科"),
    ("内科", "内科"),
)


def infer_from_name(name: object) -> str:
    """診療科列が空のときに施設名から推定する。判断できなければ空文字。"""
    s = str(name or "")
    for needle, label in NAME_HINTS:
        if needle in s:
            return label
    return ""


def build_specialty_map(clinics: pd.DataFrame) -> pd.DataFrame:
    """クリニック単位の正規化表を作る（人手レビュー用）。"""
    rows = []
    for _, r in clinics.iterrows():
        raw = r.get("診療科")
        labels, primary = normalize_text(raw)
        source = "診療科列"
        if not labels:
            guessed = infer_from_name(r.get("クリニック名"))
            if guessed:
                labels, primary, source = [guessed], guessed, "名称推定"
            else:
                source = "なし"
        rows.append(
            {
                "クリニックID": r.get("クリニックID"),
                "クリニック名": r.get("クリニック名"),
                "診療科_原文": raw,
                "推定根拠": source,
                "トークン数": len(split_tokens(raw)),
                "標準ラベル": "|".join(labels),
                "主科": primary,
                "複数科": len(labels) > 1,
                "種別": r.get("種別"),
                "要レビュー": ("その他" in labels and len(labels) == 1)
                or primary == "不明"
                or source != "診療科列",
            }
        )
    out = pd.DataFrame(rows)
    for lab in STANDARD_LABELS:
        out[f"is_{lab}"] = out["標準ラベル"].fillna("").str.split("|").apply(lambda xs: lab in xs)
    return out


def write_specialty_map(clinics: pd.DataFrame, path: Path) -> Path:
    df = build_specialty_map(clinics)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
