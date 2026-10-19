# UI表示修正の指示書（kutsuki-pharm_csv-analytics / D案テーマ）

公開ページ `docs/*.html` 向け。生CSVが無いため phase*.py は再実行せず、次の3層で直す。

1. `templates/_sidebar.css` / `_theme_d.css` / `_sidebar.js` → `python3 -m src.apply_ui_shell` で注入
2. `docs/js/**` → 直接反映
3. `src/viz/sidebar.py` の `fix_display_text()` で生成済みHTMLの文言を置換（生成元スクリプトも同時修正）

文言は「門前（40m以内）／門前以外」で統一。「非門前」は専門家向け折りたたみ以外では使わない。

対象問題は #1〜#22（凡例重なり・目標線・クリニック名切れ・割合ラベル・Phase2二重表示・チャート枠CSS・KPI折り返し・Phase5推移・半角カナ・サイドバーチップ・表スクロール・マップ凡例など）。詳細はチャット指示書を参照。

確認:

```bash
python3 -m src.apply_ui_shell
python3 -m pytest -q tests/test_sidebar.py
node --test tests/js/*.mjs
```
