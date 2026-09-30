"""Phase 5: 施策イベントの効果推定（差の差・比較 ITS・プラセボ検定）。

識別の考え方
  - 週固定効果で「その週に全体へ一律にかかった変化」（季節・開局後の伸び・祝日）を相殺する。
  - チラシ: 商圏内ポスティングは近距離の住民にだけ届く、という前提で
    近距離 vs 遠距離の新患を比べる（差の差）。
  - 継続施策: オンライン系の施策は薬局を自分で選ぶ非門前の処方箋に効き、
    門前2院の処方箋には効きにくい、という前提で非門前 vs 門前を比べる（比較 ITS）。
  - 偶然の変動と区別するため、施策のない週にニセのイベントを置いて同じ推定を繰り返す（プラセボ）。
"""

from __future__ import annotations

import shutil
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yaml

from src.io import PHARMACY_NAME, PROCESSED_DIR, RAW_DIR, ROOT, SEED, ensure_dirs, read_csv
from src.kpi import save_page_summary
from src.viz.html_report import HtmlReport

FIGURES = ROOT / "reports" / "figures"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"
EVENTS_YAML = ROOT / "config" / "events.yaml"
NON_GATE = ["患者近接型", "経由型", "遠隔型"]

DATA_END = pd.Timestamp("2026-07-31")
POST_WEEKS = 4  # チラシ配布終了後、効果窓に含める週数
# (近距離の上限km, 遠距離の下限km)。先頭が主分析。
DISTANCE_SPECS: List[Tuple[float, float]] = [(1.0, 1.5), (0.75, 1.5), (1.0, 2.0)]
# 花粉期（門前の耳鼻科だけが伸びる時期）。花粉の実測は欠損を0埋めできないため暦で近似する。
POLLEN_SEASON = ("02-15", "04-30")
# 開局直後は非門前比率が急伸しており、直線トレンドを当てると以後の施策効果が歪むため比較 ITS から除く。
ITS_START = pd.Timestamp("2024-12-01")
ITS_START_ALT = pd.Timestamp("2025-01-01")
EXCEL_MONTHS = pd.period_range("2024-09", periods=24, freq="M")

COLOR_NEAR = "#0f7c74"
COLOR_FAR = "#8a94a3"
COLOR_GATE = "#c45c26"
COLOR_NONGATE = "#2f6f9f"
COLOR_EVENT = "#b4540a"


def _setup_font() -> None:
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Hiragino Sans", "AppleGothic", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


# --------------------------------------------------------------------------
# 入力
# --------------------------------------------------------------------------

def load_events() -> pd.DataFrame:
    raw = yaml.safe_load(EVENTS_YAML.read_text(encoding="utf-8"))["events"]
    ev = pd.DataFrame(raw)
    ev["start"] = pd.to_datetime(ev["start"])
    ev["end"] = pd.to_datetime(ev.get("end")).fillna(ev["start"])
    return ev


def read_excel_monthly(filename: str) -> pd.DataFrame:
    """先方Excel（B列=指標名、C〜Z列=2024-09〜2026-08）を 月×指標 の表にする。"""
    df = pd.read_excel(RAW_DIR / filename, header=None)
    labels = df.iloc[:, 1].astype(str).str.replace("\u3000", " ").str.strip()
    body = df.iloc[:, 2:2 + len(EXCEL_MONTHS)]
    body.columns = EXCEL_MONTHS
    body.index = labels
    body = body.loc[(labels.ne("nan") & labels.ne("")).values]
    body = body[~body.index.duplicated(keep="first")]
    return body.apply(pd.to_numeric, errors="coerce").T


def load_visits() -> pd.DataFrame:
    vt = read_csv("visit_triangle")
    vt["受診日"] = pd.to_datetime(vt["受診日"])
    vt["軸"] = np.select(
        [vt["立地パターン"].astype(str).eq("門前型"), vt["立地パターン"].astype(str).isin(NON_GATE)],
        ["門前型", "非門前型"],
        default="不明",
    )
    vt["週"] = vt["受診日"].dt.to_period("W-SUN")
    return vt


def first_visits(vt: pd.DataFrame) -> pd.DataFrame:
    """初回受診＝新患（新患フラグは使わない）。"""
    return vt.sort_values(["受診日", "受診ID"]).groupby("患者ID", as_index=False).first()


# --------------------------------------------------------------------------
# 週次パネルとモデル
# --------------------------------------------------------------------------

def week_index(vt: pd.DataFrame) -> pd.PeriodIndex:
    return pd.period_range(vt["週"].min(), vt["週"].max(), freq="W-SUN")


def window_mask(weeks: pd.PeriodIndex, start: pd.Timestamp, end: pd.Timestamp) -> np.ndarray:
    """[start, end] と1日でも重なる週を True にする。"""
    return np.asarray((weeks.end_time >= start) & (weeks.start_time <= end))


def pollen_season(weeks: pd.PeriodIndex) -> np.ndarray:
    mask = np.zeros(len(weeks), bool)
    for year in sorted(set(weeks.start_time.year) | set(weeks.end_time.year)):
        start = pd.Timestamp(f"{year}-{POLLEN_SEASON[0]}")
        end = pd.Timestamp(f"{year}-{POLLEN_SEASON[1]}")
        mask |= window_mask(weeks, start, end)
    return mask


