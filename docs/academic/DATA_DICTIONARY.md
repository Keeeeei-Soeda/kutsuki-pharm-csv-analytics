# DATA_DICTIONARY（受領ExcelのMarkdown化）

原典: `data/raw/DataBank_データ一覧kai.xlsx`（シート: データ辞書）

列定義の詳細（型・欠損・出典・更新方法）は原典 Excel を正とする。以下はファイル一覧。

| ファイル | 列数（辞書記載） |
|---|---:|
| `clinic_master.csv` | 37 |
| `clinic_master_from_prescriptions.csv` | 11 |
| `patient_master.csv` | 21 |
| `patient_clinic_with_distance.csv` | 30 |
| `visit_history_with_weather_pollen.csv` | 25 |
| `visit_history.csv` | 16 |
| `competitor_pharmacy.csv` | 25 |
| `weather_pollen.csv` | 10 |
| `infectious_disease_osaka_weekly.csv` | 7 |
| `mesh_population.csv` | 8 |
| `population_by_age.csv` | 4 |
| `population_visitors_2024.csv` | 4 |
| `population_visitors_2025.csv` | 4 |
| `population_visitors_2026.csv` | 4 |
| `prescriptions_monthly.csv` | 4 |
| `juryoritsu_by_age.csv` | 5 |
| `prescriptions_by_age.csv` | 5 |
| `visit_triangle.csv` | 35 |

## 注意

- 本リポジトリの `data/raw/*.csv` は ID プレフィックスを除いた論理名。
- 詳細な列定義が必要な場合は Excel または Phase 0 のマートスキーマを参照。

