"""
日誌配置模組

提供統一的日誌配置,支援:
1. 多層級日誌輸出 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
2. 檔案輪轉 (防止日誌檔案過大)
3. 分離錯誤日誌
4. 統一的中文格式
"""

import logging.config
from pathlib import Path
from logging.handlers import RotatingFileHandler
import time

# ========================================
# 日誌目錄設定
# ========================================
LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 時間戳 (用於檔案命名)
TIMESTAMP = time.strftime('%Y%m%d_%H%M%S')

# ========================================
# 日誌配置字典
# ========================================
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    
    # ========================================
    # 格式化器定義
    # ========================================
    'formatters': {
        # 詳細格式 (用於檔案)
        'detailed': {
            'format': '[%(asctime)s] [%(levelname)-8s] [%(name)s:%(funcName)s:%(lineno)d] - %(message)s',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        
        # 簡單格式 (用於終端)
        'simple': {
            'format': '[%(asctime)s] [%(levelname)-8s] - %(message)s',
            'datefmt': '%H:%M:%S',
        },
        
        # 最精簡格式 (用於重要訊息)
        'minimal': {
            'format': '[%(levelname)-8s] %(message)s',
        },
    },
    
    # ========================================
    # 處理器定義
    # ========================================
    'handlers': {
        # 檔案處理器 - 完整日誌 (DEBUG 以上)
        'file_all': {
            'level': 'DEBUG',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / f'{TIMESTAMP}_all.log'),
            'maxBytes': 50 * 1024 * 1024,  # 50MB
            'backupCount': 5,
            'encoding': 'utf-8',
            'formatter': 'detailed',
        },
        
        # 檔案處理器 - 錯誤日誌 (WARNING 以上)
        'file_error': {
            'level': 'WARNING',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(LOG_DIR / f'{TIMESTAMP}_error.log'),
            'maxBytes': 10 * 1024 * 1024,  # 10MB
            'backupCount': 3,
            'encoding': 'utf-8',
            'formatter': 'detailed',
        },
        
        # 終端處理器 - 一般訊息 (INFO 以上)
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'stream': 'ext://sys.stdout',
        },
        
        # 終端處理器 - 錯誤訊息 (WARNING 以上)
        'console_error': {
            'level': 'WARNING',
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
            'stream': 'ext://sys.stderr',
        },
    },
    
    # ========================================
    # 根日誌器配置
    # ========================================
    'root': {
        'handlers': ['file_all', 'file_error', 'console'],
        'level': 'DEBUG',
    },
    
    # ========================================
    # 特定模組日誌配置
    # ========================================
    'loggers': {
        # 自訂模組 - 全部使用 DEBUG
        # logging.getLogger(__name__) 取得的是完整模組路徑，
        # key 必須是完整路徑才會匹配 (裸檔名不會生效)
        'src.preprocessing.gps_preprocessor': {
            'level': 'DEBUG',
            'handlers': ['file_all', 'console'],
            'propagate': False,
        },
        'src.optimization.duplicate_checker': {
            'level': 'DEBUG',
            'handlers': ['file_all', 'console'],
            'propagate': False,
        },
        'src.optimization.resource_monitor': {
            'level': 'DEBUG',
            'handlers': ['file_all', 'console'],
            'propagate': False,
        },
        'src.api.geovisio_api_client': {
            'level': 'DEBUG',
            'handlers': ['file_all', 'console'],
            'propagate': False,
        },
        
        # 第三方庫 - 只記錄警告以上
        'asyncio': {
            'level': 'WARNING',
            'handlers': ['file_all'],
            'propagate': False,
        },
        'aiohttp': {
            'level': 'WARNING',
            'handlers': ['file_all'],
            'propagate': False,
        },
        'urllib3': {
            'level': 'WARNING',
            'handlers': ['file_all'],
            'propagate': False,
        },
        'charset_normalizer': {
            'level': 'WARNING',
            'handlers': ['file_all'],
            'propagate': False,
        },
    },
}


