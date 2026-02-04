"""
GeoVisio 上傳流程主程式入口
"""

import sys
import asyncio
import logging.config

# 導入 Pipeline 與配置
try:
    from src.module.TMSUpdate.pipeline.upload_pipeline import GeoVisioUploadPipeline
    from src.module.TMSUpdate.config.logging_config import LOGGING_CONFIG
    from src.module.TMSUpdate.config.settings import Settings  # 改成大寫
    from src.module.TMSUpdate.utils.docker_monitor import HawserDockerMonitor
except ImportError:
    from .pipeline.upload_pipeline import GeoVisioUploadPipeline  # 加上 .
    from .config.logging_config import LOGGING_CONFIG  # 加上 .
    from .config.settings import Settings  # 加上 . 並改成大寫
    from .utils.docker_monitor import HawserDockerMonitor  # 加上 .

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def main():
    """主程式入口"""
    pipeline = GeoVisioUploadPipeline()
    monitor = HawserDockerMonitor()
    
    # 使用 Settings（大寫）
    monitor_task = asyncio.create_task(monitor.start(interval=Settings.MONITOR_INTERVAL))
    
    try:
        logger.info("GeoVisio 上傳流程開始，背景監控已啟動...")
        await pipeline.run()
        
    except KeyboardInterrupt:
        logger.warning("程式被使用者中斷")
    except Exception as e:
        logger.error("程式執行失敗: %s", str(e), exc_info=True)
        sys.exit(1)
    finally:
        logger.info("正在關閉服務與監控任務...")
        monitor.stop()
        
        try:
            await asyncio.wait_for(monitor_task, timeout=5.0)
        except asyncio.TimeoutError:
            monitor_task.cancel()
            
        await pipeline.cleanup()
        logger.info("所有流程已結束。")


if __name__ == "__main__":
    asyncio.run(main())