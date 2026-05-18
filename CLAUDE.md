# CLAUDE.md

此檔案提供 Claude Code (claude.ai/code) 在此專案中工作時的指引。

## 專案概要

GeoVisio 批次影像上傳系統 — 將大量街景照片（含 GPS 資料）自動化上傳至 GeoVisio (Panoramax) 平台。支援斷點續傳、去重、資源監控。

## 常用指令

### 執行主程式
```bash
python -m src.main
```

### 工具程式
```bash
# 重複影像檢查（產生報告至 output/duplicate_reports/）
python -m src.tools.check_duplicates
python -m src.tools.check_duplicates -f "20250829113426796_S9GLCPJ76.jpg"

# 刪除重複影像（--dry-run 為預覽模式）
python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv --dry-run
python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv
```

### 安裝相依套件
```bash
pip install -r requirements.txt
```

### 除錯與驗證
```bash
python -m src.config.settings   # 印出所有目前設定值並驗證
python src/test_api.py          # 測試 API 連線
```

## 系統架構

### 模組結構

```
src/
├── main.py                  # 程式入口：啟動 Docker 監控 + UploadPipeline
├── api/
│   ├── geovisio_api_client.py  # GeoVisio REST API 封裝（認證、collection、keyname 查詢）
│   ├── image_uploader.py       # 串流上傳器，含指數退避重試（tenacity）
│   └── exceptions.py           # 自定義例外：ImageAlreadyExistsError、RetryableUploadError
├── config/
│   ├── settings.py             # 所有環境變數統一由 Settings class 管理
│   └── logging_config.py       # 日誌設定
├── core/
│   ├── csv_encoding_converter.py   # 自動偵測並轉換 CSV 編碼（chardet）
│   ├── image_data_preprocessor.py  # 解析 KeyName→GPS 時間、計算時間/距離差、分割序列
│   └── failure_checker.py          # 失敗追蹤與報告
├── optimization/
│   ├── duplicate_checker.py        # LRU 快取 KeyName + MD5 去重（查 PostgreSQL）
│   ├── resource_monitor.py         # 輪詢 Job Queue，積壓過多時自動節流
│   └── sequence_batch_handler.py   # 依序列大小選擇批次策略並分批處理
├── pipeline/
│   └── upload_pipeline.py      # 主流程控制：Session 生命週期、CSV→日期→序列迴圈
├── tools/
│   ├── check_duplicates.py     # 獨立執行的重複影像報告產生器
│   └── delete_all_duplicates.py # 獨立執行的重複影像刪除工具
└── utils/
    └── docker_monitor.py       # 背景任務：透過 Hawser 監控 GeoVisio 容器，Discord 告警
```

### 資料流

1. `main.py` 執行 `Settings.validate()` 驗證設定，以非同步背景任務啟動 `HawserDockerMonitor`，再呼叫 `GeoVisioUploadPipeline.run()`。
2. Pipeline 建立唯一的共用 `aiohttp.ClientSession`，注入 `GeoVisioAPIClient` 和 `ImageUploader`。
3. 透過 `Settings.get_csv_files()` 取得 CSV 檔案清單（資料夾掃描或單一檔案）。
4. `GPSDataPreprocessor` 自動處理 CSV 編碼，解析 KeyName 時間戳（格式：`YYYYMMDDHHMMSSMMM_XXXXXXXXX`），計算相鄰影像的時間差與距離差，依 `VEHICLE_TYPE` 閾值分割序列（CAR: 500秒/200公尺；MOTORCYCLE: 300秒/20公尺）。
5. 序列依日期分組後依序處理，`SPECIFIED_DATES` / `CUTOFF_DATE` 篩選要處理的日期。
6. 每個序列：去重檢查（KeyName → MD5 via `DuplicateChecker`）→ 搜尋既有 Collection（續傳判斷）→ 建立或重用 Collection → 分批並發上傳剩餘影像。
7. `ResourceMonitor` 持續輪詢 GeoVisio Job Queue，積壓超過 `JOB_QUEUE_WARNING_THRESHOLD` 時自動降速。

### Settings 使用規範

[src/config/settings.py](src/config/settings.py) 的 `Settings` 為 class 層級屬性（非實例）。所有環境變數在 module 載入時一次性由 `os.getenv()` 讀取。其他模組一律引用 `Settings.屬性名稱`，**不得自行呼叫 `os.getenv()`**。

### 認證機制

