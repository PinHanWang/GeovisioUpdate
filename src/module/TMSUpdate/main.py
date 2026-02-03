"""
GeoVisio 上傳流程主程式入口

這是程式的主要入口點,負責:
1. 創建 Pipeline 實例
2. 執行上傳流程
3. 處理異常和清理資源
"""

import sys
import asyncio
import logging.config

# 導入 Pipeline
try:
    from src.module.TMSUpdate.pipeline.upload_pipeline import GeoVisioUploadPipeline
    from src.module.TMSUpdate.config.logging_config import LOGGING_CONFIG
except ImportError:
    from pipeline.upload_pipeline import GeoVisioUploadPipeline
    from config.logging_config import LOGGING_CONFIG

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def main():
    """主程式入口"""
    pipeline = GeoVisioUploadPipeline()
    
    try:
        await pipeline.run()
    except KeyboardInterrupt:
        logger.warning("程式被使用者中斷")
    except Exception as e:
        logger.error("程式執行失敗: %s", str(e), exc_info=True)
        sys.exit(1)
    finally:
        await pipeline.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