def flyer_windows(ev: pd.DataFrame, weeks: pd.PeriodIndex) -> Dict[str, np.ndarray]:
    out = {}
    for _, e in ev.loc[ev["design"] == "flyer_did"].iterrows():
        out[e["id"]] = window_mask(weeks, e["start"], e["end"] + pd.Timedelta(weeks=POST_WEEKS))
    return out


def stacked_panel(
    counts: Dict[str, pd.Series], weeks: pd.PeriodIndex, treated: str
) -> pd.DataFrame:
    """{群名: 週次件数} を縦に積み、週番号 t と処置群ダミーを付ける。"""
    rows = []
    for name, s in counts.items():
        s = s.reindex(weeks, fill_value=0)
        rows.append(pd.DataFrame({"週": weeks, "群": name, "y": s.values, "t": np.arange(len(weeks))}))
    panel = pd.concat(rows, ignore_index=True)
    panel["treated"] = (panel["群"] == treated).astype(float)
    return panel


def fit_poisson(panel: pd.DataFrame, extra: Dict[str, np.ndarray], group_trend: bool = True):
    """y ~ 週固定効果 + 処置群 + 処置群×t + Σ 処置群×extra。extra は週単位の配列。"""
    X = pd.get_dummies(panel["週"].astype(str), prefix="w", drop_first=True, dtype=float)
    X.insert(0, "const", 1.0)
    X["treated"] = panel["treated"].values
    if group_trend:
        X["treated_t"] = panel["treated"].values * panel["t"].values
    n_weeks = panel["t"].max() + 1
    for name, arr in extra.items():
        arr = np.asarray(arr, float)
        assert len(arr) == n_weeks, name
        X[name] = panel["treated"].values * arr[panel["t"].values]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = sm.GLM(panel["y"].values, X, family=sm.families.Poisson()).fit(cov_type="HC1")
    return res, X


def effect_row(res, name: str) -> Dict[str, float]:
    b = float(res.params[name])
    lo, hi = (float(v) for v in res.conf_int().loc[name])
    return {"beta": b, "効果%": np.expm1(b) * 100, "下限%": np.expm1(lo) * 100,
            "上限%": np.expm1(hi) * 100, "p値": float(res.pvalues[name])}


def extra_patients(res, X: pd.DataFrame, name: str) -> float:
    """処置群の効果窓で、効果項を0にした反実仮想との差（人数）。"""
    rows = X[name] != 0
    if not rows.any():
        return 0.0
    fitted = res.predict(X.loc[rows])
    cf = res.predict(X.loc[rows].assign(**{name: 0.0}))
    return float((fitted - cf).sum())


def placebo_distribution(
    panel: pd.DataFrame,
    base_extra: Dict[str, np.ndarray],
    length: int,
    forbidden: np.ndarray,
    group_trend: bool = True,
) -> np.ndarray:
    """実イベントと重ならない週に同じ長さのニセ窓を置き、係数の分布を得る。"""
    n = int(panel["t"].max() + 1)
    betas = []
    for s in range(4, n - length - 4):
        win = np.zeros(n, bool)
        win[s:s + length] = True
        if (win & forbidden).any():
            continue
        extra = dict(base_extra, placebo=win.astype(float))
        res, _ = fit_poisson(panel, extra, group_trend)
        betas.append(float(res.params["placebo"]))
    return np.array(betas)


def placebo_p(beta: float, dist: np.ndarray) -> float:
    if len(dist) == 0:
        return float("nan")
    return float((1 + np.sum(np.abs(dist) >= abs(beta))) / (1 + len(dist)))


# --------------------------------------------------------------------------
# 分析1: チラシ（近距離 vs 遠距離の新患）
# --------------------------------------------------------------------------

def distance_counts(fv: pd.DataFrame, near_km: float, far_km: float) -> Dict[str, pd.Series]:
    km = fv["患者→薬局_直線km"]
    near = fv.loc[km <= near_km].groupby("週").size()
    far = fv.loc[km > far_km].groupby("週").size()
    return {"近距離": near, "遠距離": far}


def flyer_did(fv: pd.DataFrame, ev: pd.DataFrame, weeks: pd.PeriodIndex) -> Dict:
    wins = flyer_windows(ev, weeks)
    names = ev.set_index("id")["name"].to_dict()
    forbidden = np.zeros(len(weeks), bool)
    for w in wins.values():
        forbidden |= np.convolve(w.astype(float), np.ones(5), mode="same") > 0  # 前後2週も除外

    pollen = pollen_season(weeks).astype(float)
    # (近距離km, 遠距離km, 群別トレンド, 花粉期統制)。先頭が主分析。
    specs = [(n, f, True, False) for n, f in DISTANCE_SPECS]
    specs += [(*DISTANCE_SPECS[0], False, False), (*DISTANCE_SPECS[0], True, True)]

    rows = []
    placebo = {}
    for i, (near_km, far_km, trend, use_pollen) in enumerate(specs):
        main = i == 0
        panel = stacked_panel(distance_counts(fv, near_km, far_km), weeks, "近距離")
        controls = {"統制_花粉期": pollen} if use_pollen else {}
        res, X = fit_poisson(panel, {**wins, **controls}, trend)
        for eid in wins:
            r = effect_row(res, eid)
            r.update({
                "イベント": names[eid], "id": eid,
                "近距離km": near_km, "遠距離km": far_km, "群別トレンド": trend,
                "花粉期統制": use_pollen,
                "主分析": main, "追加新患(人)": extra_patients(res, X, eid),
                "窓の週数": int(wins[eid].sum()),
            })
            if main:
                others = {k: v for k, v in wins.items() if k != eid}
                dist = placebo_distribution(panel, others, int(wins[eid].sum()), forbidden, trend)
                placebo[eid] = dist
                r["プラセボp"] = placebo_p(r["beta"], dist)
                r["プラセボ数"] = len(dist)
            rows.append(r)
    table = pd.DataFrame(rows)
    table.to_csv(PROCESSED_DIR / "phase5_flyer_did.csv", index=False, encoding="utf-8-sig")

    main_panel = stacked_panel(distance_counts(fv, *DISTANCE_SPECS[0]), weeks, "近距離")
    return {"table": table, "placebo": placebo, "windows": wins, "panel": main_panel}


