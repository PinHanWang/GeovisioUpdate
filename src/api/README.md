# src/api/

GeoVisio API 的所有對外請求與影像上傳邏輯。

## 檔案

### `geovisio_api_client.py` — `GeoVisioAPIClient`

封裝 GeoVisio REST API 的請求與認證，由 `GeoVisioUploadPipeline` 建立唯一實例並注入其他模組（不在子模組內自行建立 session）。

主要方法：
- `get_token()` / `_get_auth_headers()` — 靜態 HS256 JWT token 認證（見 [根目錄 README](../../README.md#認證機制)）
- `create_collection()` — 建立新 Collection
- `get_all_collections(use_cache=False)` — 取得所有 Collection；`use_cache=True` 時同一次執行內重複呼叫只會真正打一次 API（用於續傳搜尋，見 `find_collection_by_sequence()`）
- `get_collection_by_id()` / `get_collection_items()` / `get_uploaded_keynames()` — 查詢既有 Collection 內容，用於續傳判斷
- `find_collection_by_sequence(seq_id, collection_date)` — 依序列 ID + 日期搜尋既有 Collection
- `health_check()` — API 健康檢查

### `image_uploader.py` — `ImageUploader` / `ImageRecord`

影像上傳的核心邏輯：流式上傳、去重整合、重試、資源監控整合、記憶體管理（`MemoryAwareGC`）。

- `ImageRecord`：dataclass，封裝單張影像的上傳資訊（`keyname`/`gps_time`/`gps_x`/`gps_y`/`speed`/`img_url`/`seq`），取代逐一展開傳遞的位置參數。`ImageRecord.from_row(row, seq)` 從 DataFrame row 建立。
- `upload_sequence(df, collection_id)` — 上傳完整序列，依 `Settings.BATCH_TIERS` 分批、批次前用 `DuplicateChecker.preload_keynames()` 預熱去重快取、批次前用 `ResourceMonitor` 檢查資源
- `safe_upload_image(semaphore, collection_id, record)` → `_upload_single_image_impl(collection_id, record)` — 單張影像上傳，`tenacity` 指數退避重試。只有 `RETRYABLE_EXCEPTIONS`（網路類錯誤）會重試；其餘例外（程式邏輯錯誤等）視為永久性失敗，直接不重試
- `session` 一律使用注入的 `self.session`（來自 `api_client.session`），不在函式參數裡逐一傳遞

### `exceptions.py`

- `ImageAlreadyExistsError` — 影像已存在（409 或去重命中），視為成功
- `RetryableUploadError` — 可重試的暫時性錯誤（tenacity 攔截目標）

## 依賴關係

`GeoVisioUploadPipeline`（`src/upload_pipeline.py`）注入 `dedup_checker`（`src.optimization.duplicate_checker`）、`resource_monitor`（`src.optimization.resource_monitor`）、`seq_handler`（`src.optimization.sequence_batch_handler`）、`failure_tracker`（`src.reporting.failure_tracker`）到 `ImageUploader`。
