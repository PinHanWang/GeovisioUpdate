# src/config/

集中管理所有設定值與日誌設定。

## 檔案

### `settings.py` — `Settings`

全域設定，`Settings` 為 **class 層級屬性**（非實例），所有環境變數在 module 載入時一次性由 `os.getenv()` 讀取。

其他模組一律引用 `Settings.屬性名稱`，**不得自行呼叫 `os.getenv()`**。

- 優先順序：`.env` 環境變數 > `config.toml` > 程式碼內建預設值
- 環境特定值（URL、路徑、Token）：只在 `.env` 設定，用 `os.getenv("X", default)`
- 可調校參數（速度、批次、重試等）：預設值在 `config.toml`，用 `_env_int()`/`_env_bool()`/`_env_str()` 讀取（同時支援 `.env` 同名變數覆蓋）
- `BatchTier` dataclass + `Settings.BATCH_TIERS`：三個序列大小分級（小/中/大）的批次配置，取代早期 9 個扁平常數；`get_batch_config(size)` 回傳對應分級的 dict
- `DOCKER_TARGET_IP` 自動從 `TMS_GEOVISIO_URL` 解析 hostname，不是獨立環境變數
- `DEDUP_PRELOAD_LIMIT` 自動等於 `DEDUP_MAX_CACHE_SIZE // 2`，不是獨立環境變數
- `validate()` — 驗證必要設定是否齊全
- `print_config()` — 除錯用，印出目前所有設定值（`python -m src.config.settings`）

新增設定參數時的判斷流程：
1. 環境特定值（URL、路徑、Token、密碼）→ 加到 `Settings`（`os.getenv()`）→ 加到 `.env.example`
2. 可調校預設值（速度、批次、重試等）→ 加到 `config.toml` → 加到 `Settings`（`_env_int/bool/str()`）

### `logging_config.py`

`LOGGING_CONFIG`（`logging.config.dictConfig` 格式）+ `get_logger()` / `setup_logging()` 輔助函式。

`'loggers'` 區塊為特定模組設定 DEBUG 等級，**key 必須是完整模組路徑**（例如 `'src.optimization.duplicate_checker'`），因為 `logging.getLogger(__name__)` 取得的就是完整路徑，裸檔名不會匹配。
