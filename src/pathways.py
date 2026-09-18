"""来院経路の時系列追跡（患者IDで初回→2〜4回目を辿る）。

クリニック単位と診療科単位の両方で受診シーケンスを組み、
診療科遷移サンキー・遷移行列・同一科リピート率・実経路上位を出力する。

``python3 -m src.pathways``
"""

from __future__ import annotations

import json
import shutil
from html import escape
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.io import PHARMACY_NAME, PROCESSED_DIR, ROOT, ensure_dirs, read_csv
from src.specialty_taxonomy import (
    ACUTE_LABELS,
    CHRONIC_LABELS,
    STANDARD_LABELS,
    build_specialty_map,
)
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

MAX_STEP = 4  # 初回〜4回目
UNKNOWN = "不明"

PALETTE = {
    "内科": "#2f6f9f",
    "小児科": "#6aa84f",
    "耳鼻咽喉科": "#c45c26",
    "皮膚科": "#b5651d",
    "整形外科": "#7b5ea7",
    "眼科": "#0f8a8a",
    "精神科": "#8a6d3b",
    "産婦人科": "#c0587e",
    "外科": "#5c6675",
    "泌尿器科": "#3f7d6d",
    "歯科": "#9a8f7c",
    "リハビリテーション科": "#88a0b5",
    "その他": "#b9b1a2",
    UNKNOWN: "#d9d2c5",
}


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


# --------------------------------------------------------------------------
# 1. シーケンス構築
# --------------------------------------------------------------------------


def load_sequences() -> Dict[str, pd.DataFrame]:
    """受診をクリニック単位・診療科単位のシーケンスに整形する。"""
    vt = read_csv("visit_triangle")
    clinics = read_csv("clinic_master")
    smap = build_specialty_map(clinics)

    vt = vt.dropna(subset=["患者ID", "受診日"]).copy()
    vt["受診日"] = pd.to_datetime(vt["受診日"], errors="coerce")
    vt = vt.dropna(subset=["受診日"])
    vt = vt.merge(
        smap[["クリニックID", "主科", "標準ラベル", "クリニック名"]].rename(
            columns={"クリニック名": "科名寄せ用クリニック名"}
        ),
        on="クリニックID",
        how="left",
    )
    vt["主科"] = vt["主科"].fillna(UNKNOWN).replace("", UNKNOWN)

    # 受診日 → 受診ID の順で通番を振る（同日複数受診も一意に並ぶ）
    vt = vt.sort_values(["患者ID", "受診日", "受診ID"], kind="mergesort")
    vt["受診順"] = vt.groupby("患者ID").cumcount() + 1

    counts = vt.groupby("患者ID").size().rename("総受診回数")
    vt = vt.merge(counts, on="患者ID", how="left")
    return {"visits": vt, "specialty_map": smap}


def step_table(visits: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """患者 × n回目 のワイド表（n=1..MAX_STEP）。"""
    sub = visits[visits["受診順"] <= MAX_STEP]
    wide = sub.pivot_table(
        index="患者ID", columns="受診順", values=value_col, aggfunc="first"
    )
    wide.columns = [f"{c}回目" for c in wide.columns]
    return wide


# --------------------------------------------------------------------------
# 2. 基本統計
# --------------------------------------------------------------------------


def base_stats(visits: pd.DataFrame) -> Dict[str, object]:
    per_patient = visits.groupby("患者ID")["受診順"].max()
    n_patients = int(len(per_patient))
    dist = per_patient.value_counts().sort_index()
    single = int((per_patient == 1).sum())
    return {
        "n_visits": int(len(visits)),
        "n_patients": n_patients,
        "single_visit_n": single,
        "single_visit_share": single / n_patients if n_patients else float("nan"),
        "reached_2": int((per_patient >= 2).sum()),
        "reached_3": int((per_patient >= 3).sum()),
        "reached_4": int((per_patient >= 4).sum()),
        "visit_count_dist": {int(k): int(v) for k, v in dist.head(10).items()},
        "median_visits": float(per_patient.median()),
        "unknown_specialty_visits": int((visits["主科"] == UNKNOWN).sum()),
    }


# --------------------------------------------------------------------------
# 3. 遷移行列
# --------------------------------------------------------------------------


def transition_pairs(wide: pd.DataFrame, step: int) -> pd.DataFrame:
    """n回目→n+1回目のペア（両方存在する患者のみ）。"""
    a, b = f"{step}回目", f"{step + 1}回目"
    if a not in wide.columns or b not in wide.columns:
        return pd.DataFrame(columns=["from", "to"])
    pairs = wide[[a, b]].dropna()
    pairs.columns = ["from", "to"]
    return pairs


def transition_matrix(pairs: pd.DataFrame, labels: List[str]) -> pd.DataFrame:
    mat = pd.crosstab(pairs["from"], pairs["to"])
    return mat.reindex(index=labels, columns=labels, fill_value=0)


def pooled_transitions(wide: pd.DataFrame) -> pd.DataFrame:
    frames = [transition_pairs(wide, s) for s in range(1, MAX_STEP)]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["from", "to"])


