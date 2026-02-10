"""
全域設定模組 (重構版)

集中管理所有環境變數和設定值
所有模組應該統一從這裡讀取設定，避免重複的 os.getenv() 調用
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """應用程式設定 - 集中管理所有環境變數"""
    
    # ========================================
    # GeoVisio API 設定
    # ========================================
    TMS_GEOVISIO_URL: str = os.getenv("TMS_GEOVISIO_URL", "")
    
    # ========================================
    # OAuth 認證設定
    # ========================================
    OAUTH_TOKEN_URL: str = os.getenv("OAUTH_TOKEN_URL", "")
    OAUTH_CLIENT_ID: str = os.getenv("OAUTH_CLIENT_ID", "geovisio")
    OAUTH_CLIENT_SECRET: str = os.getenv("OAUTH_CLIENT_SECRET", "")
    OAUTH_USERNAME: str = os.getenv("OAUTH_USERNAME", "")
    OAUTH_PASSWORD: str = os.getenv("OAUTH_PASSWORD", "")
    ENABLE_AUTH: bool = os.getenv("ENABLE_AUTH", "false").lower() == "true"

    # ========================================
    # 檔案路徑設定
    # ========================================
    CSV_FILE_PATH: Optional[str] = os.getenv("CSV_FILE_PATH")
    IMAGE_BASE_PATH: Optional[str] = os.getenv("IMAGE_BASE_PATH")
    
    # ========================================
    # 資料庫設定
    # ========================================
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    
    # ========================================
    # 上傳核心參數 (影響速度的關鍵參數)
    # ========================================
    # 最大並發上傳數 - 增加此值可提高上傳速度，但會增加 API 負載
    # 建議範圍: 5-20，API 使用 Gunicorn 後可設為 10-20
    MAX_CONCURRENT_UPLOADS: int = int(os.getenv("MAX_CONCURRENT_UPLOADS", "5"))
    UPLOAD_TIMEOUT: int = int(os.getenv("UPLOAD_TIMEOUT", "60")) # 單張圖片上傳超時時間 (秒)
    SEQUENCE_DELAY: int = int(os.getenv("SEQUENCE_DELAY", "3")) # 序列間延遲 (秒) - 減少此值可加快速度
    BATCH_DELAY: int = int(os.getenv("BATCH_DELAY", "300")) # 日期組間延遲 (秒) - 這是最大的時間消耗，可大幅降低
    
    # ========================================
    # 連線池設定
    # ========================================
    # aiohttp 連線池大小 - 應大於等於 MAX_CONCURRENT_UPLOADS
    MAX_POOL_SIZE: int = int(os.getenv("MAX_POOL_SIZE", "10"))

    # ========================================
    # 連線與超時設定 (新增) <-- 插入位置 1
    # ========================================
    DNS_CACHE_TTL: int = int(os.getenv("DNS_CACHE_TTL", "300"))
    CONNECT_TIMEOUT: int = int(os.getenv("CONNECT_TIMEOUT", "10"))
    READ_TIMEOUT: int = int(os.getenv("READ_TIMEOUT", "60"))
    KEEPALIVE_TIMEOUT: int = int(os.getenv("KEEPALIVE_TIMEOUT", "30"))
    
    # ========================================
    # 重試設定 (新增) <-- 插入位置 2
    # ========================================
    RETRY_ATTEMPTS: int = int(os.getenv("RETRY_ATTEMPTS", "5"))  # 從 3 改為 5
    RETRY_MIN_WAIT: int = int(os.getenv("RETRY_MIN_WAIT", "1"))  # 最小等待秒數
    RETRY_MAX_WAIT: int = int(os.getenv("RETRY_MAX_WAIT", "30"))  # 最大等待秒數
    RETRY_DELAY: int = int(os.getenv("RETRY_DELAY", "2"))

    # ========================================
    # 批次處理策略 (根據序列大小動態調整)
    # ========================================
    SEQUENCE_SMALL_THRESHOLD: int = int(os.getenv("SEQUENCE_SMALL_THRESHOLD", "500")) # 小型序列閾值 (< 此值為小型)
    SEQUENCE_MEDIUM_THRESHOLD: int = int(os.getenv("SEQUENCE_MEDIUM_THRESHOLD", "2000")) # 中型序列閾值 (< 此值為中型，>= 此值為大型)
    
    # 小型序列配置
    BATCH_SIZE_SMALL: int = int(os.getenv("BATCH_SIZE_SMALL", "50"))
    BATCH_DELAY_SMALL: int = int(os.getenv("BATCH_DELAY_SMALL", "10"))
    CONCURRENT_SMALL: int = int(os.getenv("CONCURRENT_SMALL", "3"))
    
    # 中型序列配置
    BATCH_SIZE_MEDIUM: int = int(os.getenv("BATCH_SIZE_MEDIUM", "30"))
    BATCH_DELAY_MEDIUM: int = int(os.getenv("BATCH_DELAY_MEDIUM", "15"))
    CONCURRENT_MEDIUM: int = int(os.getenv("CONCURRENT_MEDIUM", "2"))
    
    # 大型序列配置
    BATCH_SIZE_LARGE: int = int(os.getenv("BATCH_SIZE_LARGE", "20"))
    BATCH_DELAY_LARGE: int = int(os.getenv("BATCH_DELAY_LARGE", "20"))
    CONCURRENT_LARGE: int = int(os.getenv("CONCURRENT_LARGE", "1"))
    
    # ========================================
    # 資源監控閾值 (基於 Job Queue 積壓數量)
    # ========================================
    JOB_QUEUE_SAFE_THRESHOLD: int = int(os.getenv("JOB_QUEUE_SAFE_THRESHOLD", "100")) # 安全閾值 - Job Queue < 此值時全速運行
    JOB_QUEUE_WARNING_THRESHOLD: int = int(os.getenv("JOB_QUEUE_WARNING_THRESHOLD", "500")) # 警告閾值 - Job Queue >= 此值時減速
    RESOURCE_CHECK_INTERVAL: int = int(os.getenv("RESOURCE_CHECK_INTERVAL", "60")) # 資源檢查間隔 (秒)
    
    # ========================================
    # 去重檢查設定
    # ========================================
    DEDUP_MAX_CACHE_SIZE: int = int(os.getenv("DEDUP_MAX_CACHE_SIZE", "100000")) # 最大快取大小 (KeyName 和 MD5 各自的上限)
    DEDUP_PRELOAD_LIMIT: int = int(os.getenv("DEDUP_PRELOAD_LIMIT", "50000")) # 啟動時載入的快取數量
    
    # ========================================
    # 去重失敗行為 (新增) <-- 插入位置 3
    # ========================================
    # "continue" = 去重檢查失敗時繼續上傳
    # "skip" = 去重檢查失敗時跳過上傳（更保守）
    DEDUP_FAILURE_BEHAVIOR: str = os.getenv("DEDUP_FAILURE_BEHAVIOR", "continue")

    # ========================================
    # 功能開關
    # ========================================
    ENABLE_DEDUPLICATION: bool = os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true"
    ENABLE_MD5_CHECK: bool = os.getenv("ENABLE_MD5_CHECK", "true").lower() == "true"
    ENABLE_RESOURCE_MONITOR: bool = os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"
    
    # ========================================
    # 資料預處理設定
    # ========================================
    VEHICLE_TYPE: str = os.getenv("VEHICLE_TYPE", "CAR")
    
    # ========================================
    # 日期過濾設定
    # ========================================
    # 指定日期 - 只處理這些日期的資料 (最高優先)
    # 格式: 單一日期 "2025-08-29" 或多日期 "2025-08-29,2025-08-30,2025-09-01"
    # 設定此值後會忽略 CUTOFF_DATE
    SPECIFIED_DATES: Optional[str] = os.getenv("SPECIFIED_DATES", "")
    
    # 截止日期 - 跳過早於此日期的資料 (格式: YYYY-MM-DD)
    # 只有在 SPECIFIED_DATES 未設定時才生效
    CUTOFF_DATE: Optional[str] = os.getenv("CUTOFF_DATE", "2025-06-01")
    
    @classmethod
    def get_specified_dates(cls) -> list:
        """
        解析 SPECIFIED_DATES 為日期列表
        
        Returns:
            datetime.date 列表，空列表表示未設定
        """
        import datetime
        
        if not cls.SPECIFIED_DATES:
            return []
        
        dates = []
        for date_str in cls.SPECIFIED_DATES.split(','):
            date_str = date_str.strip()
            if date_str:
                try:
                    date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    dates.append(date)
                except ValueError:
                    print(f"警告: 日期格式錯誤: {date_str}")
        
        return sorted(set(dates))  # 去重並排序

    # ========================================
    # Docker & Hawser 資源監控設定 (新增)
    # ========================================
    DOCKER_TARGET_IP: str = os.getenv("DOCKER_TARGET_IP", "192.168.61.3")
    DOCKER_CONTAINER_NAME: str = os.getenv("DOCKER_CONTAINER_NAME", "geovisio_service")
    # Hawser API 連接埠 (2376)
    HAWSER_PORT: int = int(os.getenv("HAWSER_PORT", "2376"))
    
    # Discord 通知設定
    DISCORD_BOT_TOKEN: Optional[str] = os.getenv("DISCORD_BOT_TOKEN")
    DISCORD_CHANNEL_ID: Optional[str] = os.getenv("DISCORD_CHANNEL_ID")
    
    # 監控邏輯參數
    MONITOR_INTERVAL: int = int(os.getenv("MONITOR_INTERVAL", "300")) # 預設 5 分鐘
    MONITOR_MEM_THRESHOLD_MB: int = int(os.getenv("MONITOR_MEM_THRESHOLD_MB", "3072")) # 3GB 告警
    

    
    @classmethod
    def get_auth_config(cls) -> Optional[dict]:
        """
        取得 OAuth 認證配置
        
        Returns:
            認證配置字典，若未啟用認證則回傳 None
        """
        if not cls.ENABLE_AUTH:
            return None
        
        if not all([cls.OAUTH_TOKEN_URL, cls.OAUTH_CLIENT_ID, 
                    cls.OAUTH_CLIENT_SECRET, cls.OAUTH_USERNAME, cls.OAUTH_PASSWORD]):
            print("警告: ENABLE_AUTH=true 但 OAuth 設定不完整")
            return None
        
        return {
            "token_url": cls.OAUTH_TOKEN_URL,
            "client_id": cls.OAUTH_CLIENT_ID,
            "client_secret": cls.OAUTH_CLIENT_SECRET,
            "username": cls.OAUTH_USERNAME,
            "password": cls.OAUTH_PASSWORD,
        }

    @classmethod
    def validate(cls) -> bool:
        """驗證必要設定"""
        errors = []
        
        if not cls.TMS_GEOVISIO_URL:
            errors.append("TMS_GEOVISIO_URL 未設定")
        
        if not cls.CSV_FILE_PATH:
            errors.append("CSV_FILE_PATH 未設定")
        
        if not cls.IMAGE_BASE_PATH:
            errors.append("IMAGE_BASE_PATH 未設定")
        
        # 驗證 OAuth 設定
        if cls.ENABLE_AUTH:
            if not cls.OAUTH_TOKEN_URL:
                errors.append("ENABLE_AUTH=true 但 OAUTH_TOKEN_URL 未設定")
            if not cls.OAUTH_USERNAME:
                errors.append("ENABLE_AUTH=true 但 OAUTH_USERNAME 未設定")
            if not cls.OAUTH_PASSWORD:
                errors.append("ENABLE_AUTH=true 但 OAUTH_PASSWORD 未設定")
        
        if errors:
            for error in errors:
                print(f"設定錯誤: {error}")
            return False
        
        return True
    
    @classmethod
    def get_batch_config(cls, size: int) -> dict:
        """
        根據序列大小取得批次配置
        
        Args:
            size: 序列中的影像數量
            
        Returns:
            配置字典
        """
        if size < cls.SEQUENCE_SMALL_THRESHOLD:
            return {
                'batch_size': cls.BATCH_SIZE_SMALL,
                'batch_delay': cls.BATCH_DELAY_SMALL,
                'max_concurrent': cls.CONCURRENT_SMALL,
                'description': f'小型序列 (< {cls.SEQUENCE_SMALL_THRESHOLD} 張)'
            }
        elif size < cls.SEQUENCE_MEDIUM_THRESHOLD:
            return {
                'batch_size': cls.BATCH_SIZE_MEDIUM,
                'batch_delay': cls.BATCH_DELAY_MEDIUM,
                'max_concurrent': cls.CONCURRENT_MEDIUM,
                'description': f'中型序列 ({cls.SEQUENCE_SMALL_THRESHOLD}-{cls.SEQUENCE_MEDIUM_THRESHOLD} 張)'
            }
        else:
            return {
                'batch_size': cls.BATCH_SIZE_LARGE,
                'batch_delay': cls.BATCH_DELAY_LARGE,
                'max_concurrent': cls.CONCURRENT_LARGE,
                'description': f'大型序列 (> {cls.SEQUENCE_MEDIUM_THRESHOLD} 張)'
            }
    
    @classmethod
    def print_config(cls):
        """列印目前的設定值 (用於除錯)"""
        print("=" * 80)
        print("GeoVisio 上傳系統設定")
        print("=" * 80)
        print(f"{'API URL':<35}: {cls.TMS_GEOVISIO_URL}")
        print(f"{'CSV 路徑':<35}: {cls.CSV_FILE_PATH}")
        print(f"{'影像路徑':<35}: {cls.IMAGE_BASE_PATH}")
        print("-" * 80)
        print(f"{'最大並發上傳數':<35}: {cls.MAX_CONCURRENT_UPLOADS}")
        print(f"{'上傳超時 (秒)':<35}: {cls.UPLOAD_TIMEOUT}")
        print(f"{'序列間延遲 (秒)':<35}: {cls.SEQUENCE_DELAY}")
        print(f"{'日期間延遲 (秒)':<35}: {cls.BATCH_DELAY}")
        print(f"{'連線池大小':<35}: {cls.MAX_POOL_SIZE}")
        print("-" * 80)
        print(f"{'DNS 快取時間 (秒)':<35}: {cls.DNS_CACHE_TTL}")
        print(f"{'連線超時 (秒)':<35}: {cls.CONNECT_TIMEOUT}")
        print(f"{'讀取超時 (秒)':<35}: {cls.READ_TIMEOUT}")
        print(f"{'Keep-Alive 超時 (秒)':<35}: {cls.KEEPALIVE_TIMEOUT}")
        print("-" * 80)
        print(f"{'重試次數':<35}: {cls.RETRY_ATTEMPTS}")
        print(f"{'重試間隔 (秒)':<35}: {cls.RETRY_DELAY}")
        print(f"{'去重失敗行為':<35}: {cls.DEDUP_FAILURE_BEHAVIOR}")
        print("-" * 80)
        print(f"{'小型序列批次':<35}: {cls.BATCH_SIZE_SMALL} 張/批")
        print(f"{'中型序列批次':<35}: {cls.BATCH_SIZE_MEDIUM} 張/批")
        print(f"{'大型序列批次':<35}: {cls.BATCH_SIZE_LARGE} 張/批")
        print("-" * 80)
        print(f"{'Job Queue 安全閾值':<35}: {cls.JOB_QUEUE_SAFE_THRESHOLD}")
        print(f"{'Job Queue 警告閾值':<35}: {cls.JOB_QUEUE_WARNING_THRESHOLD}")
        print("-" * 80)
        print(f"{'啟用去重檢查':<35}: {cls.ENABLE_DEDUPLICATION}")
        print(f"{'啟用 MD5 檢查':<35}: {cls.ENABLE_MD5_CHECK}")
        print(f"{'啟用資源監控':<35}: {cls.ENABLE_RESOURCE_MONITOR}")
        print(f"{'車輛類型':<35}: {cls.VEHICLE_TYPE}")
        print("-" * 80)
        print(f"{'啟用 OAuth 認證':<35}: {cls.ENABLE_AUTH}")
        if cls.ENABLE_AUTH:
            print(f"{'OAuth Token URL':<35}: {cls.OAUTH_TOKEN_URL}")
            print(f"{'OAuth Client ID':<35}: {cls.OAUTH_CLIENT_ID}")
            print(f"{'OAuth Username':<35}: {cls.OAUTH_USERNAME}")
            print(f"{'OAuth Password':<35}: {'*' * len(cls.OAUTH_PASSWORD) if cls.OAUTH_PASSWORD else '(未設定)'}")
        specified_dates = cls.get_specified_dates()
        if specified_dates:
            dates_str = ', '.join(str(d) for d in specified_dates)
            print(f"{'指定日期':<35}: {dates_str} ({len(specified_dates)} 天)")
        else:
            print(f"{'指定日期':<35}: (未設定)")
        print(f"{'截止日期':<35}: {cls.CUTOFF_DATE}")
        print("=" * 80)


# 全域設定實例
settings = Settings()


if __name__ == "__main__":
    # 測試設定
    Settings.print_config()
    print(f"\n設定驗證: {'通過' if Settings.validate() else '失敗'}")
