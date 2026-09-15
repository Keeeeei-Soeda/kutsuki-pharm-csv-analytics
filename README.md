# kutsuki_pharm-csv-analytics

くつき薬局**南茨木店** DataBank による患者獲得モデル分析リポジトリ。

## GitHub Pages

公開レポート: **https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/**

- [トップ](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/)
- [Phase 1](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase1_flow.html)
- [Phase 2](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase2_catchment.html)
- [Phase 3](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase3_model.html)
- [Phase 4](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase4_retention.html)
- [Phase 6](https://keeeeei-soeda.github.io/kutsuki-pharm-csv-analytics/phase6_integrated.html)

> 生の患者CSVはリポジトリに含めていません（`.gitignore` で除外）。

作業指示の正本: [`docs/ANALYSIS_BRIEF.md`](docs/ANALYSIS_BRIEF.md)

## 現状

- Phase 0〜4・6 完了（Phase5はイベント年表待ち）
- **門前型 89.3%** / 非門前 9.6%
- Phase6: 月次予測は移動平均3が最良（MAE≈126, MAPE≈6.8%）
- HTMLレポートを `docs/` から GitHub Pages 公開

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
# Pages用にコピー（phase3/4/6 は docs/ へ自動コピー）
cp reports/phase1_flow.html reports/phase2_catchment.html docs/
cp reports/figures/* docs/figures/
```

## ルール要約

- `data/raw/` は読み取り専用・非公開
- 花粉欠損の 0 埋め禁止、`新患フラグ` 使用禁止
- 因果表現は識別戦略がある場合のみ