GeoVisio 使用**內部 HS256 JWT token**（非 Keycloak OAuth）。Token 需在 GeoVisio API Docker 容器內執行 `_generate_jwt_token()` 產生，存入 `.env` 的 `GEOVISIO_API_TOKEN`。設定 `ENABLE_AUTH=true` 即可啟用。詳細的三步驟產生流程請參考 README.md。

### 續傳與去重邏輯

序列開始處理時，先檢查第一張影像的 KeyName 是否已存在於 PostgreSQL。若存在，透過 API 查詢對應的 Collection，比對已上傳數量與預期數量，僅上傳尚未完成的部分。

## 設定

將 `.env.example` 複製為 `.env`，必填環境變數：
- `TMS_GEOVISIO_URL` — GeoVisio API 位址（如 `http://192.168.61.1:5001`）
- `CSV_FOLDER_PATH` 或 `CSV_FILE_PATH` — 輸入資料來源（二擇一）
- `IMAGE_BASE_PATH` — 影像檔案根目錄
- `DATABASE_URL` — PostgreSQL 連線字串（去重用）

速度預設組合（保守 / 標準 / 高速）請參考 `.env.example`。

## 輸出報告

- `logs/{timestamp}_processing_results.csv` — 各序列處理結果
- `logs/{timestamp}_upload_failures.csv` — 上傳失敗的影像清單
- `output/duplicate_reports/` — check_duplicates 工具產生的報告

## Python 版本

需要 Python 3.10 以上（使用 `.venv`）。

---

## 目前開發狀態

- **已完成**：批次上傳、斷點續傳、去重（KeyName + MD5）、資源監控（Job Queue 節流）、多 CSV 匯入、Docker 容器監控、設定分層（`.env` 僅保留環境特定值，可調校參數移至 `config.toml`）
- **進行中**：<!-- 填入目前在做什麼 -->
- **已知問題**：<!-- 填入目前有哪些 bug 或待解決問題 -->

## 環境資訊

| 項目 | 說明 |
|------|------|
| GeoVisio API | `http://192.168.61.1:5001` |
| PostgreSQL | `192.168.61.3:5432` / db: `geovisio` / user: `gvs` |
| Docker Host | `192.168.61.1`（含 api-1、db-pg-geovisio-1、background-worker-1） |
| 上傳腳本機器 | `192.168.61.2` |
| venv 位置 | `D:\MyProject\GeovisioUpdate\.venv` |
| Python | 3.10 |

## 開發規範

- **不直接 push main branch**
- **所有設定集中在 `Settings` class**（[src/config/settings.py](src/config/settings.py)），其他模組一律用 `Settings.ATTR_NAME`，不直接呼叫 `os.getenv()`
- **非同步全程用 `async/await + aiohttp`**；`aiohttp.ClientSession` 由 `GeoVisioUploadPipeline` 統一建立並注入子模組，不在子模組內自行建立
- **重試機制用 `tenacity`**（指數退避），不手寫 sleep-retry 迴圈
- **新增設定參數**：判斷類型後依對應流程操作
  - 環境特定值（URL、路徑、Token、密碼）：加到 `Settings` class（`os.getenv()`）→ 加到 `.env.example`
  - 可調校預設值（速度、批次、重試等）：加到 `config.toml` → 加到 `Settings` class（`_env_int/bool/str()`，支援 env var 覆蓋）

## 常見問題與解法

| 問題 | 解法 |
|------|------|
| JWT Token 過期或 401 | 重新執行 README.md「產生 Token」的 3 步驟流程，更新 `.env` 的 `GEOVISIO_API_TOKEN` |
| Job Queue 積壓過多、上傳變慢 | `ResourceMonitor` 會自動節流，等待 Queue 降至 `JOB_QUEUE_SAFE_THRESHOLD` 以下即恢復 |
| CSV 編碼錯誤 | `csv_encoding_converter.py` 用 chardet 自動偵測並轉換，通常不需手動介入 |
| 上傳中斷後重複跑 | 程式會自動續傳，不需清除狀態；若要強制重傳可清除 PostgreSQL 中對應的 KeyName 記錄 |
| `Settings.validate()` 失敗 | 確認 `.env` 中 `TMS_GEOVISIO_URL`、`CSV_FOLDER_PATH`/`CSV_FILE_PATH`、`IMAGE_BASE_PATH` 均已設定 |

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **GeovisioUpdate** (1002 symbols, 1635 relationships, 53 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/GeovisioUpdate/context` | Codebase overview, check index freshness |
| `gitnexus://repo/GeovisioUpdate/clusters` | All functional areas |
| `gitnexus://repo/GeovisioUpdate/processes` | All execution flows |
| `gitnexus://repo/GeovisioUpdate/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
