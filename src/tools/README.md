# src/tools/

獨立執行的工具程式，不整合到主上傳流程中，都直接連 PostgreSQL 查詢/操作。

兩者都用 `Settings.DATABASE_URL` 當 `--db-url` 的預設值（可用 `--db-url` 覆蓋，方便臨時對接不同資料庫）。

## 檔案

### `check_duplicates.py`

檢查資料庫內的重複影像（KeyName 重複、MD5 重複、KeyName 相同但 MD5 不同的異常情況），輸出 CSV 報告。

```bash
python -m src.tools.check_duplicates                                    # 完整檢查並產生報告
python -m src.tools.check_duplicates -f "20250829113426796_S9GLCPJ76.jpg"  # 查詢特定檔名
python -m src.tools.check_duplicates -o ./reports                       # 指定輸出目錄
```

輸出至 `output/duplicate_reports/`：`{timestamp}_keyname_duplicates.csv`、`{timestamp}_md5_duplicates.csv`、`{timestamp}_keyname_md5_mismatch.csv`。

> 注意：此檔案內有自己的 `DuplicateChecker` 類別，是直接下 SQL 查詢的獨立實作，跟 `src/optimization/duplicate_checker.py` 的 `DuplicateChecker`（上傳流程內的去重快取邏輯）是同名但不同的兩個類別，不要混淆。

### `delete_all_duplicates.py`

讀取 `check_duplicates.py` 產生的重複報告 CSV，刪除 CSV 中列出的所有 Collection（及其下所有影像）。**`--dry-run` 是刪除前務必先跑過一次的安全閥。**

```bash
python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv --dry-run  # 預覽
python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv            # 執行刪除（需輸入 YES 確認）
```
