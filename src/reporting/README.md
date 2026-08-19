# src/reporting/

上傳失敗記錄追蹤與報告產生。

## 檔案

### `failure_tracker.py` — `FailureTracker`

- `record_upload_failure(keyname, collection_id, error, retry_count)` — 記錄單張影像上傳失敗
- `record_collection_failure(collection_id)` — 記錄整個 Collection 失敗
- `get_failure_summary()` / `print_summary()` — 統計摘要
- `save_reports(output_dir)` — 產生失敗報告 CSV（`{timestamp}_upload_failures.csv`、`{timestamp}_failed_collections.csv`），內部用 `asyncio.to_thread()` 包裝同步的 `pd.to_csv()`，避免卡住 event loop
- `get_failure_tracker()` — 惰性工廠函式，取得全域 singleton；其他模組一律用這個，不要直接 `FailureTracker()`

## 呼叫端

`ImageUploader`（`src/api/image_uploader.py`）的 tenacity 重試用盡回呼（`_log_retry_exhausted`）呼叫 `record_upload_failure()`/`record_collection_failure()`。`GeoVisioUploadPipeline` 在流程結束時呼叫 `save_reports()`。
