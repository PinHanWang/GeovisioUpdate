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

# 導入 Pipeline 與配置
try:
    from src.module.TMSUpdate.pipeline.upload_pipeline import GeoVisioUploadPipeline
    from src.module.TMSUpdate.config.logging_config import LOGGING_CONFIG
    # 導入監控模組與設定
    from src.module.TMSUpdate.utils.docker_monitor import HawserDockerMonitor
    from src.module.TMSUpdate.config.settings import settings
except ImportError:
    from pipeline.upload_pipeline import GeoVisioUploadPipeline
    from config.logging_config import LOGGING_CONFIG
    from utils.docker_monitor import HawserDockerMonitor
    from config.settings import settings

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def main():
    """主程式入口"""
    # 1. 初始化 Pipeline 與監控器
    pipeline = GeoVisioUploadPipeline()
    monitor = HawserDockerMonitor()
    
    # 2. 啟動背景監控任務
    # 使用 settings 裡面的間隔時間 (300秒)
    monitor_task = asyncio.create_task(monitor.start(interval=settings.MONITOR_INTERVAL))
    
    try:
        logger.info("GeoVisio 上傳流程開始，背景監控已啟動...")
        # 3. 執行主上傳流程
        await pipeline.run()
        
    except KeyboardInterrupt:
        logger.warning("程式被使用者中斷")
    except Exception as e:
        logger.error("程式執行失敗: %s", str(e), exc_info=True)
        sys.exit(1)
    finally:
        # 4. 清理資源：停止監控並清理 Pipeline
        logger.info("正在關閉服務與監控任務...")
        monitor.stop()
        
        try:
            await asyncio.wait_for(monitor_task, timeout=5.0)
        except asyncio.TimeoutError:
            monitor_task.cancel()
            
        await pipeline.cleanup()
        logger.info("所有流程已結束。")


if __name__ == "__main__":
    # 啟動非同步主程式
    asyncio.run(main())