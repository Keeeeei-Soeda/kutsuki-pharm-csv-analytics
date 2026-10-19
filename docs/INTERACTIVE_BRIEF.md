# 指示書：分析レポートに「さわれる」操作を足す

- 対象リポジトリ: `Keeeeei-Soeda/kutsuki-pharm-csv-analytics`（ソース側。`-design-d` は出力プレビューなので触らない）
- この指示書は `docs/INTERACTIVE_BRIEF.md` として保存し、作業の正本にする
- **前提：データは現在の `data/raw/` のまま固定。** CSV の差し替えや画面からの取り込みには対応しない

コード構成の調査は済んでいる（§1）。Cursor は**コード全体を改めて調査しなくてよい**。ただし `data/raw/` の CSV は非公開でリポジトリ外にあるため、§2-0 の「データ確認」だけはローカルで実行して結果を報告してから実装に入ること。

---

## 1. 現状（調査済み）

### パイプライン
- `src/phaseN_*.py` が `src.io.read_csv()` で生CSVを読み、matplotlib で PNG（`reports/figures/`、47枚）を出力
- `src/viz/html_report.py` の `HtmlReport` が HTML を組み立て、`publish_docs()` で `docs/` にコピー
- `src/build_summary.py` がトップの経営サマリーを `data/processed/page_summaries/*.json` から作る
- `src/apply_ui_shell.py` → `src/viz/sidebar.py: apply_shell()` が全ページにサイドバーを差し込む
- テンプレートは `templates/_sidebar.html / .css / .js / _theme.css`

### 「見るだけ」になっている原因
1. 図はすべて PNG。ブラウザにデータが渡っていないので、絞り込みや期間変更ができない
2. `templates/_sidebar.html` の `.sb-filters` は枠だけ（「期間フィルタ／区分フィルタ 準備中」）
3. 前提値が固定値：`src/kpi.py` の `TARGET_MONTHLY=3000`・`RECENT_MONTHS=3`、`config/economics.yaml` の粗利 2,000円、`sidebar.py` の `PERIOD_LABEL`
4. Phase 3 のシナリオ（`src/models/simulator.py: simulate_scenarios`）は決め打ちの数パターンだけ

### 使う既存ロジック（定義を二重に書かないこと）
| 用途 | 既存の場所 |
|---|---|
| 区分（門前型／非門前型／不明） | `src/phase1_flow.py: _axis_label()`（40m基準は `src.corrections.gate_distance_km()`） |
| 主科 | `src/specialty_taxonomy.py: build_specialty_map(clinic_master)` を `クリニックID` で結合（`src/pathways.py: load_sequences()` と同じやり方） |
| 受診順・初回 | `pathways.load_sequences()` の `受診順`（患者ID・受診日・受診ID順の連番）。**`新患フラグ` は使用禁止** |
| 患者→薬局距離 | `patient_master["患者→薬局_道路km"]` |
| 初回患者の属性 | `src/phase4_retention.py: attach_first_attrs()` |
| 現状の枚数 | `src/kpi.py: current_level()`（直近3か月平均、1受診＝1枚） |
| 成長シナリオ | `src/models/simulator.py: GrowthInputs / simulate_scenarios` |

### 見つかった不整合（先に直す）
`GrowthInputs` の既定値 `gate_share=0.893 / nongate_share=0.096` は**門前判定を40mに変える前の値**。現在の Phase 1 では門前1%・非門前98%（`page_summaries/p1.json`）。Phase 3 の「最大でも約2,312枚」はこの古い比率で計算されている。
→ ステップ1で `run_growth_sim()` が `p1.json` 相当の現行比率を渡すよう修正し、結論文がどう変わるかを報告すること（勝手に結論文を書き換えず、数値の差分を報告する）。

---

## 2. 方針