# --------------------------------------------------------------------------
# 分析2: 継続施策（非門前 vs 門前の処方箋、比較 ITS）
# --------------------------------------------------------------------------

def its_terms(weeks: pd.PeriodIndex, start: pd.Timestamp, prefix: str) -> Dict[str, np.ndarray]:
    post = np.asarray(weeks.end_time >= start, float)
    k0 = int(np.argmax(post)) if post.any() else len(weeks)
    since = np.clip(np.arange(len(weeks)) - k0, 0, None) * post
    return {f"{prefix}_水準": post, f"{prefix}_傾き": since}


def comparative_its(vt: pd.DataFrame, ev: pd.DataFrame, weeks: pd.PeriodIndex,
                    autumn_start: Optional[pd.Timestamp] = None, pollen: bool = True,
                    start: pd.Timestamp = ITS_START) -> Dict:
    weeks = weeks[weeks.start_time >= start]
    vt = vt.loc[vt["受診日"] >= weeks.start_time[0]]
    counts = {
        "非門前": vt.loc[vt["軸"] == "非門前型"].groupby("週").size(),
        "門前": vt.loc[vt["軸"] == "門前型"].groupby("週").size(),
    }
    panel = stacked_panel(counts, weeks, "非門前")
    evi = ev.set_index("id")
    extra: Dict[str, np.ndarray] = {}
    extra.update(its_terms(weeks, evi.loc["meo_consult", "start"], "MEO"))
    extra.update(its_terms(weeks, autumn_start or evi.loc["autumn_bundle", "start"], "秋施策"))
    # 評価対象外だが非門前に影響しうるものは統制項として入れる
    for eid, w in flyer_windows(ev, weeks).items():
        extra[f"統制_{eid}"] = w.astype(float)
    extra["統制_競合"] = np.asarray(weeks.end_time >= evi.loc["competitor_yamato_epark", "start"], float)
    if pollen:
        extra["統制_花粉期"] = pollen_season(weeks).astype(float)
    res, X = fit_poisson(panel, extra, group_trend=True)

    rows = []
    for name in ["MEO_水準", "MEO_傾き", "秋施策_水準", "秋施策_傾き", "統制_競合"]:
        r = effect_row(res, name)
        r["項"] = name
        rows.append(r)
    return {"table": pd.DataFrame(rows), "res": res, "X": X, "panel": panel, "extra": extra,
            "weeks": weeks}


ITS_MAIN = "主分析"
ITS_SENS = {
    "秋施策の切れ目=9/29": {"autumn_start": pd.Timestamp("2025-09-29")},
    "花粉期統制なし": {"pollen": False},
    "開始=2025-01": {"start": ITS_START_ALT},
}


def its_with_placebo(vt: pd.DataFrame, ev: pd.DataFrame, weeks: pd.PeriodIndex) -> Dict:
    main = comparative_its(vt, ev, weeks)
    main["table"]["仕様"] = ITS_MAIN
    sens_tables = []
    for label, kwargs in ITS_SENS.items():
        t = comparative_its(vt, ev, weeks, **kwargs)["table"]
        t["仕様"] = label
        sens_tables.append(t)

    # 水準変化のプラセボ: 実際の切れ目から8週以上離れた週にニセの水準変化を足す
    evi = ev.set_index("id")
    weeks = main["weeks"]
    n = len(weeks)
    real_k = [int(np.argmax(np.asarray(weeks.end_time >= evi.loc[i, "start"]))) for i in
              ("meo_consult", "autumn_bundle", "competitor_yamato_epark")]
    betas = []
    for k in range(12, n - 12):
        if min(abs(k - rk) for rk in real_k) < 8:
            continue
        step = (np.arange(n) >= k).astype(float)
        res, _ = fit_poisson(main["panel"], dict(main["extra"], placebo=step), True)
        betas.append(float(res.params["placebo"]))
    dist = np.array(betas)
    tab = main["table"]
    tab["プラセボp"] = [placebo_p(b, dist) if name.endswith("水準") else np.nan
                     for b, name in zip(tab["beta"], tab["項"])]
    table = pd.concat([tab, *sens_tables], ignore_index=True)
    table.to_csv(PROCESSED_DIR / "phase5_its.csv", index=False, encoding="utf-8-sig")
    return {"table": table, "main": main, "placebo": dist}


# --------------------------------------------------------------------------
# 図
# --------------------------------------------------------------------------