# ========================================
# 日誌等級使用指南 (供開發者參考)
# ========================================
"""
日誌等級使用規範:

1. DEBUG (除錯)
   - 用途: 開發階段的詳細資訊
   - 範例: 函數參數、中間變數、詳細流程
   - 範例: logger.debug("函數參數 - csv_path: %s, threshold: %d", csv_path, threshold)

2. INFO (資訊)
   - 用途: 正常運行的重要流程節點
   - 範例: 啟動、完成、統計數據、進度更新
   - 範例: logger.info("序列處理完成 - 成功: %d, 失敗: %d", success, failed)

3. WARNING (警告)
   - 用途: 可能有問題但不影響運行
   - 範例: 資源不足、配置異常、可恢復錯誤
   - 範例: logger.warning("資源監控 - Job Queue: %d 筆 (警告)", count)

4. ERROR (錯誤)
   - 用途: 發生錯誤但程式可以繼續
   - 範例: 單次上傳失敗、API 錯誤、檔案讀取失敗
   - 範例: logger.error("影像上傳失敗 - KeyName: %s, 錯誤: %s", keyname, error)

5. CRITICAL (嚴重)
   - 用途: 嚴重錯誤,程式需要終止
   - 範例: 初始化失敗、資料庫無法連線、關鍵資源缺失
   - 範例: logger.critical("資料庫連線失敗,程式無法繼續: %s", error)
"""


# ========================================
# 日誌訊息格式規範 (供開發者參考)
# ========================================
"""
訊息格式規範:

1. 統一使用中文
   ✅ logger.info("開始處理 CSV 檔案: %s", csv_path)
   ❌ logger.info("Starting to process CSV file: %s", csv_path)

2. 使用參數化格式 (不要用 f-string)
   ✅ logger.info("上傳成功 - KeyName: %s, 序號: %d", keyname, seq)
   ❌ logger.info(f"上傳成功 - KeyName: {keyname}, 序號: {seq}")

3. 避免過多 emoji
   ✅ logger.info("批次處理 - 當前: %d/%d", current, total)
   ❌ logger.info("📦 處理批次 %d/%d ✅", current, total)

4. 使用固定前綴標識模組
   ✅ logger.info("資源監控 - Job Queue: %d 筆", count)
   ✅ logger.info("去重檢查 - 快取命中: %s", filename)
   ✅ logger.info("API 請求 - URL: %s, 狀態: %d", url, status)

5. 錯誤訊息要包含足夠的上下文
   ✅ logger.error("影像上傳失敗 - KeyName: %s, Collection: %s, 錯誤: %s", 
                  keyname, collection_id, error)
   ❌ logger.error("上傳失敗: %s", error)

6. 統計報告使用固定格式
   logger.info("=" * 80)
   logger.info("上傳統計報告")
   logger.info("=" * 80)
   logger.info("%-30s: %10d", "總數", total)
   logger.info("%-30s: %10d", "成功", success)
   logger.info("%-30s: %10d", "失敗", failed)
   logger.info("=" * 80)
"""


# ========================================
# 輔助函數
# ========================================
def get_logger(name: str) -> logging.Logger:
    """
    取得指定名稱的日誌器
    
    Args:
        name: 日誌器名稱 (通常使用 __name__)
        
    Returns:
        配置好的日誌器
    """
    return logging.getLogger(name)


def setup_logging():
    """
    設定日誌系統
    
    應在程式啟動時呼叫一次
    """
    logging.config.dictConfig(LOGGING_CONFIG)
    logger = get_logger(__name__)
    logger.info("=" * 80)
    logger.info("日誌系統初始化完成")
    logger.info("日誌檔案位置: %s", LOG_DIR)
    logger.info("完整日誌: %s", LOG_DIR / f'{TIMESTAMP}_all.log')
    logger.info("錯誤日誌: %s", LOG_DIR / f'{TIMESTAMP}_error.log')
    logger.info("=" * 80)


# ========================================
# 範例使用方式
# ========================================
if __name__ == "__main__":
    # 設定日誌
    setup_logging()
    
    # 取得日誌器
    logger = get_logger(__name__)
    
    # 各種等級的日誌範例
    logger.debug("這是 DEBUG 訊息 - 用於開發除錯")
    logger.info("這是 INFO 訊息 - 用於正常流程")
    logger.warning("這是 WARNING 訊息 - 用於警告")
    logger.error("這是 ERROR 訊息 - 用於錯誤")
    logger.critical("這是 CRITICAL 訊息 - 用於嚴重錯誤")
    
    # 參數化日誌範例
    csv_path = "/path/to/file.csv"
    record_count = 1000
    logger.info("CSV 處理完成 - 檔案: %s, 記錄數: %d", csv_path, record_count)
    
    # 統計報告範例
    logger.info("=" * 80)
    logger.info("處理統計")
    logger.info("=" * 80)
    logger.info("%-30s: %10d", "總記錄數", 5000)
    logger.info("%-30s: %10d", "成功處理", 4800)
    logger.info("%-30s: %10d", "處理失敗", 200)
    logger.info("%-30s: %10.2f%%", "成功率", 96.0)
    logger.info("=" * 80)