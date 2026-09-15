# kutsuki_pharm_csv-analytics

くつき薬局**南茨木店** DataBank による患者獲得モデル分析リポジトリ。

作業指示の正本: [`docs/ANALYSIS_BRIEF.md`](docs/ANALYSIS_BRIEF.md)

## 現状

- Phase 0〜2 完了（整合性テスト OK）
- **門前型 89.3%** / 非門前 9.6% → 5理論は主に非門前軸で検証
- HTMLレポート対応済み

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
PYTHONPATH=. python3 -m pytest
```

## HTMLレポート（ブラウザで閲覧）

```bash
open reports/phase1_flow.html
open reports/phase2_catchment.html
open reports/figures/phase2_map.html
```

## 主要成果物

| パス | 内容 |
|---|---|
| `reports/phase1_flow.html` | Phase1 レポート（図埋め込み） |
| `reports/phase2_catchment.html` | Phase2 レポート（図埋め込み） |
| `reports/figures/phase2_map.html` | folium 地図 |
| `docs/DATA_ISSUES.md` | データ制約 |
| `docs/QUESTIONS_TO_CLIENT.md` | 依頼者確認事項 |

## ルール要約

- `data/raw/` は読み取り専用
- 花粉欠損の 0 埋め禁止、`新患フラグ` 使用禁止
- 徒歩/自転車所要分と道路kmの同時投入禁止
- 因果表現は識別戦略がある場合のみ
