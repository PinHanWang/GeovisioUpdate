# src/optimization/

上傳過程中的效能控制：去重檢查、資源監控（動態節流）、批次策略。

三個模組都是 singleton 服務，統一用惰性工廠函式取得（避免模組載入時就有副作用）：

```python
get_duplicate_checker()        # duplicate_checker.py
get_resource_monitor()         # resource_monitor.py
get_sequence_batch_handler()   # sequence_batch_handler.py
```

## 檔案

### `duplicate_checker.py` — `DuplicateChecker` / `LRUCache`

雙重去重：KeyName（快，查 `metadata->>'originalFileName'`）+ MD5（精確，查 `original_content_md5`），用 `LRUCache` 快取查詢結果。

- `should_skip_upload(keyname, img_url, check_md5, session)` — 主要入口，先查 KeyName 再查 MD5
- `preload_keynames(keynames)` — 批次上傳前用 1 次 `IN`/`ANY` 查詢預熱一整批 KeyName 的快取，取代逐張查詢
- `calculate_md5_from_url()` — 下載影像計算 MD5，內部 `_download_and_hash()` 用 `tenacity` 包裝，暫時性網路錯誤會重試最多 3 次
- `initialize()` 時會呼叫 `_load_keyname_cache()` 預載最近的 KeyName（數量 = `Settings.DEDUP_MAX_CACHE_SIZE // 2`）

### `resource_monitor.py` — `ResourceMonitor`

輪詢 GeoVisio Job Queue 積壓數量，依 `Settings.JOB_QUEUE_SAFE_THRESHOLD` / `JOB_QUEUE_WARNING_THRESHOLD` 判斷 `safe`/`warning`/`critical` 三種狀態。

- `check_resources()` — 回傳 `(is_safe, stats)`；短 TTL 快取（`Settings.RESOURCE_QUEUE_CACHE_TTL`，預設 5 秒）避免同一序列開頭連續呼叫時重複查 DB
- `get_dynamic_batch_size()` / `get_dynamic_batch_delay()` — 依目前狀態動態調整批次大小/延遲
- `wait_for_resources(max_wait)` — 積壓過高時等待，輪詢間隔用 `Settings.RESOURCE_CHECK_INTERVAL`

### `sequence_batch_handler.py` — `SequenceBatchHandler`

依序列大小（張數）選擇批次策略，實際配置來自 `Settings.get_batch_config()` / `Settings.BATCH_TIERS`（小/中/大三種分級，各自有 batch_size/batch_delay/max_concurrent）。

- `classify_sequence(size)` — 分類 `'small'`/`'medium'`/`'large'`
- `get_batch_config(size)` — 取得批次配置（委派給 `Settings.get_batch_config()`）
- `split_into_batches(df, batch_size)` — 把序列切成多個批次 DataFrame

## 呼叫端

`GeoVisioUploadPipeline.initialize_modules()`（`src/upload_pipeline.py`）呼叫三個 `get_xxx()` 工廠函式，注入到 `ImageUploader`。`GeoVisioUploadPipeline._resource_aware_sleep()` 也會查詢 `resource_monitor` 狀態，決定序列間/批次間的固定延遲要不要跳過。
