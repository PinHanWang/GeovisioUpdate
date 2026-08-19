# src/preprocessing/

上傳前的 CSV 資料前處理：編碼轉換、GPS 資料解析與序列分割。

## 檔案

### `csv_encoding_converter.py` — `CSVEncodingConverter` / `convert_csv_encoding()`

自動偵測 CSV 編碼（`chardet`）並轉換為 UTF-8（無 BOM）。

- `convert_csv_encoding(csv_path, backup=False)` — 便捷函式，主要上傳流程用這個（`backup=False`，不產生 `.bak` 備份檔）
- `CSVEncodingConverter.convert_directory()` — 批次轉換整個目錄，用 `ThreadPoolExecutor` 平行處理（I/O bound），僅供獨立執行使用（`python csv_encoding_converter.py <csv_file_or_directory>`），不在主流程路徑上

### `gps_preprocessor.py` — `GPSDataPreprocessor` / `data_preprocessing()`

解析 KeyName（格式 `YYYYMMDDHHMMSSMMM_XXXXXXXXX`）取得 GPS 時間戳，計算相鄰影像的時間差與距離差（TWD97 座標系），依 `VEHICLE_TYPE` 對應的時間/距離閾值分割序列。

- `parse_keyname_to_gpstime()` — 從 KeyName 解析時間戳
- `calculate_time_differences()` — 向量化計算時間差
- `calculate_distance_differences()` — 向量化座標轉換（WGS84→TWD97）+ 距離計算（取代逐列 `apply`）
- `split_into_sequences()` — 向量化布林遮罩 + `cumsum()` 分割序列（取代逐列 `iterrows()`）
- `preprocess(csv_path)` — 完整前處理流程入口
- `data_preprocessing(csv_path, time_threshold, distance_threshold)` — 便捷函式，`upload_pipeline.py` 呼叫這個

## 呼叫端

`GeoVisioUploadPipeline.process_csv_file()`（`src/upload_pipeline.py`）依序呼叫 `convert_csv_encoding()` → `data_preprocessing()`，兩者都是同步阻塞函式，用 `asyncio.to_thread()` 包裝避免卡住其他協程（例如 Docker 監控背景任務）。
