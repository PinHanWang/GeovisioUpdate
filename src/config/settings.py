"""
全域設定模組

優先順序：.env 環境變數 > config.toml > 程式碼內建預設值
- 環境特定值（URL、路徑、Token）：只在 .env 設定
- 可調校參數（速度、批次、重試）：預設值在 config.toml，需要時可在 .env 覆蓋
"""

import os
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


# ============================================================
# TOML 設定載入
# ============================================================
_CONFIG_FILE = Path(__file__).parent.parent.parent / "config.toml"


def _load_toml() -> dict:
    if not _CONFIG_FILE.exists():
        return {}
    if sys.version_info >= (3, 11):
        import tomllib
        with open(_CONFIG_FILE, "rb") as f:
            return tomllib.load(f)
    try:
        import tomli
        with open(_CONFIG_FILE, "rb") as f:
            return tomli.load(f)
    except ImportError:
        print("警告: 找不到 tomli 套件，請執行 pip install tomli")
        return {}


_cfg = _load_toml()


def _cfg_get(path: str):
    """以點分隔路徑取得 TOML 設定值，例如 'upload.max_concurrent'"""
    val = _cfg
    for part in path.split("."):
        if isinstance(val, dict) and part in val:
            val = val[part]
        else:
            return None
    return val


def _env_int(env_key: str, cfg_path: str, default: int) -> int:
    v = os.getenv(env_key)
    if v is not None:
        return int(v)
    c = _cfg_get(cfg_path)
    return int(c) if c is not None else default


def _env_bool(env_key: str, cfg_path: str, default: bool) -> bool:
    v = os.getenv(env_key)
    if v is not None:
        return v.lower() == "true"
    c = _cfg_get(cfg_path)
    return bool(c) if c is not None else default


def _env_str(env_key: str, cfg_path: str, default: str) -> str:
    v = os.getenv(env_key)
    if v is not None:
        return v
    c = _cfg_get(cfg_path)
    return str(c) if c is not None else default