### 2-0. 実装前のデータ確認（ローカルで実行して報告）
以下を出力するスクリプト `scripts/inspect_for_explore.py` を作って実行し、結果を報告する（コミット不要）。
- `visit_triangle` の行数、受診日の最小・最大、`立地パターン` の値と件数
- `主科` 結合後の値と件数、結合できなかった件数
- `患者→薬局_道路km` の分布（欠損数、0-0.5 / 0.5-1 / 1-2 / 2+ の件数）
- 月 × 区分 × 主科 × 距離帯 × 初回/再来 でセルを作ったときの、5件未満セルの割合

### 2-1. 2層構成
| 層 | 中身 | フィルタ |
|---|---|---|
| **探索層**（新規） | 枚数・割合・推移・ランキング・距離帯・90日再来率 | 効く。ブラウザ（JS）で再集計 |
| **モデル層**（既存） | GLM・Huff・条件付きロジット・ITS/DiD・生存分析・予測 | 効かない。図に「全期間・全患者で推定」バッジを付ける |

モデルをブラウザへ移植しない。

### 2-2. データの渡し方
新規 `src/export_explore_data.py` が**集計済み JSON** を `docs/data/` に出力し、ブラウザはそれだけを読む。患者単位の行は出さない（GitHub Pages は公開）。

### 2-3. 技術
- ビルドなし・ES Modules。GitHub Pages に置くだけで動く
- チャート: Apache ECharts 5（`docs/vendor/echarts.min.js` にバージョン固定で同梱）
- 集計: 素の JS（データは数千セル程度）
- フィルタ状態: URL クエリ＋`localStorage`。全ページで共有
- 色は `templates/_theme.css` と `html_report.py` の CSS 変数（`--gate` `--nongate` `--accent` など）を ECharts テーマに流用

---

## 3. 出力データ（`docs/data/`）

### `facts_monthly.json`
受診（＝処方箋1枚）の件数キューブ。
```json
{ "dims": ["ym","axis","clinic","dept","dist","visit_type"],
  "rows": [["2025-04","非門前型","C001","耳鼻咽喉科","0-0.5","再来", 123], ...] }
```
| 次元 | 値 |
|---|---|
| `ym` | `YYYY-MM` |
| `axis` | 門前型 / 非門前型 / 不明（`_axis_label`） |
| `clinic` | 全期間枚数の上位20院のクリニックID、残りは `OTHER` |
| `dept` | 主科（未結合は `不明`） |
| `dist` | `0-0.5` / `0.5-1` / `1-2` / `2+` / `unknown` |
| `visit_type` | 初回（受診順=1）/ 再来 |

**小セル秘匿:** 件数が1〜4のセルは `null` にして出力（0 にしない）。合計値は別ファイルで正確な値を持つ（下記）。

### `totals_monthly.json`
月 × 区分、月 × 主科、月 × クリニック（上位20＋OTHER）の**1次元ずつの正確な合計**。KPI と推移グラフはこちらを優先して使い、複数条件で絞ったときだけキューブを使う。秘匿セルを含む集計結果には「一部5件未満を除く」と注記を出す。

### `retention.json`
初回月 × 区分 × 主科 × 距離帯 ごとの `{first: 初回患者数, ret90: 90日以内に再来した患者数}`。定義は `phase4_retention` と同じにする。同じく1〜4は秘匿。

### `dims.json`
クリニックID → 名称・主科・門前判定、主科の表示順、距離帯ラベル、データ期間（最初と最後の受診日）、生成日時。

### `params.json`
既定の前提値（目標3,000、直近月数3、粗利2,000円）と、シミュレーター用の現行比率（門前・非門前・不明のシェア、患者数、1人あたり来局回数）。

### `events.json`
`config/events.yaml` を JSON 化したもの。

### テスト `tests/test_export_explore.py`
- `totals_monthly` の月合計 == `kpi.monthly_prescriptions()`
- 直近3か月平均 == `kpi.current_level().recent_mean`（= 1,768）
- `retention.json` 全体の再来率 == `p4.json` の `retention90`（= 0.4067）
- どの JSON にも `患者ID`・住所・緯度経度・生年月日の値やキーが含まれない

---

## 4. 画面の機能

### 4-1. グローバルフィルタ（サイドバーの「準備中」を置き換え）
`templates/_sidebar.html` の `.sb-filters` を実装する。