def _event_lines(ax, ev: pd.DataFrame, as_period: bool = False, label: bool = True) -> None:
    for i, (_, e) in enumerate(ev.iterrows()):
        x0 = e["start"].to_period("M").to_timestamp() if as_period else e["start"]
        if e["design"] == "flyer_did":
            x1 = e["end"] if not as_period else e["end"].to_period("M").to_timestamp() + pd.offsets.MonthEnd(0)
            ax.axvspan(x0, x1, color=COLOR_EVENT, alpha=0.14, lw=0)
        else:
            ax.axvline(x0, color=COLOR_EVENT, ls="--", lw=1, alpha=0.7)
        if label:
            ax.annotate(str(i + 1), (x0, 1.0), xycoords=("data", "axes fraction"),
                        xytext=(2, -12), textcoords="offset points", fontsize=8, color=COLOR_EVENT)


def plot_timeline(aux: pd.DataFrame, ev: pd.DataFrame) -> Path:
    _setup_font()
    d = aux.loc[:"2026-07"]
    x = d.index.to_timestamp()
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(x, d["処方箋枚数"], color="#1b2430", lw=2, label="処方箋枚数（全体）")
    ax.plot(x, d["門前(はせ、平山）枚数"], color=COLOR_GATE, lw=1.6, label="門前2院の枚数")
    ax.plot(x, d["広域合計枚数"], color=COLOR_NONGATE, lw=1.6, label="広域（門前以外）の枚数")
    ax.plot(x, d["新患数"], color=COLOR_NEAR, lw=1.6, ls="--", label="新患数")
    _event_lines(ax, ev, as_period=False)
    ax.set_ylabel("件／月")
    ax.set_title(f"{PHARMACY_NAME} 月次推移と施策イベント（2024-09〜2026-07、補助資料）")
    ax.legend(fontsize=8, ncol=4, loc="upper left")
    legend = "  ".join(f"{i + 1}:{n}" for i, n in enumerate(ev["name"]))
    fig.text(0.01, -0.04, legend, fontsize=7.5, color="#5b6776", wrap=True)
    fig.tight_layout()
    out = FIGURES / "phase5_timeline.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_mediators(online: pd.DataFrame, ev: pd.DataFrame) -> Path:
    _setup_font()
    series = {
        "Googleビジネスプロフィール閲覧（ユニーク）": "GBPを閲覧したユニークユーザー数",
        "Googleマップ ルート検索": "MEO ルート検索",
        "EPARK 登録数（累計）": "EPARK登録数(web)",
        "LINE 登録数": "LINE 登録数",
        "オンライン受付 総数": "オンライン総数",
    }
    d = online.loc[:"2026-07"]
    x = d.index.to_timestamp()
    fig, axes = plt.subplots(len(series), 1, figsize=(11, 9), sharex=True)
    for ax, (title, col) in zip(axes, series.items()):
        if col not in d.columns:
            ax.set_visible(False)
            continue
        ax.plot(x, d[col], color=COLOR_NONGATE, lw=1.6, marker="o", ms=3)
        _event_lines(ax, ev, label=ax is axes[0])
        ax.set_title(title, fontsize=10, loc="left")
        ax.grid(axis="y", alpha=0.3)
    axes[-1].tick_params(axis="x", rotation=0)
    fig.suptitle("中間指標（オンライン系データ）: 施策の後にチャネルの数字が動いたか", fontsize=12)
    fig.tight_layout()
    out = FIGURES / "phase5_mediators.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_flyer_weekly(did: Dict, ev: pd.DataFrame, weeks: pd.PeriodIndex) -> Path:
    _setup_font()
    p = did["panel"]
    near = p.loc[p["群"] == "近距離", "y"].values
    far = p.loc[p["群"] == "遠距離", "y"].values
    x = weeks.start_time
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.4), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
    ax = axes[0]
    ax.plot(x, near, color=COLOR_NEAR, lw=1.5, label=f"近距離（薬局から{DISTANCE_SPECS[0][0]:g}km以内）")
    ax.plot(x, far, color=COLOR_FAR, lw=1.5, label=f"遠距離（{DISTANCE_SPECS[0][1]:g}km超）")
    for eid, w in did["windows"].items():
        idx = np.where(w)[0]
        axes[0].axvspan(x[idx[0]], x[idx[-1]] + pd.Timedelta(days=6), color=COLOR_EVENT, alpha=0.14, lw=0)
        axes[1].axvspan(x[idx[0]], x[idx[-1]] + pd.Timedelta(days=6), color=COLOR_EVENT, alpha=0.14, lw=0)
    ax.set_ylabel("新患／週")
    ax.set_title("チラシの効果窓（網掛け＝配布期間＋4週）の新患数: 近距離だけ増えたか")
    ax.legend(fontsize=8)
    ax = axes[1]
    ratio = np.log((near + 0.5) / (far + 0.5))
    ax.plot(x, ratio, color="#1b2430", lw=1)
    ax.plot(x, pd.Series(ratio).rolling(5, center=True).mean(), color=COLOR_NEAR, lw=2, label="5週移動平均")
    ax.set_ylabel("log(近距離/遠距離)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = FIGURES / "phase5_flyer_weekly.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_flyer_effects(did: Dict) -> Path:
    _setup_font()
    t = did["table"]
    events = list(dict.fromkeys(t["イベント"]))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), gridspec_kw={"width_ratios": [3, 2]})
    ax = axes[0]
    y = 0
    ticks, labels = [], []
    for ev_name in events:
        sub = t.loc[t["イベント"] == ev_name]
        for _, r in sub.iterrows():
            color = COLOR_NEAR if r["主分析"] else "#9aa4b1"
            ax.errorbar(r["効果%"], y, xerr=[[r["効果%"] - r["下限%"]], [r["上限%"] - r["効果%"]]],
                        fmt="o", color=color, ms=6 if r["主分析"] else 4, capsize=2)
            spec = (f"{r['近距離km']:g}km以内 vs {r['遠距離km']:g}km超"
                    + ("" if r["群別トレンド"] else "・トレンドなし")
                    + ("・花粉期統制" if r["花粉期統制"] else ""))
            ticks.append(y)
            labels.append(f"{ev_name[:14]}｜{spec}" if r["主分析"] else spec)
            y -= 1
        y -= 0.6
    ax.axvline(0, color="#1b2430", lw=1)
    ax.set_yticks(ticks)
    ax.set_yticklabels(labels, fontsize=7.5)
    ax.set_xlabel("近距離の新患の変化（%、95%信頼区間）")
    ax.set_title("チラシ効果の推定（濃い色＝主分析、灰色＝感度分析）")

    ax = axes[1]
    main = t.loc[t["主分析"]]
    for i, (_, r) in enumerate(main.iterrows()):
        dist = did["placebo"].get(r["id"], np.array([]))
        ax.scatter(np.expm1(dist) * 100, np.full(len(dist), i), s=8, color="#9aa4b1", alpha=0.6)
        ax.scatter(r["効果%"], i, s=60, color=COLOR_NEAR, zorder=3)
    ax.axvline(0, color="#1b2430", lw=1)
    ax.set_yticks(range(len(main)))
    ax.set_yticklabels([f"{n[:12]}（p={p:.2f}）" for n, p in zip(main["イベント"], main["プラセボp"])], fontsize=8)
    ax.set_xlabel("変化（%）")
    ax.set_title("プラセボ比較（灰＝施策のない週、緑＝実施策）")
    fig.tight_layout()
    out = FIGURES / "phase5_flyer_effects.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_its(its: Dict, ev: pd.DataFrame, weeks: pd.PeriodIndex) -> Path:
    _setup_font()
    m = its["main"]
    res, X, panel = m["res"], m["X"], m["panel"]
    ng = (panel["群"] == "非門前").values
    fitted = res.predict(X.loc[ng])
    cf_cols = ["MEO_水準", "MEO_傾き", "秋施策_水準", "秋施策_傾き"]
    cf = res.predict(X.loc[ng].assign(**{c: 0.0 for c in cf_cols}))
    x = weeks.start_time
    gate = panel.loc[~ng, "y"].values
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.6), sharex=True)
    ax = axes[0]
    ax.plot(x, panel.loc[ng, "y"].values, color=COLOR_NONGATE, lw=1, alpha=0.6, label="非門前 実績")
    ax.plot(x, fitted.values, color=COLOR_NONGATE, lw=2, label="非門前 モデル")
    ax.plot(x, cf.values, color="#1b2430", lw=1.5, ls="--", label="非門前 施策がなかった場合（推定）")
    _event_lines(ax, ev)
    ax.set_ylabel("処方箋／週")
    ax.set_title("継続施策の比較ITS: 非門前の処方箋（門前との比で週ごとの共通変動を相殺、2024-12以降）")
    ax.legend(fontsize=8)
    ax = axes[1]
    ax.plot(x, gate, color=COLOR_GATE, lw=1.3, label="門前 実績（比較対照）")
    _event_lines(ax, ev, label=False)
    ax.set_ylabel("処方箋／週")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = FIGURES / "phase5_its.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------
