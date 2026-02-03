"""
全域設定模組

集中管理所有環境變數和設定值
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """應用程式設定"""
    
    # GeoVisio API
    TMS_GEOVISIO_URL: str = os.getenv("TMS_GEOVISIO_URL", "")
    
    # 檔案路徑
    CSV_FILE_PATH: Optional[str] = os.getenv("CSV_FILE_PATH")
    IMAGE_BASE_PATH: Optional[str] = os.getenv("IMAGE_BASE_PATH")
    
    # 資料庫
    DATABASE_URL: Optional[str] = os.getenv("DATABASE_URL")
    
    # 上傳設定
    MAX_CONCURRENT_UPLOADS: int = int(os.getenv("MAX_CONCURRENT_UPLOADS", "5"))
    UPLOAD_TIMEOUT: int = int(os.getenv("UPLOAD_TIMEOUT", "60"))
    SEQUENCE_DELAY: int = int(os.getenv("SEQUENCE_DELAY", "3"))
    BATCH_DELAY: int = int(os.getenv("BATCH_DELAY", "300"))
    
    # 功能開關
    ENABLE_DEDUPLICATION: bool = os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true"
    ENABLE_MD5_CHECK: bool = os.getenv("ENABLE_MD5_CHECK", "true").lower() == "true"
    ENABLE_RESOURCE_MONITOR: bool = os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"
    
    # 車輛類型
    VEHICLE_TYPE: str = os.getenv("VEHICLE_TYPE", "CAR")
    
    @classmethod
    def validate(cls) -> bool:
        """驗證必要設定"""
        errors = []
        
        if not cls.TMS_GEOVISIO_URL:
            errors.append("TMS_GEOVISIO_URL 未設定")
        
        if not cls.CSV_FILE_PATH:
            errors.append("CSV_FILE_PATH 未設定")
        
        if errors:
            for error in errors:
                print(f"設定錯誤: {error}")
            return False
        
        return True


# 全域設定實例
settings = Settings()