# Cursor 指示書：面薬局における患者獲得モデルの構築・分析

対象データ：`DataBank`（くつき薬局南茨木店 / 18 CSV・データ辞書付き）  
対象期間：受診 2024-09-02 〜 2026-07-31（患者 8,885人・受診 31,924件・医療機関 434施設・競合薬局 66件）

本ファイルは Cursor（Agent / Composer）に読ませる作業指示書である。各 Phase のタスクを順に実行すること。

---

## 0. 目的と前提（重大ギャップ）

依頼者は「面薬局における患者獲得モデル」を5理論（Prescription Flow / Clinic Catchment Area / Pharmacy Choice Rate / Patient Growth Engine / Patient Experience Engine）として構築し、処方箋枚数を数理モデルで説明したい。

**データ精査により4つの重大ギャップがある。ギャップを無視した推定は解釈不能になる。**

### ギャップ1：実態は門前薬局データ

`visit_triangle` では門前フラグ TRUE 約90%、立地パターン門前型約90%。非門前は約3,060件（9.7%）が「面」の実体。

**分析の主軸（2本立て）**

- **軸A（規模）**：門前需要＝直近クリニックの患者流量。薬局施策変数はほぼ効かない。
- **軸B（成長余地）**：非門前 9.7%。5理論は主に軸Bで検証。

第1タスクで門前型 vs 非門前型の記述統計を出し前提を数値確定すること。

### ギャップ2：薬局選択率は個票MNL不可

自店来局者のみ。競合の処方箋枚数なし。クリニック総発行数なし。

**代替（この順）**

1. 集計来局率モデル（population_visitors_*）— 第一推奨
2. メッシュ単位拡張（mesh_population）
3. クリニック選択モデル（自店条件付き・バイアス明記必須）
4. Huffは記述的ベンチマークのみ

### ギャップ3：Patient Experience Engine（SEM）は不可

観測変数なし。Phase 4は行動代理指標（継続・世帯・紹介）。アンケートは別途設計。

### ギャップ4：店舗不一致

依頼書は沢良宜店・月1,800枚想定。データは**南茨木店**。月平均受診は約1,390件。Phase 0で月別実測と確認質問を出す。

---

## 1. 5理論の実行可能性

| # | 理論 | 可否 | Phase |
|---|---|---|---|
| ① | Prescription Flow | ◎ | 1–2 |
| ② | Clinic Catchment Area | ◎ | 2 |
| ③ | Pharmacy Choice Rate | △ 集計代替 | 3 |
| ④ | Patient Growth Engine | ◎ | 3–4 |
| ⑤ | Patient Experience | × SEM保留 | 4+ |

---

## 2. リポジトリ構成

```
data/raw|interim|processed
docs/ANALYSIS_BRIEF.md, DATA_DICTIONARY.md, DATA_ISSUES.md, QUESTIONS_TO_CLIENT.md
src/io.py, validate.py, features.py, models/, viz/
notebooks/, reports/figures/, tests/, config/
```

- 乱数シード固定。結果は `reports/` にファイル出力。
- 日本語フォント設定必須。
- 距離・面積は JGD2011 / EPSG:6674 投影。緯度経度ユークリッド禁止。

---

## 3. Phase 0：データ契約と検証（飛ばさない）

`src/validate.py` + pytest。結果は `docs/DATA_ISSUES.md`。

### 3.1 整合性

- PK一意：patient 8885 / visit 31924 / clinic 434 / competitor 66 / weather 706連続
- FK：visit→patient、visit→clinic（空欄6＝医療機関なしは正常）
- 受診回数総和=31924、初回≤最終、受診クリニック数=distinct
- C061欠番は欠損扱いにしない
- clinic_master(434) vs from_prescriptions(435) の差1件を特定

### 3.2 欠損・制約（再計算して明記）

患者住所なし151、クリニック座標なし11、花粉0埋め禁止、新患フラグ使用禁止、年齢は基準日固定、徒歩/自転車/道路km同時投入禁止、遠方外れ値は商圏サンプル定義、診療科マルチラベル正規化必須、prescriptions_by_ageは推計値、等（詳細は受領指示書§3.2）。

### 3.3 成果物

1. `docs/DATA_ISSUES.md`
2. `docs/QUESTIONS_TO_CLIENT.md`
3. `data/processed/` マート（visits, patients, clinics, market_areas）
4. 月別受診件数グラフ

---

## 4–9. Phase 1〜6（要約）

- **Phase 1**：門前/非門前層別のABC・時系列・外生要因・ポートフォリオ・Sankey → `reports/phase1_flow.md`
- **Phase 2**：クリニック商圏GIS・地区×クリニック・Moran/LISA・競合圧力・ネットワーク → `reports/phase2_catchment.md`
- **Phase 3**：集計来局率GLM、条件付きロジット、Huffベンチマーク、Growth分解シミュレータ → `reports/phase3_model.md`
- **Phase 4**：コホート・定着・生存・世帯・LTV・マルチレベル・クラスタ → `reports/phase4_retention.md`
- **Phase 5**：ITS / CausalImpact / DiD（イベント年表取得後）
- **Phase 6**：統合モデル・シミュレータ・学術ポジショニング

---

## 10. 追加データ依頼（優先度A/B/C）

A: クリニック総処方箋発行数、競合規模代理、他店舗同一スキーマ、イベント年表  
B: 薬効・処方日数・点数、性別、待ち時間、GBP、祝日  
C: アンケート、来局きっかけ  

→ `docs/QUESTIONS_TO_CLIENT.md` に出力。

---

## 11. 作業ルール（遵守）

1. Phase 0完了・DATA_ISSUES出力までモデリングコードを書かない。
2. 辞書と矛盾する前処理はせず ISSUES に記録。
3. `data/raw/` は読み取り専用。
4. 禁止：花粉0埋め、新患フラグ使用、徒歩/自転車/道路km同時投入、固定年齢を受診時点扱い、推計を実測扱い、自店のみで市場選択率主張、識別なし因果表現。
5. 全モデルにサンプル定義・N・欠損・適合度・限界。
6. 図表は単体可読（自店限定・推計の注記必須）。
7. 関数化 + tests。ノートブック依存禁止。
8. Phase完了時レポート冒頭に「わかった3 / わからなかった3 / 次に必要なデータ」。

---

## 12. 最初の3タスク

1. `src/io.py` + `src/validate.py` → Phase 0 整合性テストと `docs/DATA_ISSUES.md`
2. 門前/非門前層別記述統計・月別推移 → `reports/phase1_flow.md` 冒頭で「面か門前か」を数値回答
3. `population_visitors_*` + `mesh_population` で来局率テーブルと距離減衰曲線（Phase 3土台の先行検証）

---

## 付記（本リポジトリでの確定事項）

- 固定点：くつき薬局南茨木店 (34.801298494906895, 135.56540221590993)
- `patient_master` / `patient_clinic_with_distance` の住所テキスト空欄は**意図的**（座標利用のため）
- 受領直後の年齢階級 Excel 日付化（`5月9日`/`10月14日`）と日付スラッシュ形式は、分析前に正規化済み。詳細は `DATA_ISSUES.md`