def present_labels(wide: pd.DataFrame) -> List[str]:
    seen = pd.unique(wide.values.ravel())
    seen = {s for s in seen if isinstance(s, str)}
    ordered = [lab for lab in STANDARD_LABELS if lab in seen]
    ordered += sorted(seen - set(ordered))
    return ordered


# --------------------------------------------------------------------------
# 4. 図
# --------------------------------------------------------------------------


def fig_transition_heatmap(pairs: pd.DataFrame, labels: List[str]) -> Path:
    _setup_font()
    mat = transition_matrix(pairs, labels)
    row_sum = mat.sum(axis=1).replace(0, np.nan)
    share = mat.div(row_sum, axis=0)

    fig, ax = plt.subplots(figsize=(9.5, 8))
    im = ax.imshow(share.to_numpy(dtype=float), cmap="YlGnBu", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(
        [f"{lab} (n={int(mat.loc[lab].sum()):,})" for lab in labels], fontsize=9
    )
    for i, lab in enumerate(labels):
        for j, lab2 in enumerate(labels):
            v = share.iloc[i, j]
            if pd.notna(v) and v >= 0.03:
                ax.text(
                    j, i, f"{v:.0%}", ha="center", va="center", fontsize=7.5,
                    color="#fff" if v > 0.55 else "#1c2430",
                )
    ax.set_xlabel("n+1回目の診療科")
    ax.set_ylabel("n回目の診療科")
    ax.set_title(
        f"診療科の遷移行列（行=n回目、列=n+1回目・行内構成比）\n"
        f"{PHARMACY_NAME} / n=1〜3 をプール N={len(pairs):,}"
    )
    fig.colorbar(im, ax=ax, fraction=0.035, label="行内構成比")
    fig.tight_layout()
    out = FIGURES / "pathways_transition_heatmap.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig_repeat_rate(pairs: pd.DataFrame, labels: List[str]) -> Tuple[Path, pd.DataFrame]:
    _setup_font()
    rows = []
    for lab in labels:
        sub = pairs[pairs["from"] == lab]
        if len(sub) < 20:  # 少数科は率が不安定なので図から外す
            continue
        same = float((sub["to"] == lab).mean())
        rows.append({"診療科": lab, "同一科リピート率": same, "診療科変更率": 1 - same, "N": len(sub)})
    tbl = pd.DataFrame(rows).sort_values("同一科リピート率", ascending=False)

    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    y = np.arange(len(tbl))
    ax.barh(y, tbl["同一科リピート率"], color="#0f6a6a", label="同一科リピート")
    ax.barh(
        y, tbl["診療科変更率"], left=tbl["同一科リピート率"], color="#c45c26", label="診療科変更"
    )
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.診療科} (N={r.N:,})" for r in tbl.itertuples()], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlim(0, 1)
    ax.set_xlabel("次回受診の構成比")
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1))
    for i, r in enumerate(tbl.itertuples()):
        ax.text(r.同一科リピート率 / 2, i, f"{r.同一科リピート率:.0%}", ha="center", va="center",
                color="#fff", fontsize=9)
    ax.set_title(
        f"同一診療科リピート率 vs 診療科変更率（n回目→n+1回目）\n"
        f"{PHARMACY_NAME} / N={len(pairs):,}・N<20の科は非表示"
    )
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=2, frameon=False, fontsize=9)
    fig.tight_layout()
    out = FIGURES / "pathways_repeat_rate.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out, tbl


