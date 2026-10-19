"""図（matplotlib）の配色と書体。テーマ（a / d）に合わせて切り替える。

テーマは :data:`src.viz.sidebar.THEME`（環境変数 REPORT_THEME）に従う。
A案の値は従来の図の色そのまま。D案は生成りの画面になじむよう彩度を落とす。
門前 :data:`GATE` / 門前以外 :data:`NONGATE` は全ページで意味が同じなので、テーマで変えない。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import matplotlib.pyplot as plt
from cycler import cycler

from src.viz.sidebar import THEME

GATE = "#c45c26"
NONGATE = "#2f6f9f"


@dataclass(frozen=True)
class FigurePalette:
    ink: str          # 実績の線・0や1の基準線・図中の文字
    note: str         # 図の下の注記
    grey: str         # 強調しない棒・点
    grey_line: str    # 境界線・現状値の線・「不明」
    accent: str       # 強調する系列（傾向線・累積構成比など）
    target: str       # 目標線・施策の期間
    primary: str      # 主系列（門前の意味は持たない）
    secondary: str    # 主系列と対比する系列（門前の意味は持たない）
    teal: str         # 自店の目印・良い側
    near: str         # 近距離（薬局から近い側）
    far: str          # 遠距離
    faint: str        # 背景に敷く散布点
    gate_bar: str     # 門前（月別の積み上げ棒など、古い集計図）
    nongate_bar: str  # 門前以外（同上）
    series: Tuple[str, ...]       # 色の指定がない系列の既定の順番
    categorical: Tuple[str, ...]  # 順序のない区分（患者タイプなど）を塗り分ける色
    fonts: Tuple[str, ...]


_FALLBACK_FONTS = ("Hiragino Sans", "AppleGothic", "DejaVu Sans")

_PALETTES = {
    "a": FigurePalette(
        ink="#1b2430",
        note="#5b6776",
        grey="#9aa4b1",
        grey_line="#888888",
        accent="#E45756",
        target="#b4540a",
        primary=NONGATE,
        secondary=GATE,
        teal="#0f6a6a",
        near="#0f7c74",
        far="#8a94a3",
        faint="#9ecae1",
        gate_bar="#F58518",
        nongate_bar="#4C78A8",
        series=("#4C78A8", "#F58518", "#54A24B", "#B279A2"),
        categorical=("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                     "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"),  # matplotlib の tab10
        fonts=_FALLBACK_FONTS,
    ),
    "d": FigurePalette(
        ink="#3a2e28",
        note="#6b5a52",
        grey="#cbbdb3",
        grey_line="#a8978c",
        accent="#c4472b",
        target="#c4472b",
        primary="#7d8fa8",
        secondary="#d9a066",
        teal="#4f8a7c",
        near="#4f8a7c",
        far="#b5a69c",
        faint="#d9cfe6",
        gate_bar=GATE,
        nongate_bar=NONGATE,
        series=("#7d8fa8", "#d9a066", "#8fb39a", "#a993b8"),
        categorical=("#6f86a6", "#d99a5b", "#6fa58a", "#b07fa8", "#c9a24a",
                     "#8a7166", "#5f9fb0", "#a8978c"),
        fonts=("Zen Maru Gothic", "Hiragino Maru Gothic ProN", "Hiragino Maru Gothic Pro") + _FALLBACK_FONTS,
    ),
}

PAL = _PALETTES[THEME]

# D案の軸まわり。A案は matplotlib の既定のまま。
_D_AXES_STYLE = {
    "figure.facecolor": "#ffffff",
    "axes.facecolor": "#ffffff",
    "savefig.facecolor": "#ffffff",
    "axes.edgecolor": "#6b5a52",
    "axes.labelcolor": "#6b5a52",
    "xtick.color": "#6b5a52",
    "ytick.color": "#6b5a52",
    "grid.color": "#f3ebe4",
    "text.color": PAL.ink,
    "axes.titlecolor": PAL.ink,
    "legend.edgecolor": "#eadfd6",
}


def apply_figure_style() -> None:
    """図を描く前に呼ぶ。書体・軸の色・既定の系列色をテーマに合わせる。"""
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = list(PAL.fonts)
    plt.rcParams["axes.unicode_minus"] = False
    if THEME == "d":
        plt.rcParams.update(_D_AXES_STYLE)
        plt.rcParams["axes.prop_cycle"] = cycler(color=list(PAL.series))