| フィルタ | UI |
|---|---|
| 期間 | 開始月・終了月のセレクト＋プリセット（直近3か月／直近6か月／直近12か月／全期間） |
| 区分 | 門前型・非門前型・不明（複数選択チップ） |
| 診療科 | 主科の複数選択 |
| クリニック | 検索付き複数選択（上位20＋その他） |
| 距離帯 | 複数選択チップ |
| 初回/再来 | 全て／初回のみ／再来のみ |

- 「リセット」ボタン。適用中の条件はページ上部にチップで表示し、×で個別に外せる
- URL 例: `explore.html?from=2025-04&to=2026-07&axis=非門前型&dept=内科`。URL を開くと同じ状態になる
- ページ移動しても条件を保持（`localStorage`）
- 900px 未満はドロワー内で操作できること
- フィルタはどのページでも表示するが、探索層の図がないページでは「このページの図は全期間の分析です」と表示する

### 4-2. 新ページ「データ探索」`explore.html`
`src/viz/sidebar.py` の `NAV_PAGES` 先頭に追加（key: `explore`）。生成は新規 `src/build_explore.py`。

1. **KPI カード**: 期間内の処方箋枚数（合計・月平均）、比較期間との差、目標までの差、初回比率、90日再来率
2. **月次推移**: 積み上げ棒（区分別／診療科別を切替）＋目標ライン＋施策の縦線（`events.json`）
3. **クリニック別ランキング**: 横棒。表示件数をスライダーで変更。棒クリックでそのクリニックに絞り込み
4. **診療科構成**: 横棒。クリックで絞り込み
5. **距離帯別**: 枚数と90日再来率
6. **明細テーブル**: 並べ替え可。表示中の集計を CSV でダウンロード

各グラフに「画像として保存」を付ける。

### 4-3. 期間比較
「比較する」トグルで期間Bを指定。KPI に A/B と差、月次推移に B を重ねて表示。
文言は「増えた／減った」の記述まで。「効果」「〜によって」などの因果表現は使わない。

### 4-4. 前提値パネル
全ページ共通（サイドバー下部 or ヘッダー右）。`localStorage` に保存、「既定に戻す」あり。
- 目標枚数/月（既定 3,000）
- 「現状」の算出に使う直近月数（1〜6、既定 3）
- 1受診あたり粗利（既定 2,000円）

変更すると KPI・目標ライン・目標までの差が即時に変わる。トップの経営サマリーは静的のまま（「既定値での計算」と注記）。

### 4-5. シミュレーター（Phase 3 ページ内に追加）
`simulate_scenarios` の計算式を JS に移植し、決め打ちのシナリオ表の上にスライダー版を置く。
- スライダー: 門前の増加率、非門前の倍率、来局頻度の増加率、活動患者の増加率
- 比率は `params.json` の**現行値**を使う（§1 の不整合を直した後の値）
- 出力: 到達枚数、目標に対する達成率のゲージ、「非門前だけで目標に届くには×何倍が必要か」
- `tests/js/simulator.test.mjs` で、既定シナリオの値が Python の `simulate_scenarios` と一致することを確認（Python 側で期待値を JSON に書き出して比較）

### 4-6. 既存ページの図を置き換え（記述系のみ）
以下は探索層のチャートに置き換えてフィルタ連動させる。モデル系 PNG は残してバッジを付ける。

| ページ | 置き換える PNG |
|---|---|
| Phase 1 | `phase1_monthly_plain` `phase1_monthly_gate` `phase1_top_clinics` `phase1_timeseries` |
| Phase 2 | `phase2_distance_plain` |
| Phase 4 | `phase4_retention90` |

置き換え方：`HtmlReport` に `chart(id, kind, options)` のようなメソッドを足し、`<div data-chart="...">` を出力。JS 側が `data-chart` を見つけて描画する。JS が読めない場合（印刷時など）に備え、元の PNG を `<noscript>` と印刷用に残す。

