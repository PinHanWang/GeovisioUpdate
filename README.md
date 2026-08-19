# GeoVisio 影像上傳系統

GeoVisio (Panoramax) 街景影像批次上傳系統，支援大量影像的自動化上傳、續傳、去重檢查與資源監控。

## 目錄

- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [安裝與設定](#安裝與設定)
- [認證機制](#認證機制)
- [快速開始](#快速開始)
- [設定參數](#設定參數)
- [模組說明](#模組說明)
- [工具程式](#工具程式)
- [上傳流程](#上傳流程)
- [GeoVisio 伺服器端部署備註](#geovisio-伺服器端部署備註)
- [常見問題](#常見問題)

---

## 功能特色

| 功能 | 說明 |
|------|------|
| **批次上傳** | 支援大量影像自動化上傳至 GeoVisio (Panoramax) 平台 |
| **GeoVisio JWT 認證** | 使用 GeoVisio 內部 HS256 JWT token 認證 |
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
GeovisioUpdate/
├── src/
│   ├── main.py                         # 主程式入口
│   │
│   ├── api/                            # API 層
│   │   ├── geovisio_api_client.py      # GeoVisio API 客戶端 (認證 & 請求)
│   │   ├── image_uploader.py           # 影像上傳管理器
│   │   └── exceptions.py               # 自定義例外
│   │
│   ├── config/                         # 設定層
│   │   ├── settings.py                 # 統一設定管理 (含認證設定)
│   │   └── logging_config.py           # 日誌設定
│   │
│   ├── core/                           # 核心功能
│   │   ├── csv_encoding_converter.py   # CSV 編碼轉換
│   │   ├── image_data_preprocessor.py  # GPS 資料前處理 & 序列分割
│   │   └── failure_checker.py          # 失敗追蹤器
│   │
│   ├── optimization/                   # 效能優化
│   │   ├── duplicate_checker.py        # 去重檢查器
│   │   ├── resource_monitor.py         # 資源監控器 (Job Queue)
│   │   └── sequence_batch_handler.py   # 序列批次處理器
│   │
│   ├── pipeline/                       # 流程管理
│   │   └── upload_pipeline.py          # 上傳流程主控
│   │
│   ├── tools/                          # 工具程式
│   │   ├── check_duplicates.py         # 重複影像檢查
│   │   └── delete_all_duplicates.py    # 重複影像刪除
│   │
│   └── utils/                          # 工具函式
│       └── docker_monitor.py           # Docker 容器監控 (Hawser)
│
├── configs/                            # 靜態設定檔
│   ├── carAngleTable.csv               # 車輛角度對照表
│   └── iiiSignName.json                # 交通標誌名稱
│
├── data/                               # 輸入資料 (CSV)
├── logs/                               # 執行日誌 & 報告輸出
├── .env                                # 環境變數 (認證 token、路徑、參數)
├── requirements.txt                    # Python 依賴套件
└── README.md                           # 本文件
```

---

## 安裝與設定

### 1. 安裝相依套件

```bash
pip install -r requirements.txt
```

主要相依套件：

| 套件 | 用途 |
|------|------|
| `aiohttp` | 非同步 HTTP 客戶端 |
| `aiofiles` | 非同步檔案操作 |
| `asyncpg` | PostgreSQL 非同步驅動 |
| `pandas` | 資料處理 |
| `tenacity` | 重試機制 (指數退避) |
| `pyproj` | 座標轉換 (WGS84 ↔ TWD97) |
| `python-dotenv` | 環境變數管理 |
| `psutil` | 系統資源監控 |
| `chardet` | CSV 編碼偵測 |

### 2. 設定環境變數

在專案根目錄建立 `.env` 檔案（可參考 `.env.example`）：

```bash
# ========================================
# 必要設定
# ========================================
TMS_GEOVISIO_URL=http://192.168.61.1:5001
CSV_FILE_PATH=D:\path\to\your\data.csv
IMAGE_BASE_PATH=D:\path\to\your\images

# ========================================
# 認證設定
# ========================================
ENABLE_AUTH=true
GEOVISIO_API_TOKEN=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# ========================================
# 資料庫 (去重檢查用)
# ========================================
DATABASE_URL=postgresql://user:password@192.168.61.3:5432/geovisio
```

---

## 認證機制

### 架構說明

GeoVisio (Panoramax) 的 API 認證使用**內部 HS256 JWT token**，而非直接使用 Keycloak OAuth token。

```
上傳腳本                     GeoVisio API                    PostgreSQL
   │                            │                               │
   │  Bearer <JWT token>        │                               │
   ├───────────────────────────►│                               │
   │                            │  用 FLASK_SECRET_KEY          │
   │                            │  解碼 JWT (HS256)             │
   │                            │                               │
   │                            │  取出 token id (sub)          │
   │                            │  查詢 tokens 表               │
   │                            ├──────────────────────────────►│
   │                            │  找到 account_id              │
   │                            │◄──────────────────────────────┤
   │                            │                               │
   │        200 OK              │                               │
   │◄───────────────────────────┤                               │
```

**重點：JWT token 的有效性只依賴兩個東西：**

1. `FLASK_SECRET_KEY`（docker-compose.yml 中設定，固定值）
2. PostgreSQL `tokens` 表中的記錄（有 volume 持久化）

與 Keycloak 完全無關。Keycloak 重啟不影響上傳 token。

### 產生 Token

Token 的產生需要在 GeoVisio **伺服器端** (Docker Host) 操作，共三個步驟：

#### Step 1: 確認帳號存在

```bash
docker exec geovisio_dev-db-pg-geovisio-1 psql -U gvs -d geovisio \
  -c "SELECT id, name, role FROM accounts;"
```

記下目標帳號的 `id`（例如 `7dbd6e37-0b34-4c7e-847f-0d6924f37ca5`）。

#### Step 2: 在 tokens 表建立記錄

```bash
docker exec geovisio_dev-db-pg-geovisio-1 psql -U gvs -d geovisio \
  -c "INSERT INTO tokens (account_id, description) VALUES ('<ACCOUNT_ID>', 'API upload token') RETURNING id;"
```

記下回傳的 token `id`（例如 `3e13b3d6-921c-4220-8d1a-f05222372717`）。

#### Step 3: 產生 JWT

```bash
docker exec geovisio_dev-api-1 bash -c "python -c \"from geovisio import create_app; app = create_app(); ctx = app.app_context(); ctx.push(); from geovisio.web.tokens import _generate_jwt_token; print(_generate_jwt_token('<TOKEN_ID>'))\""
```

> **注意：** `_generate_jwt_token()` 是 GeoVisio API 容器內部的函數，
> 位於容器內的 `/opt/geovisio/geovisio/web/tokens.py`，
> 不是本專案的程式碼。它使用 `FLASK_SECRET_KEY` 以 HS256 演算法簽發 JWT，
> JWT payload 包含 `{"iss": "geovisio", "sub": "<token_id>"}`。
> 必須透過 `docker exec` 在 API 容器內執行。

產生的 JWT 放入 `.env` 的 `GEOVISIO_API_TOKEN` 即可。

### 驗證 Token

```powershell
Invoke-WebRequest -Uri "http://192.168.61.1:5001/api/users/me" `
  -Headers @{"Authorization"="Bearer <YOUR_JWT_TOKEN>"}
```

回傳 200 並包含帳號資訊即表示 token 有效。

### Token 失效條件

| 情境 | 是否失效 |
|------|----------|
| Keycloak 重啟 | ❌ 不影響 |
| API 容器重啟 | ❌ 不影響 |
| `FLASK_SECRET_KEY` 變更 | ✅ 失效，需重新產生 |
| PostgreSQL 資料遺失 | ✅ 失效，需重新建立 |
| 手動 DELETE revoke token | ✅ 失效 |

---

## 快速開始

### 基本執行

```bash
python -m src.main
```

### 只上傳指定日期

在 `.env` 中設定：
```bash
SPECIFIED_DATES=2025-08-29,2025-08-30
```

### 檢查重複影像

```bash
python -m src.tools.check_duplicates
python -m src.tools.check_duplicates -f "20250829113426796_S9GLCPJ76.jpg"
```

---

## 設定參數

### 核心參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `TMS_GEOVISIO_URL` | - | GeoVisio API 位址 (必填) |
| `CSV_FILE_PATH` | - | 輸入 CSV 檔案路徑 (必填) |
| `IMAGE_BASE_PATH` | - | 影像檔案根目錄 (必填) |
| `DATABASE_URL` | - | PostgreSQL 連線字串 (去重用) |

### 認證參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `ENABLE_AUTH` | false | 啟用 API 認證 |
| `GEOVISIO_API_TOKEN` | - | GeoVisio 內部 JWT token |

### 日期過濾

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `SPECIFIED_DATES` | (空) | 指定要處理的日期，逗號分隔 (最高優先) |
| `CUTOFF_DATE` | 2025-06-01 | 截止日期，跳過早於此日期的資料 |

優先順序：`SPECIFIED_DATES` > `CUTOFF_DATE` > 處理所有日期

### 效能參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `MAX_CONCURRENT_UPLOADS` | 5 | 最大並發上傳數 |
| `UPLOAD_TIMEOUT` | 60 | 單張圖片上傳超時 (秒) |
| `SEQUENCE_DELAY` | 3 | 序列間延遲 (秒) |
| `BATCH_DELAY` | 300 | 日期組間延遲 (秒) |
| `MAX_POOL_SIZE` | 10 | HTTP 連線池大小 |

### 連線與重試

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `DNS_CACHE_TTL` | 300 | DNS 快取時間 (秒) |
| `CONNECT_TIMEOUT` | 10 | 連線建立超時 (秒) |
| `READ_TIMEOUT` | 60 | 讀取回應超時 (秒) |
| `RETRY_ATTEMPTS` | 5 | 最大重試次數 |

### 批次處理

根據序列大小自動選擇策略：

| 分類 | 張數 | 批次大小 | 批次延遲 | 並發數 |
|------|------|----------|----------|--------|
| 小型 | < 500 | 50 | 5s | 3 |
| 中型 | 500-2000 | 30 | 10s | 2 |
| 大型 | > 2000 | 20 | 15s | 1 |

### 資源監控

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
| `VEHICLE_TYPE` | CAR | 車輛類型 (CAR / MOTORCYCLE) |

### Docker 監控

監控主機自動採用 `TMS_GEOVISIO_URL` 的主機位址（假設 GeoVisio API 與 Docker 監控主機同一台），不需要另外設定 `DOCKER_TARGET_IP`。

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `DOCKER_CONTAINER_NAME` | geovisio_dev-api-1 | 目標容器名稱 |
| `MONITOR_INTERVAL` | 300 | 監控回報頻率 (秒) |
| `MONITOR_MEM_THRESHOLD` | 3072 | 記憶體告警門檻 (MB) |
| `DISCORD_BOT_TOKEN` | - | Discord 通知 Bot Token |
| `DISCORD_CHANNEL_ID` | - | Discord 通知頻道 ID |

---

## 模組說明

### API 層 (`src/api/`)

**GeoVisioAPIClient** — API 請求與認證封裝

- 使用靜態 GeoVisio JWT token 認證（Bearer token）
- 401 回應時自動重試
- 統一的請求/回應處理
- 主要方法：`create_collection()`、`get_all_collections()`、`get_collection_items()`、`get_uploaded_keynames()`、`find_collection_by_sequence()`

**ImageUploader** — 影像上傳管理

- 流式上傳（不預載入記憶體）
- 指數退避重試（tenacity）
- 去重檢查整合
- 批次處理與並發控制

### 設定層 (`src/config/`)

**Settings** — 集中管理所有環境變數

- 所有模組統一從此處讀取設定
- `get_auth_config()` 回傳認證配置（靜態 token）
- `get_batch_config()` 根據序列大小回傳批次策略
- `validate()` 驗證必要設定

### 核心功能 (`src/core/`)

**GPSDataPreprocessor** — GPS 資料前處理

- 從 KeyName 解析 GPS 時間戳
- 計算相鄰影像的時間差和距離差
- 根據閾值自動分割序列（CAR: 500s/200m, MOTORCYCLE: 300s/20m）
- 支援 TWD97 ↔ WGS84 座標轉換

**FailureTracker** — 失敗追蹤與報告

### 效能優化 (`src/optimization/`)

**DuplicateChecker** — 雙重去重檢查

- KeyName 快速檢查 + MD5 精確檢查
- LRU 快取機制
- 支援本地檔案和 URL 來源

**ResourceMonitor** — 基於 Job Queue 的動態調速

- 動態調整 batch size 和延遲
- Job Queue 積壓過多時自動減速
- 等待資源恢復機制

### 流程管理 (`src/pipeline/`)

**GeoVisioUploadPipeline** — 主流程控制器

- 模組初始化與資源管理（aiohttp Session 生命週期）
- CSV 前處理與日期分組
- 續傳邏輯判斷
- 統一的錯誤處理與清理

---

## 工具程式

### check_duplicates.py

```bash
# 完整檢查並產生報告
python -m src.tools.check_duplicates

# 查詢特定檔名
python -m src.tools.check_duplicates -f "20250829113426796_S9GLCPJ76.jpg"

# 指定輸出目錄
python -m src.tools.check_duplicates -o ./reports
```

輸出報告位於 `output/duplicate_reports/`：
- `{timestamp}_keyname_duplicates.csv`
- `{timestamp}_md5_duplicates.csv`
- `{timestamp}_keyname_md5_mismatch.csv`

### delete_all_duplicates.py

```bash
# 預覽模式
python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv --dry-run

# 執行刪除 (需輸入 YES 確認)
python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv
```

---

## 上傳流程

### 整體流程

```
main.py
  │
  ├── 驗證環境變數 (Settings.validate)
  ├── 啟動背景 Docker 監控 (HawserDockerMonitor)
  │
  └── GeoVisioUploadPipeline.run()
        │
        ├── 初始化 aiohttp Session & API Client (含 JWT token)
        ├── CSV 編碼轉換 & GPS 資料前處理 & 序列分割
        ├── 按日期分組
        │
        ├── 日期迴圈 ─────────────────────────────────────┐
        │   ├── 日期過濾 (SPECIFIED_DATES / CUTOFF_DATE)   │
        │   ├── 按 group_id 分組序列                       │
        │   │                                              │
        │   └── 序列迴圈 ─────────────────────────┐        │
        │       ├── 去重檢查 (KeyName / MD5)       │        │
        │       ├── 搜尋既有 Collection (續傳)     │        │
        │       ├── 建立或使用既有 Collection       │        │
        │       ├── 批次上傳影像 (並發控制)         │        │
        │       └── 資源監控 & 動態調速            │        │
        │       ───────────────────────────────────┘        │
        ────────────────────────────────────────────────────┘
        │
        ├── 產生處理報告 (logs/)
        └── 清理資源 (關閉 Session)
```

### 續傳邏輯

```
開始處理序列
    │
    ▼
檢查第一張 KeyName 是否存在（本地資料庫）
    │
    ├── 不存在 → 建立新 Collection → 上傳全部
    │
    └── 存在 → 搜尋既有 Collection（API）
                  │
                  ├── 找到 → 比對已上傳數量
                  │            │
                  │            ├── 已完成 → 跳過
                  │            └── 未完成 → 續傳（只上傳剩餘部分）
                  │
                  └── 未找到 → 建立新 Collection → 上傳全部
```

---

## GeoVisio 伺服器端部署備註

### 網路架構

```
192.168.61.2 (上傳腳本)
    │
    ├── HTTP → 192.168.61.1:5001  (GeoVisio API, Gunicorn)
    └── TCP  → 192.168.61.3:5432  (PostgreSQL, 去重查詢)

192.168.61.1 (Docker Host)
    ├── geovisio_dev-api-1          (GeoVisio API)
    ├── geovisio_dev-db-pg-geovisio-1  (PostgreSQL)
    ├── geovisio_dev-auth-1         (Keycloak, 僅瀏覽器登入用)
    └── geovisio_dev-background-worker-1 (背景處理)
```

### Token 管理速查

```bash
# 查看帳號
docker exec geovisio_dev-db-pg-geovisio-1 psql -U gvs -d geovisio \
  -c "SELECT id, name, role FROM accounts;"

# 查看 tokens
docker exec geovisio_dev-db-pg-geovisio-1 psql -U gvs -d geovisio \
  -c "SELECT t.id, t.description, t.account_id FROM tokens t;"

# 建立新 token
docker exec geovisio_dev-db-pg-geovisio-1 psql -U gvs -d geovisio \
  -c "INSERT INTO tokens (account_id, description) VALUES ('<ACCOUNT_ID>', 'description') RETURNING id;"

# 產生 JWT
docker exec geovisio_dev-api-1 bash -c "python -c \"from geovisio import create_app; app = create_app(); ctx = app.app_context(); ctx.push(); from geovisio.web.tokens import _generate_jwt_token; print(_generate_jwt_token('<TOKEN_ID>'))\""

# 撤銷 token
docker exec geovisio_dev-db-pg-geovisio-1 psql -U gvs -d geovisio \
  -c "DELETE FROM tokens WHERE id = '<TOKEN_ID>';"
```

---

## 常見問題

### Q: Token 失效怎麼辦？

重新產生一個。參考 [產生 Token](#產生-token) 章節，用 psql 建立新 token 記錄，再用 `_generate_jwt_token()` 產生 JWT，更新 `.env` 中的 `GEOVISIO_API_TOKEN`。

### Q: 為什麼不用 Keycloak OAuth token？

GeoVisio API 的 Bearer token 驗證只支援自己產生的 HS256 JWT token。Keycloak 發的是 RS256 token，API 嘗試用 `FLASK_SECRET_KEY` 解碼時會報 `PEM MalformedFraming` 錯誤。Keycloak 僅用於瀏覽器 OAuth 登入流程。

### Q: 如何處理上傳中斷？

程式支援自動續傳。重新執行時會：
1. 檢查本地資料庫中已存在的 KeyName
2. 透過 API 搜尋對應的 Collection
3. 比對已上傳數量，只上傳未完成的部分

### Q: 如何只上傳特定日期？

在 `.env` 中設定：
```bash
SPECIFIED_DATES=2025-08-29,2025-08-30,2025-09-01
```

### Q: 如何調整上傳速度？

調整以下參數：
- 增加 `MAX_CONCURRENT_UPLOADS`（建議 5-20）
- 減少 `SEQUENCE_DELAY` 和 `BATCH_DELAY`
- 增加 `BATCH_SIZE_*` 參數

速度模式參考：

| 模式 | 並發數 | 日期延遲 | 序列延遲 |
|------|--------|----------|----------|
| 保守 | 3 | 300s | 5s |
| 一般 | 10 | 60s | 2s |
| 高速 | 20 | 30s | 1s |

### Q: 去重檢查失敗怎麼辦？

設定 `DEDUP_FAILURE_BEHAVIOR`：
- `continue`（預設）— 繼續上傳
- `skip` — 跳過該影像

### Q: 輸出的報告在哪裡？

| 報告 | 路徑 |
|------|------|
| 處理結果 | `logs/{timestamp}_processing_results.csv` |
| 失敗報告 | `logs/{timestamp}_upload_failures.csv` |
| 重複檢查 | `output/duplicate_reports/` |

---

## 授權

內部使用

## 維護者

TMS 開發團隊