# レポート
# --------------------------------------------------------------------------

def _fmt_pct(v: float) -> str:
    return f"{v:+.0f}%"


def _verdict(r: pd.Series, sensitivity_effects: Sequence[float]) -> str:
    """95%CIが0をまたがない・プラセボp<0.10・感度分析で符号が変わらない、の全部を満たすときだけ効果とみなす。"""
    ci_excludes_zero = r["下限%"] > 0 or r["上限%"] < 0
    pp = r.get("プラセボp", np.nan)
    placebo_ok = np.isnan(pp) or pp < 0.1
    robust = all(np.sign(v) == np.sign(r["効果%"]) for v in sensitivity_effects)
    if ci_excludes_zero and placebo_ok and robust:
        return "効果あり（前提付き）" if r["効果%"] > 0 else "減少（前提付き）"
    return "判定できない"


def write_report(ev: pd.DataFrame, did: Dict, its: Dict, figs: Dict[str, Path],
                 n_new: int, n_visits: int, aux_issue: str) -> Dict[str, Path]:
    dt = did["table"]
    flyer = dt.loc[dt["主分析"]].copy()
    flyer["感度で符号反転"] = [
        int((np.sign(dt.loc[(dt["id"] == r["id"]) & ~dt["主分析"], "効果%"]) != np.sign(r["効果%"])).sum())
        for _, r in flyer.iterrows()
    ]
    flyer["判定"] = [
        _verdict(r, dt.loc[(dt["id"] == r["id"]) & ~dt["主分析"], "効果%"]) for _, r in flyer.iterrows()
    ]
    it = its["table"]
    its_main = it.loc[it["仕様"] == ITS_MAIN].copy()
    its_sens = {label: it.loc[it["仕様"] == label].set_index("項") for label in ITS_SENS}
    its_main["判定"] = [
        _verdict(r, [s.loc[r["項"], "効果%"] for s in its_sens.values()])
        for _, r in its_main.iterrows()
    ]

    def its_row(term: str) -> pd.Series:
        return its_main.set_index("項").loc[term]

    found = []
    for _, r in flyer.iterrows():
        found.append(
            f"{r['イベント']}: 近距離の新患 {_fmt_pct(r['効果%'])}（95%CI {r['下限%']:+.0f}〜{r['上限%']:+.0f}%、"
            f"プラセボp={r['プラセボp']:.2f}、追加 約{r['追加新患(人)']:.0f}人）→ {r['判定']}"
        )
    for term, label in [("MEO_水準", "MEOコンサル開始（水準）"), ("秋施策_水準", "秋の施策群（水準）")]:
        r = its_row(term)
        found.append(
            f"{label}: 非門前の処方箋 {_fmt_pct(r['効果%'])}（95%CI {r['下限%']:+.0f}〜{r['上限%']:+.0f}%、"
            f"プラセボp={r['プラセボp']:.2f}）→ {r['判定']}"
        )

    evi = ev.reset_index(drop=True)
    timeline_rows = [
        [i + 1, e["name"], e["target"], e["start"].strftime("%Y-%m-%d"),
         e["end"].strftime("%Y-%m-%d") if e["end"] != e["start"] else "（継続）",
         {"flyer_did": "差の差", "its": "比較ITS", "descriptive": "記述のみ"}[e["design"]],
         e["source"]]
        for i, e in evi.iterrows()
    ]

    # ---- Markdown
    md_lines = [
        "# Phase 5 施策イベントの効果推定",
        "",
        f"- データ: 受診明細 {n_visits:,}件 / 新患 {n_new:,}人（2024-09-02〜2026-07-31）、先方Excel 2点（2026-09-30受領）",
        "- 新患＝初回受診日（新患フラグは不使用）",
        "- 年表: `config/events.yaml`（Excelの「↑」注記を転記。注記内の日付を優先）",
        "",
        "## 結果",
        "",
        *[f"- {s}" for s in found],
        "",
        "## 手法",
        "",
        "- チラシ: 週次の新患を近距離（≤1.0km）と遠距離（>1.5km）に分け、週固定効果＋群別トレンドのポアソン回帰で差の差。",
        "  感度分析: 近距離0.75km、遠距離2.0km、群別トレンドなし、花粉期統制あり。",
        "- 継続施策: 週次の処方箋を非門前と門前に分け、週固定効果の比較ITS（水準・傾きの変化）。",
        "  チラシ窓・競合イベント・花粉期（2/15〜4/30、門前の耳鼻科だけが伸びる時期）は統制項。",
        "  開局直後（2024-09〜11）は非門前比率が急伸しており直線トレンドでは表せないため、2024-12以降で推定。",
        "  感度分析: 秋施策の切れ目を 9/29 に動かす、花粉期統制を外す、開始を2025-01にする。",
        "- プラセボ: 実イベントと重ならない週にニセの窓・切れ目を置いて同じ推定を繰り返し、実係数の順位でp値を出す。",
        "- 判定: 95%CIが0をまたがない・プラセボp<0.10・感度分析の全仕様で効果の向きが同じ、の3つを満たすときだけ",
        "  「効果あり（前提付き）」。1つでも欠けたら「判定できない」（効果がないという意味ではない）。",
        "",
        "## 前提と限界",
        "",
        "- ポスティングは薬局から半径1km（先方確認済み）。半径内を全戸配布したかは未確認で、配布漏れがあれば効果は薄まって見える。",
        "- 近距離と遠距離は、施策がなければ同じ動き方をする（群別の直線トレンドの差は許容）と仮定。",
        "- 秋の施策群は4施策が6週間に集中しており、個別の効果は分離できない。",
        "- LINEチラシ同封（2026-02-13〜）は春ポスティング2026と重なり分離できない。",
        "- 競合（ヤマト薬局EPARK課金）は事後が約2か月で推定対象外（統制項としてのみ投入）。",
        f"- {aux_issue}",
        "- 1店舗のデータであり、他店舗への一般化はできない。",
    ]
    md_path = REPORTS / "phase5_causal.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    # ---- HTML
    evi_by_id = ev.set_index("id")
    plain_rows = [
        _plain_row(evi_by_id.loc[r["id"]], r["判定"], r["効果%"], "近くの新患")
        for _, r in flyer.iterrows()
    ] + [
        _plain_row(evi_by_id.loc[eid], its_row(term)["判定"], its_row(term)["効果%"], "門前以外の処方箋")
        for eid, term in [("meo_consult", "MEO_水準"), ("autumn_bundle", "秋施策_水準")]
    ]
    n_eval = len(plain_rows)
    n_confirmed = sum(row[2] == "確認できた" for row in plain_rows)
    months = (DATA_END.to_period("M") - pd.Timestamp("2024-09-01").to_period("M")).n + 1

    rep = HtmlReport(
        title="チラシや施策は効いたか",
        subtitle="これまでのチラシ配布や集客施策で、患者が増えたかを確かめます。",
        pharmacy=PHARMACY_NAME,
        period="受診 2024-09-02 〜 2026-07-31",
        eyebrow="Kutsuki DataBank / Phase 5",
        active_phase=5,
    )
    rep.add_kpi("評価した施策", f"{n_eval}件", f"チラシ{len(flyer)}・継続施策{n_eval - len(flyer)}",
                compare=f"年表の{len(ev)}件のうち、効果を測れる時期と期間があったもの", tone="neutral")
    rep.add_kpi("効果を確認できた施策", f"{n_confirmed}件", f"評価{n_eval}件のうち",
                compare=f"残り{n_eval - n_confirmed}件は、増えたとも減ったとも言えなかった",
                tone="good" if n_confirmed else "bad")
    rep.add_kpi("分析した新規患者", f"{n_new:,}人", "初めて来局した日で数えた人数",
                compare=f"1か月あたり平均 約{n_new / months:,.0f}人", tone="neutral")

    if n_confirmed:
        rep.takeaway(
            finding=f"評価した{n_eval}件のうち{n_confirmed}件で、患者数の変化を確認できました。",
            judgment="確認できなかった施策も、効果がなかったという意味ではありません。",
            action=("次の施策では、①配布エリアと配布日を記録する、②同じ時期に別の施策を重ねない、"
                    "③チラシにQRコードなど「チラシを見て来た」ことがわかる仕掛けを入れます。"),
        )
    else:
        rep.takeaway(
            finding="今回のデータでは、どの施策も「患者が増えた」とも「減った」とも言い切れませんでした。",
            judgment=("効果がなかったという意味ではありません。施策の時期が重なっていたり、"
                      "期間が短かったりして、効果を切り分けられませんでした。"),
            action=("次の施策では、①配布エリアと配布日を記録する、②同じ時期に別の施策を重ねない、"
                    "③チラシにQRコードなど「チラシを見て来た」ことがわかる仕掛けを入れます。"
                    "これで効果を測れるようになります。"),
        )

    rep.section("results", "施策ごとの結果")
    rep.table(["施策名", "時期", "結果", "ひとこと"], plain_rows)

    rep.section("timeline", "月別の推移と施策の時期")
    rep.figure(
        figs["timeline"],
        point="施策の前後で、処方箋や新患の数がはっきり変わった時期は見当たりません。",
        explain=(
            "黒が処方箋全体、橙が門前2院、青が門前以外、緑の点線が新患の月別の数です。"
            "縦の点線と網掛けが施策の時期で、番号は下の注記に対応します。"
        ),
    )

    with rep.expert_details("専門家向けの詳細（推定方法・統計量・感度分析・前提）"):
        rep.callout("結果（数値はすべて前提付きの推定）", found, kind="ok")
        rep.callout(
            "限界",
            [
                "ポスティングは半径1km（先方確認済み）。半径内の全戸に配ったかは未確認。",
                "秋の施策群は4施策が6週間に集中し、個別の効果は分けられない。",
                "LINEチラシ同封は春ポスティング2026と重なり分けられない。競合イベントは事後期間が短く推定対象外。",
                aux_issue,
                "新患＝初回受診日（新患フラグは不使用）。",
            ],
            kind="warn",
        )

        rep.section("events", "イベント年表", "Excelの「↑」注記を転記。注記内の日付を優先した。")
        rep.table(["#", "イベント", "対象", "開始", "終了", "推定方法", "出典セル"], timeline_rows)

        rep.section("mediators", "中間指標の動き", "施策がチャネルの数字を動かしたかの確認（効果推定ではない）。")
        rep.figure(figs["mediators"], "オンライン系データの月次推移")

        rep.section("flyer", "チラシの効果（近距離 vs 遠距離の新患）",
                    "週固定効果＋群別トレンドのポアソン回帰。効果窓＝配布期間＋4週。")
        rep.figure(figs["flyer_weekly"], "週次の新患数と効果窓")
        rep.figure(figs["flyer_effects"], "推定効果と感度分析・プラセボ")
        n_sens = int((~dt["主分析"]).sum() / max(len(flyer), 1))
        rep.table(
            ["イベント", "効果", "95%CI", "プラセボp", "追加新患", f"感度{n_sens}仕様中の符号反転", "判定"],
            [[r["イベント"], _fmt_pct(r["効果%"]), f"{r['下限%']:+.0f}〜{r['上限%']:+.0f}%",
              f"{r['プラセボp']:.2f}", f"{r['追加新患(人)']:.0f}人", f"{r['感度で符号反転']}件", r["判定"]]
             for _, r in flyer.iterrows()],
            numeric_cols=[1, 3, 4, 5],
        )

        rep.section("its", "継続施策の効果（非門前 vs 門前の処方箋）",
                    "週固定効果の比較ITS。水準＝切れ目での段差、傾き＝その後の週あたりの伸びの変化。")
        rep.figure(figs["its"], "非門前の実績・モデル・施策がなかった場合")
        label = {"MEO_水準": "MEO 水準", "MEO_傾き": "MEO 傾き（週あたり）", "秋施策_水準": "秋施策 水準",
                 "秋施策_傾き": "秋施策 傾き（週あたり）", "統制_競合": "競合イベント（参考）"}
        rep.table(
            ["項", "効果", "95%CI", "プラセボp", *ITS_SENS, "判定"],
            [[label[r["項"]], _fmt_pct(r["効果%"]) if "傾き" not in r["項"] else f"{r['効果%']:+.1f}%",
              f"{r['下限%']:+.0f}〜{r['上限%']:+.0f}%",
              "-" if np.isnan(r["プラセボp"]) else f"{r['プラセボp']:.2f}",
              *[f"{s.loc[r['項'], '効果%']:+.1f}%" for s in its_sens.values()], r["判定"]]
             for _, r in its_main.iterrows()],
            numeric_cols=[1, 3, 4, 5, 6],
        )

        _write_method_section(rep)

    html_path = REPORTS / "phase5_causal.html"
    rep.save(html_path)

    save_page_summary("p5", {
        "n_eval": n_eval,
        "n_confirmed": n_confirmed,
        "n_new": n_new,
        "conclusion": (
            f"評価した施策{n_eval}件のうち、効果を確認できたのは{n_confirmed}件。"
            "次の施策は効果を測れる形で行う必要があります。"
        ),
    })
    return {"md": md_path, "html": html_path}