### 4-7. 施策の表示と前後比較
- 月次推移に `events.json` の施策を縦線／帯で表示。凡例クリックで表示切替
- 施策を選ぶと、開始前N週と開始後N週の枚数を並べて表示（N は 4/8/12 から選択）。記述のみ。Phase 5 の推定結果がある施策はそのページへのリンクを出す
- 施策の追加・編集は今回やらない

---

## 5. ファイル構成

```
src/
  export_explore_data.py     # 新規: docs/data/*.json を出力
  build_explore.py           # 新規: explore.html を生成
  models/simulator.py        # 修正: 現行比率を受け取る
  phase3_model.py            # 修正: run_growth_sim に現行比率を渡す、シミュレーター枠を追加
  viz/html_report.py         # 修正: chart() メソッド、モデル図バッジ
  viz/sidebar.py             # 修正: NAV_PAGES に explore 追加
templates/
  _sidebar.html/.css/.js     # 修正: フィルタUI・前提値パネル
docs/
  explore.html               # 生成物
  data/*.json                # 生成物（集計のみ）
  vendor/echarts.min.js
  js/
    store.js                 # フィルタ・前提値の状態、URL/localStorage同期
    data.js                  # docs/data/*.json の読み込み（キャッシュ）
    aggregate.js             # 絞り込み・集計・KPI（DOMに触らない純関数）
    simulator.js             # simulate_scenarios の移植（純関数）
    charts.js                # ECharts テーマと共通ラッパ
    filters-ui.js
    pages/explore.js
    pages/inline-charts.js   # 既存ページの data-chart を描画
tests/
  test_export_explore.py
  js/aggregate.test.mjs
  js/simulator.test.mjs      # node --test で実行
```

README の「実行」に `python3 -m src.export_explore_data` と `python3 -m src.build_explore` を追加（`apply_ui_shell` の前）。

---

## 6. 実装ステップ（1ステップずつ。各ステップでコミットし、完了報告に変更点とスクリーンショットを付ける）

1. **データ確認と不整合の修正**: §2-0 の報告、`GrowthInputs` の比率修正と Phase 3 の数値差分の報告
2. **データ出力**: `export_explore_data.py` とテスト。テストが通る
3. **状態管理とフィルタUI**: `store.js` `filters-ui.js`。選んだ条件が URL に反映され、ページ移動後も保持
4. **データ探索ページ**: §4-2 の6ブロック。フィルタ変更で全ブロックが更新
5. **期間比較・前提値パネル**: §4-3、§4-4
6. **シミュレーター**: §4-5 と JS テスト
7. **既存ページの置き換え**: §4-6
8. **施策の表示**: §4-7
9. **README 更新**

---

## 7. ルール

- `data/raw/` は読み取り専用。`docs/` に患者単位データ・住所・緯度経度・生年月日を出さない
- 1受診＝処方箋1枚。「現状」の定義は `src/kpi.py` に合わせる
- 欠損や秘匿セルを 0 で埋めない
- `新患フラグ` は使用禁止
- 因果表現は Phase 5 の推定結果に限る
- `docs/academic/` は凍結版。再生成しない
- 既存の Python 分析の結果（モデル系の数値）は変えない（§1 の不整合修正を除く）

---

## 8. 受け入れ基準

- [ ] 全期間・絞り込みなしで、探索ページの数字が経営サマリーと一致（月平均1,768枚、上位2院73%、90日再来41%）
- [ ] 期間を 2025-04〜2025-09、区分を非門前型にすると全ブロックが連動し、URL を別タブで開くと同じ状態になる
- [ ] ランキングの棒をクリックするとそのクリニックで全体が絞り込まれる
- [ ] 目標を 2,500 にすると KPI の差と目標ラインが即時に変わる
- [ ] シミュレーターの既定値が Python の結果と一致する
- [ ] モデル系の図に「全期間・全患者で推定」バッジがある
- [ ] スマホ幅（375px）でフィルタが操作でき、横スクロールが出ない
- [ ] `pytest` と `node --test tests/js` が通る
- [ ] `docs/data/` に個人情報の列・値が含まれない（テストで確認）
