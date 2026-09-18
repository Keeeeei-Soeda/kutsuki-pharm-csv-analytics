# DATA_ISSUES（Phase 0 自動生成）

- 生成対象店舗: **くつき薬局南茨木店**（固定点 34.801298494906895, 135.56540221590993）
- 受診期間: 2024-09-02 〜 2026-07-31

## わかったこと（先行）

1. 門前フラグ TRUE: **28,824** 件 / 立地パターン門前型: **28,518** 件 → 実態は門前中心。
2. 月平均受診件数: **1388.0** 件（23か月）。依頼書の月1,800枚とは乖離。
3. 患者住所テキストは両患者ファイルで全空欄だが、これは座標利用のための**意図的設計**（依頼者確認済）。GISは緯度経度を使用する。

## 整合性テスト結果

- 全件OK: **YES**（失敗 0 / 14）

- [OK] `patient_master.患者ID` — `{'column': '患者ID', 'rows': 8885, 'nunique': 8885, 'duplicates': 0, 'ok': True, 'expected_rows': 8885}`
- [OK] `visit_history.受診ID` — `{'column': '受診ID', 'rows': 31924, 'nunique': 31924, 'duplicates': 0, 'ok': True, 'expected_rows': 31924}`
- [OK] `clinic_master.クリニックID` — `{'column': 'クリニックID', 'rows': 434, 'nunique': 434, 'duplicates': 0, 'ok': True, 'expected_rows': 434}`
- [OK] `competitor_pharmacy.競合薬局ID` — `{'column': '競合薬局ID', 'rows': 66, 'nunique': 66, 'duplicates': 0, 'ok': True, 'expected_rows': 66}`
- [OK] `weather_pollen.日付` — `{'column': '日付', 'rows': 706, 'nunique': 706, 'duplicates': 0, 'ok': True, 'expected_rows': 706}`
- [OK] `weather_pollen.連続日数` — `{'ok': True, 'rows': 706, 'span_days': 706, 'min': '2024-09-01', 'max': '2026-08-07'}`
- [OK] `FK visit_history.患者ID→patient_master` — `{'ok': True, 'missing': 0}`
- [OK] `FK visit_history.クリニックID→clinic_master` — `{'ok': True, 'null_clinic_rows': 6, 'orphan_ids': [], 'orphan_count': 0}`
- [OK] `patient_master.受診回数合計==31924` — `{'ok': True, 'sum': 31924}`
- [OK] `初回受診日≤最終受診日` — `{'ok': True, 'violations': 0}`
- [OK] `受診クリニック数==visit distinct` — `{'ok': True, 'mismatches': 0}`
- [OK] `C061欠番（欠損扱いにしない）` — `{'ok': True, 'has_C061': False, 'has_C014': True}`
- [OK] `clinic_master vs from_prescriptions 件数差` — `{'clinic_master_n': 434, 'from_prescriptions_n': 435, 'only_in_from_prescriptions': ['C061'], 'only_in_clinic_master': [], 'ok': True}`
- [OK] `visit_triangle.受診ID == visit_history` — `{'ok': True, 'triangle_n': 31924, 'visit_n': 31924}`

### clinic_master(434) vs clinic_master_from_prescriptions(435)

- from_prescriptions のみ: `['C061']` / 名称: `{'C061': '医療法人桜会\u3000はしづめ内科'}`
- C061 は欠番（C014へ統合済）。欠損として扱わない。

## 欠損・制約（実データ再計算）

| 項目 | 実測 | 分析上の扱い |
|---|---|---|
| 患者座標なし | 151人 / 受診317件 | GISから除外。感度分析 |
| クリニック座標なし or 医療機関なし | 施設11 / 受診側欠損扱い29 | GISから除外。医療機関なし6件は明示フラグ |
| 座標精度 | {'街区': 8621, 'nan': 151, '町名': 87, '丁目': 15, '市区町村': 11}（町名+市区町村=98人） | メッシュ分析で重み/除外 |
| 花粉欠損（visit_weather） | {'スギ': 20991, 'ヒノキ科': 20991, '花粉合計': 20991} / 実測あり受診 10933 | **0埋め禁止**。飛散期のみ |
| 新患フラグ | {'1': 8867, '0': 18} | **使用禁止**。初回受診日==受診日で再定義 |
| 年齢 | 年齢は基準日2026-07-31時点で固定（辞書記載） | 時系列は生年月日から再計算（生年月日は現状全空欄→要追加取得） |
| 日曜受診 | 0件 | 曜日モデルは月〜土 |
| 徒歩/自転車所要の線形従属 | 中央残差(分) 徒歩=0.02499999999999991, 自転車=0.02400000000000002 | 道路kmと同時投入禁止 |
| 遠方外れ値 | 患者→薬局道路km max=1710.1, 迂回率 max=10103.1 | 主分析は商圏内（例≤10km） |
| 商圏内クリニック | {'FALSE': 315, 'TRUE': 119} | 軸A/B設計に使用 |
| 住所テキスト空欄 | 意図的（座標利用） | 世帯推定は現状不可。visit_triangleの市区町村で地区分析 |

## 受領時の正規化メモ

- `patient_master` / `patient_clinic_with_distance` で年齢階級の Excel 日付化（`5月9日`→`5-9`, `10月14日`→`10-14`）と日付 `YYYY/M/D`→`YYYY-MM-DD` を修正済み。
- `data/raw` の当該2ファイルは修正後コピーを含む。以降 raw は読み取り専用として扱う。
- 生年月日は全空欄のまま（マスクの可能性）。

## 禁止事項リマインダ

- 花粉0埋め / 新患フラグ使用 / 徒歩・自転車・道路km同時投入 / 固定年齢を受診時点扱い / 推計を実測扱い / 自店のみで市場選択率主張 / 識別なし因果表現