# 施策ごとの補足（年表の note を薬局長向けに短くしたもの）
EVENT_NOTES = {
    "autumn_bundle": "4つの施策が6週間に重なり、個別には分けられない",
    "flyer_2026_spring": "LINEチラシ同封と時期が重なっている",
    "meo_consult": "開始月だけが分かり、日付は不明",
}


def _period_label(e: pd.Series) -> str:
    s = e["start"]
    if e["design"] == "its":
        return f"{s.year}年{s.month}月〜（継続）"
    end = e["end"]
    tail = f"{end.month}月{end.day}日" if end.year == s.year else f"{end.year}年{end.month}月{end.day}日"
    return f"{s.year}年{s.month}月{s.day}日〜{tail}"


def _plain_row(e: pd.Series, verdict: str, effect: float, target: str) -> list:
    confirmed = verdict.startswith("効果あり") or verdict.startswith("減少")
    direction = "増えた" if effect > 0 else "減った"
    if confirmed:
        comment = f"{target}が約{abs(effect):.0f}%{direction}"
    else:
        comment = f"{target}はやや{direction}が、偶然の範囲と区別できない"
    note = EVENT_NOTES.get(e.name)
    if note:
        comment += f"。{note}"
    return [e["name"], _period_label(e), "確認できた" if confirmed else "確認できなかった", comment]


