# kutsuki_pharm-csv-analytics

くつき薬局**南茨木店** DataBank による患者獲得モデル分析リポジトリ。

## GitHub Pages

**2系統を同時に公開している。**

| 版 | URL | 用途 |
|---|---|---|
| 薬局向け（最新） | https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/ | サイドバーUI・来院経路・商圏マップを含む |
| 学術用（旧UI・凍結） | https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/academic/ | サイドバー導入前の状態を `docs/academic/` に凍結 |

薬局向け版のページ:

- [トップ](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/)
- [Phase 1](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase1_flow.html)
- [Phase 2](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase2_catchment.html)
- [Phase 3](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase3_model.html)
- [Phase 4](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase4_retention.html)
- [Phase 5](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase5_causal.html)（データ不足・保留）
- [Phase 6](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase6_integrated.html)
- [来院経路](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/pathways.html)
- [商圏マップ](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/map.html)

学術版は**再生成しない凍結スナップショット**。取り直すときは
`python3 -m src.snapshot_academic <git-ref>`。

> 生の患者CSVはリポジトリに含めていません（`.gitignore` で除外）。

作業指示の正本: [`docs/ANALYSIS_BRIEF.md`](docs/ANALYSIS_BRIEF.md)

## 現状

- Phase 0〜4・6 完了（Phase5はイベント年表待ち）
- **門前型 89.3%** / 非門前 9.6%
- Phase6: 月次予測は移動平均3が最良（MAE≈126, MAPE≈6.8%）
- 来院経路: 単発患者 44.4%。急性期（耳鼻咽喉科・皮膚科）→内科系への広がりは観測されず
- HTMLレポートを `docs/` から GitHub Pages 公開（薬局向け／学術用の2系統）

## セットアップ

```bash
python3 -m pip install -r requirements.txt
```

## 実行

```bash
python3 -m src.validate
python3 -m src.run_early_phases
python3 -m src.phase1_flow && python3 -m src.export_phase1_html
python3 -m src.phase2_catchment
python3 -m src.phase3_model
python3 -m src.phase4_retention
python3 -m src.phase6_integrated
python3 -m src.pathways        # 来院経路（診療科遷移）
python3 -m src.build_map       # 商圏マップ（Leaflet / 地理院タイル）
# Pages用にコピー（phase3/4/6・pathways・map は docs/ へ自動コピー）
cp reports/phase1_flow.html reports/phase2_catchment.html docs/
cp reports/figures/* docs/figures/
# UIシェル（サイドバー）を全ページへ適用 → 学術版へのバナーを入れる
python3 -m src.apply_ui_shell
python3 -m src.snapshot_academic
```

分析を回さず UI だけ直したいときは `python3 -m src.apply_ui_shell` のみでよい。

### 補正の適用

```bash
python3 -m src.corrections --verify   # キーが指すクリニック名を突合（適用しない）
python3 -m src.corrections --force    # enabled:false のまま影響だけ試算
python3 -m src.corrections            # 影響レポートを生成
```

`config/corrections.yaml` の `enabled: true` にすると `src.io.read_csv` 経由で
全分析に自動適用される。`data/raw/` は書き換えない。

## UI（サイドバー）

マークアップ・CSS・JS は `templates/` の3ファイルに集約している。
Phase を増やすときは `src/viz/sidebar.py` の `NAV_PAGES` に1行足す。

| ファイル | 役割 |
|---|---|
| `templates/_sidebar.html` | サイドバーのマークアップ（全ページ共通・実体はここだけ） |
| `templates/_sidebar.css` | レイアウト（240px固定 / 900px未満はドロワー）・印刷時非表示 |
| `templates/_sidebar.js` | ドロワー開閉・ページ内目次のスクロールスパイ |
| `src/viz/sidebar.py` | テンプレの埋め込みと既存HTMLへのレトロフィット |

## ルール要約

- `data/raw/` は読み取り専用・非公開
- 花粉欠損の 0 埋め禁止、`新患フラグ` 使用禁止
- 因果表現は識別戦略がある場合のみ
