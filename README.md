# TMSUpdate - GeoVisio 影像上傳模組

GeoVisio 街景影像批次上傳系統，支援大量影像的自動化上傳、續傳、去重檢查與資源監控。

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [安裝與設定](#安裝與設定)
- [快速開始](#快速開始)
- [設定參數](#設定參數)
- [模組說明](#模組說明)
- [工具程式](#工具程式)
- [上傳流程](#上傳流程)
- [常見問題](#常見問題)

---

## 功能特色

| 功能 | 說明 |
|------|------|
| **批次上傳** | 支援大量影像自動化上傳至 GeoVisio 平台 |
| **智慧續傳** | 中斷後可自動從上次進度繼續上傳 |
| **去重檢查** | 支援 KeyName 和 MD5 雙重去重，避免重複上傳 |
| **資源監控** | 基於 Job Queue 的動態資源監控與調整 |
| **指數退避重試** | 網路錯誤時自動重試，採用指數退避策略 |
| **記憶體優化** | 流式上傳、LRU 快取、智慧 GC 回收 |
| **日期過濾** | 支援指定日期或截止日期過濾 |
| **Docker 監控** | 背景監控 GeoVisio 容器資源使用狀態 |

---

## 系統架構

```
TMSUpdate/
├── main.py                     # 主程式入口
├── README.md                   # 本文件
│
├── api/                        # API 層
│   ├── geovisio_api_client.py  # GeoVisio API 客戶端
│   ├── image_uploader.py       # 影像上傳管理器
│   └── exceptions.py           # 自定義例外
│
├── config/                     # 設定層
│   ├── settings.py             # 統一設定管理
│   └── logging_config.py       # 日誌設定
│
├── core/                       # 核心功能
│   ├── csv_encoding_converter.py   # CSV 編碼轉換
│   ├── image_data_preprocessor.py  # GPS 資料前處理
│   └── failure_checker.py          # 失敗追蹤器
│
├── optimization/               # 效能優化
│   ├── duplicate_checker.py    # 去重檢查器
│   ├── resource_monitor.py     # 資源監控器
│   └── sequence_batch_handler.py   # 序列批次處理器
│
├── pipeline/                   # 流程管理
│   └── upload_pipeline.py      # 上傳流程主控
│
├── tools/                      # 工具程式
│   ├── check_duplicates.py     # 重複影像檢查
│   └── delete_all_duplicates.py    # 重複影像刪除
│
└── utils/                      # 工具函式
    └── docker_monitor.py       # Docker 容器監控
```

---

## 安裝與設定

### 1. 安裝相依套件

```bash
pip install -r requirements.txt
```

主要相依套件：
- `aiohttp` - 非同步 HTTP 客戶端
- `asyncpg` - PostgreSQL 非同步驅動
- `pandas` - 資料處理
- `tenacity` - 重試機制
- `pyproj` - 座標轉換
- `python-dotenv` - 環境變數管理
- `psutil` - 系統資源監控

### 2. 設定環境變數

在專案根目錄建立 `.env` 檔案：

```bash
# ========================================
# 必要設定
# ========================================
TMS_GEOVISIO_URL=https://your-geovisio-api.com
CSV_FILE_PATH=./data/input.csv
IMAGE_BASE_PATH=D:/Images/

# 資料庫連線 (用於去重檢查)
DATABASE_URL=postgresql://user:password@host:port/database

# ========================================
# 日期過濾 (擇一設定)
# ========================================
# 指定日期 - 只處理這些日期 (最高優先，逗號分隔)
SPECIFIED_DATES=2025-08-29,2025-08-30

# 截止日期 - 跳過早於此日期的資料
# CUTOFF_DATE=2025-06-01

# ========================================
# 效能調校 (選填)
# ========================================
MAX_CONCURRENT_UPLOADS=5
UPLOAD_TIMEOUT=60
SEQUENCE_DELAY=3
BATCH_DELAY=300
MAX_POOL_SIZE=10

# ========================================
# 功能開關 (選填)
# ========================================
ENABLE_DEDUPLICATION=true
ENABLE_MD5_CHECK=true
ENABLE_RESOURCE_MONITOR=true
VEHICLE_TYPE=CAR
```

---

## 快速開始

### 基本執行

```bash
# 從專案根目錄執行
python -m src.module.TMSUpdate.main

# 或直接執行
cd src/module/TMSUpdate
python main.py
```

### 只上傳指定日期

```bash
# 設定 .env
SPECIFIED_DATES=2025-08-29,2025-08-30

# 執行
python -m src.module.TMSUpdate.main
```

### 執後檢查重複

```bash
# 檢查資料庫中的重複影像
python tools/check_duplicates.py

# 查詢特定檔名
python tools/check_duplicates.py -f "20250829113426796_S9GLCPJ76.jpg"
```

---

## 設定參數

### 核心參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `TMS_GEOVISIO_URL` | - | GeoVisio API 位址 (必填) |
| `CSV_FILE_PATH` | - | 輸入 CSV 檔案路徑 (必填) |
| `IMAGE_BASE_PATH` | - | 影像檔案根目錄 (必填) |
| `DATABASE_URL` | - | PostgreSQL 連線字串 |

### 日期過濾

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `SPECIFIED_DATES` | (空) | 指定要處理的日期，逗號分隔 (最高優先) |
| `CUTOFF_DATE` | 2025-06-01 | 截止日期，跳過早於此日期的資料 |

**優先順序**：`SPECIFIED_DATES` > `CUTOFF_DATE` > 處理所有日期

### 效能參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `MAX_CONCURRENT_UPLOADS` | 5 | 最大並發上傳數 |
| `UPLOAD_TIMEOUT` | 60 | 單張圖片上傳超時 (秒) |
| `SEQUENCE_DELAY` | 3 | 序列間延遲 (秒) |
| `BATCH_DELAY` | 300 | 日期組間延遲 (秒) |
| `MAX_POOL_SIZE` | 10 | HTTP 連線池大小 |

### 重試參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `RETRY_ATTEMPTS` | 5 | 最大重試次數 |
| `RETRY_MIN_WAIT` | 1 | 最小等待秒數 |
| `RETRY_MAX_WAIT` | 30 | 最大等待秒數 |

### 批次處理參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `SEQUENCE_SMALL_THRESHOLD` | 500 | 小型序列閾值 |
| `SEQUENCE_MEDIUM_THRESHOLD` | 2000 | 中型序列閾值 |
| `BATCH_SIZE_SMALL` | 50 | 小型序列批次大小 |
| `BATCH_SIZE_MEDIUM` | 30 | 中型序列批次大小 |
| `BATCH_SIZE_LARGE` | 20 | 大型序列批次大小 |

### 資源監控參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `JOB_QUEUE_SAFE_THRESHOLD` | 100 | Job Queue 安全閾值 |
| `JOB_QUEUE_WARNING_THRESHOLD` | 500 | Job Queue 警告閾值 |
| `RESOURCE_CHECK_INTERVAL` | 60 | 資源檢查間隔 (秒) |

### 功能開關

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `ENABLE_DEDUPLICATION` | true | 啟用去重檢查 |
| `ENABLE_MD5_CHECK` | true | 啟用 MD5 檢查 |
| `ENABLE_RESOURCE_MONITOR` | true | 啟用資源監控 |
| `VEHICLE_TYPE` | CAR | 車輛類型 (CAR/MOTORCYCLE) |

---

## 模組說明

### API 層 (`api/`)

#### GeoVisioAPIClient
GeoVisio API 的封裝客戶端，提供以下功能：
- `create_collection()` - 建立新的 Collection
- `get_all_collections()` - 取得所有 Collection
- `get_collection_items()` - 取得 Collection 內的影像
- `get_uploaded_keynames()` - 取得已上傳的 KeyName 集合
- `find_collection_by_sequence()` - 根據序列搜尋 Collection

#### ImageUploader
影像上傳管理器，負責：
- 流式上傳 (不預載入記憶體)
- 指數退避重試機制
- 去重檢查整合
- 批次處理與並發控制
- 智慧記憶體回收

### 核心功能 (`core/`)

#### GPSDataPreprocessor
GPS 資料前處理器，功能包括：
- 從 KeyName 解析 GPS 時間
- 計算相鄰影像的時間差和距離差
- 根據閾值自動分割序列
- 支援 TWD97 座標轉換

#### FailureTracker
失敗追蹤器，記錄：
- 上傳失敗的影像
- 失敗的 Collection
- 產生失敗報告 (CSV)

### 優化模組 (`optimization/`)

#### DuplicateChecker
去重檢查器，特點：
- KeyName 快速檢查
- MD5 精確檢查
- LRU 快取機制
- 支援本地檔案和 URL

#### ResourceMonitor
資源監控器，基於 Job Queue：
- 動態調整 batch size
- 動態調整批次延遲
- 等待資源恢復機制

### 流程管理 (`pipeline/`)

#### GeoVisioUploadPipeline
主流程控制器，負責：
- 模組初始化與資源管理
- CSV 前處理與日期分組
- 續傳邏輯判斷
- 統一的錯誤處理與清理

---

## 工具程式

### check_duplicates.py - 重複影像檢查

```bash
# 完整檢查並產生報告
python tools/check_duplicates.py

# 指定輸出目錄
python tools/check_duplicates.py -o ./reports

# 查詢特定檔名
python tools/check_duplicates.py -f "20250829113426796_S9GLCPJ76.jpg"
```

輸出報告：
- `{timestamp}_keyname_duplicates.csv` - KeyName 重複報告
- `{timestamp}_md5_duplicates.csv` - MD5 重複報告
- `{timestamp}_keyname_md5_mismatch.csv` - 不一致報告

### delete_all_duplicates.py - 重複影像刪除

```bash
# 預覽模式 (不實際刪除)
python tools/delete_all_duplicates.py -i keyname_duplicates.csv --dry-run

# 執行刪除 (需輸入 YES 確認)
python tools/delete_all_duplicates.py -i keyname_duplicates.csv
```

---

## 上傳流程

### 整體流程圖

```
┌─────────────────────────────────────────────────────────────┐
│                       主程式入口                              │
│                       (main.py)                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 驗證環境變數                                              │
│ 2. 初始化模組 (Session, API Client, Uploader, 監控器)        │
│ 3. 處理 CSV 檔案 (編碼轉換, 資料前處理)                       │
│ 4. 按日期分組資料                                            │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    日期迴圈處理                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 檢查日期過濾 (SPECIFIED_DATES / CUTOFF_DATE)         │    │
│  │    ↓                                                │    │
│  │ 按 group_id 分組序列                                 │    │
│  │    ↓                                                │    │
│  │ 序列迴圈處理                                         │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    序列上傳邏輯                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 1. 檢查第一張 KeyName 是否存在 (本地 DB)              │    │
│  │ 2. 搜尋既有 Collection (API)                        │    │
│  │ 3. 判斷：新建 Collection 或 續傳模式                  │    │
│  │ 4. 執行影像上傳 (批次處理, 並發控制)                  │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 5. 儲存報告 (處理結果, 失敗記錄)                              │
│ 6. 清理資源 (關閉連線, GC)                                   │
└─────────────────────────────────────────────────────────────┘
```

### 續傳邏輯

```
                    ┌─────────────────┐
                    │  開始處理序列    │
                    └────────┬────────┘
                             │
                             ▼
              ┌──────────────────────────────┐
              │ 檢查第一張 KeyName 是否存在   │
              │ (本地資料庫)                  │
              └──────────────┬───────────────┘
                             │
              ┌──────────────┴───────────────┐
              │                              │
              ▼                              ▼
       ┌────────────┐                 ┌────────────┐
       │  不存在     │                 │   存在     │
       └─────┬──────┘                 └─────┬──────┘
             │                              │
             ▼                              ▼
    ┌─────────────────┐         ┌─────────────────────────┐
    │ 建立新 Collection │         │ 搜尋既有 Collection     │
    └────────┬────────┘         └───────────┬─────────────┘
             │                              │
             │                   ┌──────────┴──────────┐
             │                   │                     │
             │                   ▼                     ▼
             │            ┌───────────┐         ┌───────────┐
             │            │ 找到      │         │ 未找到    │
             │            └─────┬─────┘         └─────┬─────┘
             │                  │                     │
             │                  ▼                     │
             │         ┌────────────────────┐         │
             │         │ 查詢 API 已上傳數量 │         │
             │         └────────┬───────────┘         │
             │                  │                     │
             │      ┌───────────┴───────────┐         │
             │      │                       │         │
             │      ▼                       ▼         │
             │ ┌─────────┐           ┌──────────┐    │
             │ │ 已完成  │           │ 未完成   │    │
             │ │ (跳過)  │           │ (續傳)   │    │
             │ └─────────┘           └────┬─────┘    │
             │                            │          │
             └────────────────────────────┼──────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │ 執行影像上傳         │
                               │ (只上傳未完成部分)   │
                               └─────────────────────┘
```

---

## 常見問題

### Q: 如何處理上傳中斷？

程式支援自動續傳。重新執行程式時，會：
1. 檢查本地資料庫中已存在的 KeyName
2. 透過 API 搜尋對應的 Collection
3. 比對已上傳數量，只上傳未完成的部分

### Q: 如何只上傳特定日期？

在 `.env` 中設定 `SPECIFIED_DATES`：

```bash
# 單一日期
SPECIFIED_DATES=2025-08-29

# 多個日期
SPECIFIED_DATES=2025-08-29,2025-08-30,2025-09-01
```

### Q: 如何調整上傳速度？

調整以下參數：
- 增加 `MAX_CONCURRENT_UPLOADS` (建議 5-20)
- 減少 `SEQUENCE_DELAY` 和 `BATCH_DELAY`
- 增加 `BATCH_SIZE_*` 參數

### Q: 去重檢查失敗怎麼辦？

設定 `DEDUP_FAILURE_BEHAVIOR`：
- `continue` (預設) - 繼續上傳
- `skip` - 跳過該影像

### Q: 如何清理重複影像？

```bash
# 1. 先檢查重複
python tools/check_duplicates.py

# 2. 預覽要刪除的內容
python tools/delete_all_duplicates.py -i output/duplicate_reports/xxx_keyname_duplicates.csv --dry-run

# 3. 確認後執行刪除
python tools/delete_all_duplicates.py -i output/duplicate_reports/xxx_keyname_duplicates.csv
```

### Q: 輸出的報告在哪裡？

- 處理結果：`logs/{timestamp}_processing_results.csv`
- 失敗報告：`logs/{timestamp}_upload_failures.csv`
- 重複檢查：`output/duplicate_reports/`

---

## 授權

內部使用

## 維護者

TMS 開發團隊