def _write_method_section(rep: HtmlReport) -> None:
    rep.section("method", "手法と前提")
    rep.paragraph(
        "週ごとの固定効果で、その週に全体へ一律にかかった変化（3月の花粉ピーク、開局後の伸び、祝日）を相殺する。"
        "チラシは商圏内の住民にだけ届くという前提で、近距離（1.0km以内）と遠距離（1.5km超）の新患を比べる。"
        "継続施策は、薬局を自分で選ぶ非門前の処方箋に効き、門前2院の処方箋には効きにくいという前提で両者を比べる。"
        "ただし花粉期（2/15〜4/30）は門前の耳鼻科だけが伸び、この前提が崩れるため、花粉期の差を統制項として入れた。"
    )
    rep.paragraph(
        "比較ITSは2024年12月以降で推定した。開局直後の3か月は非門前の比率が0.04→0.07と急に伸びており、"
        "ここを含めて直線トレンドを当てると、伸びが落ち着いただけの2025年4月以降を『MEO開始で下がった』と誤読する"
        "（全期間で推定すると MEO −29% という、月次の実数では見えない減少が出た）。"
    )
    rep.paragraph(
        "判定は「95%信頼区間が0をまたがない」「プラセボp＜0.10」「感度分析のすべての仕様で効果の向きが同じ」の"
        "3つを満たすときだけ『効果あり（前提付き）』とした。1つでも欠けた場合は、効果がないと言えるわけではなく、"
        "このデータでは区別できないという意味で『判定できない』とした。"
    )