def fig_acute_to_chronic(wide: pd.DataFrame, spread: Dict[str, object]) -> Path:
    _setup_font()
    tbl = pd.DataFrame([r for r in spread["by_first"] if r["区分"] != "初回から内科系（参考）"])
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    y = np.arange(len(tbl))
    ax.barh(y, tbl["内科到達率"], color=["#c45c26" if a else "#2f6f9f" for a in tbl["急性期"]])
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r.初回診療科} (N={r.N:,})" for r in tbl.itertuples()], fontsize=9)
    ax.invert_yaxis()
    ax.axvline(spread["overall_rate"], color="#1c2430", ls="--", lw=1.2)
    ax.annotate(
        f"初回内科系を除く全体 {spread['overall_rate']:.1%}",
        xy=(spread["overall_rate"], 0.02), xycoords=("data", "axes fraction"),
        xytext=(6, 0), textcoords="offset points",
        fontsize=9, color="#1c2430", va="bottom", ha="left",
    )
    for i, r in enumerate(tbl.itertuples()):
        ax.text(r.内科到達率 + 0.008, i, f"{r.内科到達率:.1%}", va="center", fontsize=9)
    ax.set_xlabel("2〜4回目のいずれかで内科系に到達した患者の割合")
    ax.set_xlim(0, max(0.35, float(tbl["内科到達率"].max()) * 1.30))
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(xmax=1))
    ax.set_title(
        "初回診療科別・内科系への広がり（2回目以降が存在する患者に限定）\n"
        f"{PHARMACY_NAME} ／ 橙=急性期（耳鼻咽喉科・皮膚科）／ 初回が内科系の患者は除外"
    )
    fig.tight_layout()
    out = FIGURES / "pathways_acute_to_chronic.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig_sankey(wide: pd.DataFrame, labels: List[str]) -> Path:
    """1回目→2回目→3回目の診療科サンキー（Plotly CDN、Python依存なし）。"""
    cols = ["1回目", "2回目", "3回目"]
    have = [c for c in cols if c in wide.columns]
    sub = wide[have].dropna()
    nodes: List[str] = []
    node_color: List[str] = []
    index: Dict[Tuple[int, str], int] = {}
    for depth, col in enumerate(have):
        for lab in labels:
            if (sub[col] == lab).any():
                index[(depth, lab)] = len(nodes)
                nodes.append(f"{col} {lab}")
                node_color.append(PALETTE.get(lab, "#b9b1a2"))

    src, dst, val, link_color = [], [], [], []
    for depth in range(len(have) - 1):
        pair = sub[[have[depth], have[depth + 1]]]
        pair.columns = ["a", "b"]
        for (a, b), n in pair.groupby(["a", "b"]).size().items():
            if (depth, a) in index and (depth + 1, b) in index:
                src.append(index[(depth, a)])
                dst.append(index[(depth + 1, b)])
                val.append(int(n))
                rgb = PALETTE.get(a, "#b9b1a2").lstrip("#")
                link_color.append(
                    "rgba(%d,%d,%d,0.38)" % tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4))
                )

    html = f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>来院経路 Sankey - {escape(PHARMACY_NAME)}</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>body{{font-family:"Hiragino Sans",sans-serif;margin:16px;color:#1c2430}}</style>
</head><body>
<h2>診療科の遷移（1回目 → 2回目 → 3回目） N={len(sub):,}人</h2>
<p>注: 3回目まで到達した患者に限定。診療科は標準タキソノミーへ正規化した主科。</p>
<div id="sankey" style="width:100%;height:720px;"></div>
<script>
var data=[{{type:"sankey",orientation:"h",
 node:{{pad:14,thickness:16,line:{{color:"#d9d2c5",width:1}},
        label:{json.dumps(nodes, ensure_ascii=False)},
        color:{json.dumps(node_color)}}},
 link:{{source:{json.dumps(src)},target:{json.dumps(dst)},value:{json.dumps(val)},
        color:{json.dumps(link_color)}}}}}];
Plotly.newPlot("sankey",data,{{font:{{family:"Hiragino Sans, sans-serif",size:12}}}},{{responsive:true}});
</script>
</body></html>
"""
    out = FIGURES / "pathways_sankey.html"
    out.write_text(html, encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# 5. 読み筋（急性期 → 慢性期）
# --------------------------------------------------------------------------


def acute_to_chronic(wide: pd.DataFrame) -> Dict[str, object]:
    """初回が急性期科の患者が、2〜4回目で内科系に広がっているか。"""
    later_cols = [c for c in ["2回目", "3回目", "4回目"] if c in wide.columns]
    have_second = wide[wide["2回目"].notna()] if "2回目" in wide.columns else wide.iloc[0:0]
    reach = have_second[later_cols].apply(
        lambda row: any(v in CHRONIC_LABELS for v in row.dropna()), axis=1
    )

    rows = []
    for lab in present_labels(wide):
        mask = have_second["1回目"] == lab
        n = int(mask.sum())
        if n < 30:
            continue
        rows.append(
            {
                "初回診療科": lab,
                "N": n,
                "内科到達率": float(reach[mask].mean()),
                "急性期": lab in ACUTE_LABELS,
                "区分": "急性期" if lab in ACUTE_LABELS
                else ("初回から内科系（参考）" if lab in CHRONIC_LABELS else "その他の科"),
            }
        )
    rows.sort(key=lambda r: r["内科到達率"], reverse=True)

    acute_mask = have_second["1回目"].isin(ACUTE_LABELS)
    # 初回が既に内科系の患者は「広がり」の対象外（同一科リピートで自動的に到達するため、
    # これを比較群に混ぜると他科側の到達率が機械的に跳ね上がる）
    chronic_first = have_second["1回目"].isin(CHRONIC_LABELS)
    other_mask = ~acute_mask & ~chronic_first

    acute_rate = float(reach[acute_mask].mean()) if acute_mask.any() else float("nan")
    other_rate = float(reach[other_mask].mean()) if other_mask.any() else float("nan")
    # 破線に使う「全体」は初回内科系を除いた母数（図の対象と定義を揃える）
    overall = float(reach[~chronic_first].mean()) if (~chronic_first).any() else float("nan")

    # 2回目だけを見た素の遷移率（リフト計算用）。初回内科の患者は除く。
    eligible = have_second[~chronic_first]
    second = eligible["2回目"]
    second_chronic = float(second.isin(CHRONIC_LABELS).mean()) if len(second) else float("nan")
    acute_second = have_second.loc[acute_mask, "2回目"]
    acute_second_chronic = (
        float(acute_second.isin(CHRONIC_LABELS).mean()) if len(acute_second) else float("nan")
    )
    return {
        "by_first": rows,
        "overall_rate": overall,
        "acute_rate": acute_rate,
        "other_rate": other_rate,
        "n_acute": int(acute_mask.sum()),
        "n_other": int(other_mask.sum()),
        "lift": acute_rate / other_rate if other_rate else float("nan"),
        "second_chronic_rate": second_chronic,
        "acute_second_chronic_rate": acute_second_chronic,
        "second_lift": acute_second_chronic / second_chronic if second_chronic else float("nan"),
        "n_with_second": int(len(have_second)),
    }


def top_paths(wide: pd.DataFrame, n: int = 20) -> pd.DataFrame:
    cols = [c for c in ["1回目", "2回目", "3回目"] if c in wide.columns]
    sub = wide[cols].dropna()
    if not len(sub):
        return pd.DataFrame(columns=["経路", "件数", "構成比"])
    grp = sub.groupby(cols).size().sort_values(ascending=False)
    total = int(grp.sum())
    rows = [
        {"経路": " → ".join(str(x) for x in (k if isinstance(k, tuple) else (k,))),
         "件数": int(v), "構成比": v / total}
        for k, v in grp.head(n).items()
    ]
    out = pd.DataFrame(rows)
    out.attrs["total"] = total
    return out


# --------------------------------------------------------------------------
# 6. レポート
# --------------------------------------------------------------------------


def write_report(ctx: Dict[str, object]) -> Path:
    stats = ctx["stats"]
    spread = ctx["spread"]
    repeat = ctx["repeat_tbl"]
    paths_sp = ctx["top_paths_specialty"]
    paths_cl = ctx["top_paths_clinic"]

    rep = HtmlReport(
        title="来院経路の時系列追跡",
        subtitle="患者IDで初回から2〜4回目までを辿り、診療科間の流れを見る。急性期（耳鼻咽喉科・皮膚科）が内科系へ広がっているかが継続率の鍵。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / 来院経路",
        nav_key="pathways",
    )
    rep.add_kpi("単発患者", f"{stats['single_visit_share']:.1%}",
                f"{stats['single_visit_n']:,} / {stats['n_patients']:,}人")
    rep.add_kpi("2回目到達", f"{stats['reached_2'] / stats['n_patients']:.1%}",
                f"3回目 {stats['reached_3'] / stats['n_patients']:.1%} / 4回目 {stats['reached_4'] / stats['n_patients']:.1%}")
    rep.add_kpi("内科系への到達", f"{spread['acute_rate']:.1%}",
                f"急性期初回 {spread['n_acute']:,}人が母数")
    rep.add_kpi("同一科リピート",
                f"{ctx['overall_same_rate']:.1%}",
                f"n→n+1 の全遷移 N={ctx['n_transitions']:,}")

    rep.callout(
        "結論",
        [
            ctx["headline"],
            f"母数注記: 2回目以降が存在しない単発患者が {stats['single_visit_share']:.1%}"
            f"（{stats['single_visit_n']:,}人）。以降の遷移率はすべて 2回目以降が存在する "
            f"{spread['n_with_second']:,}人 が母数。",
            f"同一診療科リピートが {ctx['overall_same_rate']:.1%} を占め、"
            f"診療科変更は {1 - ctx['overall_same_rate']:.1%}。来局の大半は同じ科の再受診。",
        ],
        kind="ok",
    )

    rep.section("base", "1. 母数と到達状況",
                "遷移率を読む前に、そもそも何人が2回目以降に到達しているかを示す。")
    rep.table(
        ["区分", "人数", "全患者に対する割合"],
        [
            ["全患者", f"{stats['n_patients']:,}", "100.0%"],
            ["単発（1回のみ）", f"{stats['single_visit_n']:,}", f"{stats['single_visit_share']:.1%}"],
            ["2回目に到達", f"{stats['reached_2']:,}", f"{stats['reached_2'] / stats['n_patients']:.1%}"],
            ["3回目に到達", f"{stats['reached_3']:,}", f"{stats['reached_3'] / stats['n_patients']:.1%}"],
            ["4回目に到達", f"{stats['reached_4']:,}", f"{stats['reached_4'] / stats['n_patients']:.1%}"],
        ],
        numeric_cols=[1, 2],
    )
    rep.paragraph(
        f"受診回数の中央値は {stats['median_visits']:.0f} 回。"
        f"診療科を特定できなかった受診は {stats['unknown_specialty_visits']:,} 件"
        f"（{stats['unknown_specialty_visits'] / stats['n_visits']:.2%}）で、遷移集計では「不明」として残している。"
    )

    rep.section("sankey", "2. 診療科遷移サンキー（1回目→2回目→3回目）")
    rep.add_html(
        '<div class="card span-12"><p>'
        '<a href="figures/pathways_sankey.html" target="_blank">サンキー図を開く</a>'
        "</p>"
        '<div class="fig-explain"><strong>この図の読み方</strong>'
        "左から1回目・2回目・3回目の診療科。帯の太さが人数。"
        "同じ色の帯がまっすぐ右へ伸びていれば同一科のリピート、"
        "他の色へ流れ込んでいれば診療科をまたいだ利用。"
        "耳鼻咽喉科・皮膚科の帯が内科へ向かっているかを見る。"
        "</div></div>"
    )

    rep.section("matrix", "3. 遷移行列（n回目 → n+1回目）")
    rep.figure(FIGURES / "pathways_transition_heatmap.png", "行内構成比。n=1〜3をプール",
               explain="行がn回目、列がn+1回目の診療科。行方向に足すと100%。"
                       "対角線が濃いほど同じ科に留まっている。対角線から右下・左上に外れたセルが"
                       "診療科をまたいだ移動で、ここが面展開の接点にあたる。")

    rep.section("repeat", "4. 同一診療科リピート率 vs 診療科変更率")
    rep.figure(FIGURES / "pathways_repeat_rate.png", "初回科別の内訳",
               explain="緑が「次も同じ科」、橙が「次は別の科」。"
                       "緑が長い科は単科で完結しており面展開の余地が小さい。"
                       "橙が長い科は他科への入口になっている。")
    rep.table(
        ["診療科", "同一科リピート率", "診療科変更率", "N（遷移数）"],
        [[r["診療科"], f"{r['同一科リピート率']:.1%}", f"{r['診療科変更率']:.1%}", f"{r['N']:,}"]
         for r in repeat.to_dict("records")],
        numeric_cols=[1, 2, 3],
    )

    rep.section("spread", "5. 急性期は内科系へ広がっているか")
    rep.figure(FIGURES / "pathways_acute_to_chronic.png", "初回診療科別・内科系への到達率",
               explain="初回に各科を受診し、かつ2回目以降が存在する患者のうち、"
                       "2〜4回目のどこかで内科系に到達した割合。破線は全体平均。"
                       "橙（耳鼻咽喉科・皮膚科）が破線より左にあるほど、"
                       "急性期患者が慢性疾患側へ広がっていないことを意味する。")
    rep.table(
        ["初回診療科", "N", "内科系到達率", "区分"],
        [[r["初回診療科"], f"{r['N']:,}", f"{r['内科到達率']:.1%}", r["区分"]]
         for r in spread["by_first"]],
        numeric_cols=[1, 2],
    )
    rep.callout(
        "読み筋",
        [
            ctx["headline"],
            f"比較群「非急性期かつ初回が内科系でない患者」は N={spread['n_other']:,} と小さく、"
            f"到達率 {spread['other_rate']:.1%} は参考値。判定は母数の大きい2回目遷移のリフト "
            f"{spread['second_lift']:.2f}倍で行っている。",
            ctx["action"],
        ],
        kind="warn" if ctx["spread_weak"] else "ok",
    )

    rep.section("toppaths", "6. 実際に多い経路 上位20")
    rep.paragraph(f"診療科ベース（3回目まで到達した {paths_sp.attrs.get('total', 0):,}人が母数）")
    rep.table(
        ["経路（1回目 → 2回目 → 3回目）", "人数", "構成比"],
        [[r["経路"], f"{r['件数']:,}", f"{r['構成比']:.1%}"] for r in paths_sp.to_dict("records")],
        numeric_cols=[1, 2],
    )
    rep.paragraph(f"クリニックベース（同 {paths_cl.attrs.get('total', 0):,}人が母数）")
    rep.table(
        ["経路（1回目 → 2回目 → 3回目）", "人数", "構成比"],
        [[r["経路"], f"{r['件数']:,}", f"{r['構成比']:.1%}"] for r in paths_cl.to_dict("records")],
        numeric_cols=[1, 2],
    )

    rep.section("limits", "7. 限界")
    rep.callout(
        "限界",
        [
            "自店を経由した受診のみ。他薬局で調剤された受診は観測できないため、"
            "「診療科を変えた」ように見えて実は自店を使わなかっただけ、という取りこぼしが含まれる。",
            "診療科は施設の標榜科から推定した主科であり、実際の受診科ではない。"
            "複数科標榜の施設では先頭の標榜科を主科としている。",
            f"診療科を特定できない受診が {stats['unknown_specialty_visits']:,} 件ある"
            "（clinic_master の診療科欄が空欄の施設）。",
            "遷移は回数ベースで、受診間隔を考慮していない。2回目が翌日か1年後かを区別しない。",
        ],
        kind="warn",
    )

    out = REPORTS / "pathways.html"
    rep.save(out)
    return out


def publish_docs(html_path: Path) -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, DOCS / "pathways.html")
    for p in FIGURES.glob("pathways_*"):
        shutil.copy2(p, DOCS / "figures" / p.name)


# --------------------------------------------------------------------------


def run() -> Dict[str, object]:
    ensure_dirs()
    data = load_sequences()
    visits, smap = data["visits"], data["specialty_map"]

    smap_path = PROCESSED_DIR / "specialty_map.csv"
    smap.to_csv(smap_path, index=False, encoding="utf-8-sig")

    stats = base_stats(visits)
    wide_sp = step_table(visits, "主科")
    wide_cl = step_table(visits, "クリニック名")
    wide_sp.to_csv(PROCESSED_DIR / "pathways_specialty_steps.csv", encoding="utf-8-sig")
    wide_cl.to_csv(PROCESSED_DIR / "pathways_clinic_steps.csv", encoding="utf-8-sig")

    labels = present_labels(wide_sp)
    pairs = pooled_transitions(wide_sp)
    n_transitions = int(len(pairs))
    overall_same = float((pairs["from"] == pairs["to"]).mean()) if n_transitions else float("nan")

    transition_matrix(pairs, labels).to_csv(
        PROCESSED_DIR / "pathways_transition_matrix.csv", encoding="utf-8-sig"
    )

    fig_transition_heatmap(pairs, labels)
    _, repeat_tbl = fig_repeat_rate(pairs, labels)
    repeat_tbl.to_csv(PROCESSED_DIR / "pathways_repeat_rate.csv", index=False, encoding="utf-8-sig")
    spread = acute_to_chronic(wide_sp)
    fig_acute_to_chronic(wide_sp, spread)
    fig_sankey(wide_sp, labels)

    paths_sp = top_paths(wide_sp)
    paths_cl = top_paths(wide_cl)
    paths_sp.to_csv(PROCESSED_DIR / "pathways_top_specialty.csv", index=False, encoding="utf-8-sig")
    paths_cl.to_csv(PROCESSED_DIR / "pathways_top_clinic.csv", index=False, encoding="utf-8-sig")

    # 判定は 2回目遷移のリフト（母数が大きく安定）で行う。
    # other_rate は「非急性期かつ非内科の初回」で母数が小さいため補助的にしか使わない。
    weak = not (spread["second_lift"] > 1.1)
    if weak:
        headline = (
            f"急性期（耳鼻咽喉科・皮膚科）を初回に受診した患者 {spread['n_acute']:,}人のうち、"
            f"2〜4回目までに内科系へ到達したのは {spread['acute_rate']:.1%}。"
            f"2回目の遷移で見ると内科系へ移る割合は {spread['acute_second_chronic_rate']:.1%} で、"
            f"初回が内科系でない患者全体の {spread['second_chronic_rate']:.1%} と差がない"
            f"（リフト {spread['second_lift']:.2f}倍）。"
            f"急性期患者が慢性疾患側へ広がっている形跡はない。"
        )
        action = (
            "したがって面展開の焦点は、急性期患者が自然に内科系へ流れるのを待つことではなく、"
            "内科系クリニックとの接点づくり（処方箋の直接獲得）に置くべき。"
        )
    else:
        headline = (
            f"急性期（耳鼻咽喉科・皮膚科）を初回に受診した患者 {spread['n_acute']:,}人のうち、"
            f"2〜4回目までに内科系へ到達したのは {spread['acute_rate']:.1%}。"
            f"2回目の遷移で内科系へ移る割合は {spread['acute_second_chronic_rate']:.1%} で、"
            f"初回が内科系でない患者全体の {spread['second_chronic_rate']:.1%} を上回る"
            f"（リフト {spread['second_lift']:.2f}倍）。"
            f"急性期から慢性疾患側への広がりが確認できる。"
        )
        action = (
            "急性期入口からの内科系への広がりが効いているため、"
            "耳鼻咽喉科・皮膚科の初回接点を維持しつつ、2回目以降の継続導線を強化する価値がある。"
        )

    ctx = {
        "stats": stats,
        "spread": spread,
        "repeat_tbl": repeat_tbl,
        "top_paths_specialty": paths_sp,
        "top_paths_clinic": paths_cl,
        "overall_same_rate": overall_same,
        "n_transitions": n_transitions,
        "headline": headline,
        "action": action,
        "spread_weak": bool(weak),
    }
    html = write_report(ctx)
    publish_docs(html)
    return {"html": html, "stats": stats, "spread": spread, "headline": headline}


if __name__ == "__main__":
    out = run()
    print("wrote", out["html"])
    print(out["headline"])