# ============================================================
class Settings:
    """應用程式設定 — 集中管理所有設定值"""

    # ========================================
    # GeoVisio API 設定（必填，.env 設定）
    # ========================================
    TMS_GEOVISIO_URL: str = os.getenv("TMS_GEOVISIO_URL", "")

    # ========================================
    # 認證設定（.env 設定）
    # ========================================
    ENABLE_AUTH: bool = os.getenv("ENABLE_AUTH", "false").lower() == "true"
    GEOVISIO_API_TOKEN: str = os.getenv("GEOVISIO_API_TOKEN", "")

    # ========================================
    # 檔案路徑設定（必填，.env 設定）
    # ========================================
    CSV_FOLDER_PATH: Optional[str] = os.getenv("CSV_FOLDER_PATH")
    CSV_FILE_PATH: Optional[str] = os.getenv("CSV_FILE_PATH")
    IMAGE_BASE_PATH: Optional[str] = os.getenv("IMAGE_BASE_PATH")

    # ========================================
    # 資料庫設定（必填，.env 設定）
    # ========================================
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")

    # ========================================
    # 專案與資料預處理設定（.env 設定）
    # ========================================
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "DefaultProject")
    VEHICLE_TYPE: str = os.getenv("VEHICLE_TYPE", "CAR")

    # ========================================
    # 日期過濾設定（.env 設定，每次執行可能不同）
    # ========================================
    SPECIFIED_DATES: Optional[str] = os.getenv("SPECIFIED_DATES", "")
    CUTOFF_DATE: Optional[str] = os.getenv("CUTOFF_DATE", "")

    # ========================================
    # Discord 通知（選用，.env 設定）
    # ========================================
    DISCORD_BOT_TOKEN: Optional[str] = os.getenv("DISCORD_BOT_TOKEN")
    DISCORD_CHANNEL_ID: Optional[str] = os.getenv("DISCORD_CHANNEL_ID")

    # ========================================
    # Docker 監控 — 環境特定值（.env 設定）
    # ========================================
    DOCKER_TARGET_IP: str = os.getenv("DOCKER_TARGET_IP", "192.168.61.3")

    # ========================================
    # 上傳核心參數（config.toml，可用 .env 覆蓋）
    # ========================================
    MAX_CONCURRENT_UPLOADS: int = _env_int("MAX_CONCURRENT_UPLOADS", "upload.max_concurrent", 10)
    UPLOAD_TIMEOUT: int        = _env_int("UPLOAD_TIMEOUT",          "upload.timeout",        60)
    SEQUENCE_DELAY: int        = _env_int("SEQUENCE_DELAY",          "upload.sequence_delay", 2)
    BATCH_DELAY: int           = _env_int("BATCH_DELAY",             "upload.batch_delay",    120)

    # ========================================
    # 連線設定（config.toml，可用 .env 覆蓋）
    # ========================================
    MAX_POOL_SIZE: int      = _env_int("MAX_POOL_SIZE",      "connection.max_pool_size",    20)
    DNS_CACHE_TTL: int      = _env_int("DNS_CACHE_TTL",      "connection.dns_cache_ttl",    300)
    CONNECT_TIMEOUT: int    = _env_int("CONNECT_TIMEOUT",    "connection.connect_timeout",  10)
    READ_TIMEOUT: int       = _env_int("READ_TIMEOUT",       "connection.read_timeout",     60)
    KEEPALIVE_TIMEOUT: int  = _env_int("KEEPALIVE_TIMEOUT",  "connection.keepalive_timeout", 30)

    # ========================================
    # 重試設定（config.toml，可用 .env 覆蓋）
    # ========================================
    RETRY_ATTEMPTS: int  = _env_int("RETRY_ATTEMPTS",  "retry.attempts",  3)
    RETRY_MIN_WAIT: int  = _env_int("RETRY_MIN_WAIT",  "retry.min_wait",  1)
    RETRY_MAX_WAIT: int  = _env_int("RETRY_MAX_WAIT",  "retry.max_wait",  30)
    RETRY_DELAY: int     = _env_int("RETRY_DELAY",     "retry.delay",     2)

    # ========================================
    # 批次處理策略（config.toml，可用 .env 覆蓋）
    # ========================================
    SEQUENCE_SMALL_THRESHOLD: int  = _env_int("SEQUENCE_SMALL_THRESHOLD",  "batch.small_threshold",  500)
    SEQUENCE_MEDIUM_THRESHOLD: int = _env_int("SEQUENCE_MEDIUM_THRESHOLD", "batch.medium_threshold", 2000)

    BATCH_SIZE_SMALL: int    = _env_int("BATCH_SIZE_SMALL",    "batch.small.size",       100)
    BATCH_DELAY_SMALL: int   = _env_int("BATCH_DELAY_SMALL",   "batch.small.delay",      5)
    CONCURRENT_SMALL: int    = _env_int("CONCURRENT_SMALL",    "batch.small.concurrent", 5)

    BATCH_SIZE_MEDIUM: int   = _env_int("BATCH_SIZE_MEDIUM",   "batch.medium.size",       50)
    BATCH_DELAY_MEDIUM: int  = _env_int("BATCH_DELAY_MEDIUM",  "batch.medium.delay",      10)
    CONCURRENT_MEDIUM: int   = _env_int("CONCURRENT_MEDIUM",   "batch.medium.concurrent", 3)

    BATCH_SIZE_LARGE: int    = _env_int("BATCH_SIZE_LARGE",    "batch.large.size",       30)
    BATCH_DELAY_LARGE: int   = _env_int("BATCH_DELAY_LARGE",   "batch.large.delay",      15)
    CONCURRENT_LARGE: int    = _env_int("CONCURRENT_LARGE",    "batch.large.concurrent", 2)

    # ========================================
    # 資源監控閾值（config.toml，可用 .env 覆蓋）
    # ========================================
    JOB_QUEUE_SAFE_THRESHOLD: int    = _env_int("JOB_QUEUE_SAFE_THRESHOLD",    "monitor.job_queue_safe_threshold",    200)
    JOB_QUEUE_WARNING_THRESHOLD: int = _env_int("JOB_QUEUE_WARNING_THRESHOLD", "monitor.job_queue_warning_threshold", 1000)
    RESOURCE_CHECK_INTERVAL: int     = _env_int("RESOURCE_CHECK_INTERVAL",     "monitor.resource_check_interval",     60)
    RESOURCE_QUEUE_CACHE_TTL: int    = _env_int("RESOURCE_QUEUE_CACHE_TTL",    "monitor.resource_query_cache_ttl",    5)

    # ========================================
    # 去重檢查設定（config.toml，可用 .env 覆蓋）
    # ========================================
    DEDUP_MAX_CACHE_SIZE: int  = _env_int("DEDUP_MAX_CACHE_SIZE",  "dedup.max_cache_size",  100000)
    DEDUP_PRELOAD_LIMIT: int   = _env_int("DEDUP_PRELOAD_LIMIT",   "dedup.preload_limit",   50000)
    DEDUP_FAILURE_BEHAVIOR: str = _env_str("DEDUP_FAILURE_BEHAVIOR", "dedup.failure_behavior", "continue")

    # ========================================
    # 功能開關（config.toml，可用 .env 覆蓋）
    # ========================================
    ENABLE_DEDUPLICATION: bool    = _env_bool("ENABLE_DEDUPLICATION",    "features.enable_deduplication",    True)
    ENABLE_MD5_CHECK: bool        = _env_bool("ENABLE_MD5_CHECK",        "features.enable_md5_check",        True)
    ENABLE_RESOURCE_MONITOR: bool = _env_bool("ENABLE_RESOURCE_MONITOR", "features.enable_resource_monitor", True)

    # ========================================
    # Docker 容器監控 — 調校值（config.toml，可用 .env 覆蓋）
    # ========================================
    DOCKER_CONTAINER_NAME: str       = _env_str("DOCKER_CONTAINER_NAME",       "docker.container_name",         "geovisio_service")
    HAWSER_PORT: int                 = _env_int("HAWSER_PORT",                 "docker.hawser_port",            2376)
    MONITOR_INTERVAL: int            = _env_int("MONITOR_INTERVAL",            "docker.monitor_interval",       300)
    MONITOR_MEM_THRESHOLD_MB: int    = _env_int("MONITOR_MEM_THRESHOLD_MB",    "docker.monitor_mem_threshold_mb", 3072)

    # ============================================================

    @classmethod
    def get_specified_dates(cls) -> list:
        """解析 SPECIFIED_DATES 為 datetime.date 列表"""
        import datetime

        if not cls.SPECIFIED_DATES:
            return []

        dates = []
        for date_str in cls.SPECIFIED_DATES.split(","):
            date_str = date_str.strip()
            if date_str:
                try:
                    dates.append(datetime.datetime.strptime(date_str, "%Y-%m-%d").date())
                except ValueError:
                    print(f"警告: 日期格式錯誤: {date_str}")

        return sorted(set(dates))

    @classmethod
    def get_csv_files(cls) -> list:
        """
        取得要處理的 CSV 檔案列表

        優先順序:
        1. CSV_FOLDER_PATH — 掃描資料夾內所有 .csv 檔案
        2. CSV_FILE_PATH   — 單一檔案（向下相容）
        """
        if cls.CSV_FOLDER_PATH:
            folder = Path(cls.CSV_FOLDER_PATH)
            if not folder.exists():
                print(f"錯誤: CSV 資料夾不存在: {folder}")
                return []
            csv_files = sorted(folder.glob("*.csv"))
            if not csv_files:
                print(f"警告: CSV 資料夾內無 .csv 檔案: {folder}")
            return csv_files

        if cls.CSV_FILE_PATH:
            p = Path(cls.CSV_FILE_PATH)
            if p.exists():
                return [p]
            print(f"錯誤: CSV 檔案不存在: {p}")
            return []

        return []

    @classmethod
    def get_auth_config(cls) -> Optional[dict]:
        if not cls.ENABLE_AUTH:
            return None

        if not cls.GEOVISIO_API_TOKEN:
            print("警告: ENABLE_AUTH=true 但 GEOVISIO_API_TOKEN 未設定")
            return None

        return {"static_token": cls.GEOVISIO_API_TOKEN}

    @classmethod
    def validate(cls) -> bool:
        """驗證必要設定"""
        errors = []

        if not cls.TMS_GEOVISIO_URL:
            errors.append("TMS_GEOVISIO_URL 未設定")

        if not cls.CSV_FOLDER_PATH and not cls.CSV_FILE_PATH:
            errors.append("CSV_FOLDER_PATH 或 CSV_FILE_PATH 至少需設定一個")

        if not cls.IMAGE_BASE_PATH:
            errors.append("IMAGE_BASE_PATH 未設定")

        if cls.ENABLE_AUTH and not cls.GEOVISIO_API_TOKEN:
            errors.append("ENABLE_AUTH=true 但 GEOVISIO_API_TOKEN 未設定")

        if errors:
            for error in errors:
                print(f"設定錯誤: {error}")
            return False

        return True

    @classmethod
    def get_batch_config(cls, size: int) -> dict:
        """根據序列大小取得批次配置"""
        if size < cls.SEQUENCE_SMALL_THRESHOLD:
            return {
                "batch_size": cls.BATCH_SIZE_SMALL,
                "batch_delay": cls.BATCH_DELAY_SMALL,
                "max_concurrent": cls.CONCURRENT_SMALL,
                "description": f"小型序列 (< {cls.SEQUENCE_SMALL_THRESHOLD} 張)",
            }
        elif size < cls.SEQUENCE_MEDIUM_THRESHOLD:
            return {
                "batch_size": cls.BATCH_SIZE_MEDIUM,
                "batch_delay": cls.BATCH_DELAY_MEDIUM,
                "max_concurrent": cls.CONCURRENT_MEDIUM,
                "description": f"中型序列 ({cls.SEQUENCE_SMALL_THRESHOLD}–{cls.SEQUENCE_MEDIUM_THRESHOLD} 張)",
            }
        else:
            return {
                "batch_size": cls.BATCH_SIZE_LARGE,
                "batch_delay": cls.BATCH_DELAY_LARGE,
                "max_concurrent": cls.CONCURRENT_LARGE,
                "description": f"大型序列 (> {cls.SEQUENCE_MEDIUM_THRESHOLD} 張)",
            }

    @classmethod
    def print_config(cls):
        """列印目前的設定值（用於除錯）"""
        cfg_source = "✓" if _CONFIG_FILE.exists() else "✗ (未找到 config.toml，使用內建預設值)"
        print("=" * 80)
        print("GeoVisio 上傳系統設定")
        print(f"config.toml: {cfg_source}")
        print("=" * 80)
        print(f"{'API URL':<35}: {cls.TMS_GEOVISIO_URL}")
        if cls.CSV_FOLDER_PATH:
            print(f"{'CSV 資料夾':<35}: {cls.CSV_FOLDER_PATH}")
        if cls.CSV_FILE_PATH:
            print(f"{'CSV 檔案 (單檔)':<35}: {cls.CSV_FILE_PATH}")
        print(f"{'影像路徑':<35}: {cls.IMAGE_BASE_PATH}")
        print(f"{'車輛類型':<35}: {cls.VEHICLE_TYPE}")
        print("-" * 80)
        print(f"{'最大並發上傳數':<35}: {cls.MAX_CONCURRENT_UPLOADS}")
        print(f"{'上傳超時 (秒)':<35}: {cls.UPLOAD_TIMEOUT}")
        print(f"{'序列間延遲 (秒)':<35}: {cls.SEQUENCE_DELAY}")
        print(f"{'日期間延遲 (秒)':<35}: {cls.BATCH_DELAY}")
        print(f"{'連線池大小':<35}: {cls.MAX_POOL_SIZE}")
        print("-" * 80)
        print(f"{'重試次數':<35}: {cls.RETRY_ATTEMPTS}")
        print(f"{'重試間隔 (秒)':<35}: {cls.RETRY_DELAY}")
        print(f"{'去重失敗行為':<35}: {cls.DEDUP_FAILURE_BEHAVIOR}")
        print("-" * 80)
        print(f"{'小型序列批次':<35}: {cls.BATCH_SIZE_SMALL} 張/批，並發 {cls.CONCURRENT_SMALL}")
        print(f"{'中型序列批次':<35}: {cls.BATCH_SIZE_MEDIUM} 張/批，並發 {cls.CONCURRENT_MEDIUM}")
        print(f"{'大型序列批次':<35}: {cls.BATCH_SIZE_LARGE} 張/批，並發 {cls.CONCURRENT_LARGE}")
        print("-" * 80)
        print(f"{'Job Queue 安全閾值':<35}: {cls.JOB_QUEUE_SAFE_THRESHOLD}")
        print(f"{'Job Queue 警告閾值':<35}: {cls.JOB_QUEUE_WARNING_THRESHOLD}")
        print("-" * 80)
        print(f"{'啟用去重檢查':<35}: {cls.ENABLE_DEDUPLICATION}")
        print(f"{'啟用 MD5 檢查':<35}: {cls.ENABLE_MD5_CHECK}")
        print(f"{'啟用資源監控':<35}: {cls.ENABLE_RESOURCE_MONITOR}")
        print("-" * 80)
        print(f"{'啟用 API 認證':<35}: {cls.ENABLE_AUTH}")
        if cls.ENABLE_AUTH:
            token_display = cls.GEOVISIO_API_TOKEN[:20] + "..." if cls.GEOVISIO_API_TOKEN else "(未設定)"
            print(f"{'GeoVisio API Token':<35}: {token_display}")
        specified_dates = cls.get_specified_dates()
        if specified_dates:
            dates_str = ", ".join(str(d) for d in specified_dates)
            print(f"{'指定日期':<35}: {dates_str} ({len(specified_dates)} 天)")
        else:
            print(f"{'指定日期':<35}: (未設定)")
        print(f"{'截止日期':<35}: {cls.CUTOFF_DATE or '(未設定)'}")
        print("=" * 80)


# 全域設定實例（向後相容）
settings = Settings()


if __name__ == "__main__":
    Settings.print_config()
    print(f"\n設定驗證: {'通過' if Settings.validate() else '失敗'}")