def publish_docs(html_path: Path) -> None:
    (DOCS / "figures").mkdir(parents=True, exist_ok=True)
    shutil.copy2(html_path, DOCS / "phase5_causal.html")
    for p in FIGURES.glob("phase5_*.png"):
        shutil.copy2(p, DOCS / "figures" / p.name)


def run_phase5() -> Dict:
    np.random.seed(SEED)
    ensure_dirs()
    ev = load_events()
    aux = read_excel_monthly("補助資料.xlsx")
    online = read_excel_monthly("オンライン系データ.xlsx")

    last = aux.loc["2026-08"]
    aux_issue = (
        f"補助資料の2026-08は受付回数{last['受付回数']:.0f}に対し処方箋枚数{last['処方箋枚数']:.0f}と整合せず、"
        "受診データも2026-07-31までのため2026-08は使っていない。"
    )

    vt = load_visits()
    vt = vt.loc[vt["受診日"] <= DATA_END]
    fv = first_visits(vt)
    weeks = week_index(vt)

    did = flyer_did(fv, ev, weeks)
    its = its_with_placebo(vt, ev, weeks)
    figs = {
        "timeline": plot_timeline(aux, ev),
        "mediators": plot_mediators(online, ev),
        "flyer_weekly": plot_flyer_weekly(did, ev, weeks),
        "flyer_effects": plot_flyer_effects(did),
        "its": plot_its(its, ev.loc[ev["start"] >= ITS_START], its["main"]["weeks"]),
    }
    paths = write_report(ev, did, its, figs, len(fv), len(vt), aux_issue)
    publish_docs(paths["html"])
    return {"paths": paths, "flyer": did["table"], "its": its["table"]}


if __name__ == "__main__":
    out = run_phase5()
    print("wrote", out["paths"])
    cols = ["イベント", "近距離km", "遠距離km", "群別トレンド", "効果%", "下限%", "上限%", "プラセボp", "追加新患(人)"]
    print(out["flyer"][cols].round(2).to_string(index=False))
    print(out["its"].round(3).to_string(index=False))
