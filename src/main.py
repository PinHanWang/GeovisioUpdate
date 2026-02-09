"""
GeoVisio 上傳流程主程式入口
"""

import sys
import asyncio
import logging.config
from pathlib import Path

# ========================================
# 動態調整 Python Path（支援直接執行）
# ========================================
# 取得專案根目錄 (GeovisioUpdate)
_current_file = Path(__file__).resolve()
_project_root = _current_file.parent.parent  # src -> GeovisioUpdate

# 如果專案根目錄不在 sys.path 中，加入它
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ========================================
# 導入 Pipeline 與配置
# ========================================
from src.pipeline.upload_pipeline import GeoVisioUploadPipeline
from src.config.logging_config import LOGGING_CONFIG
from src.config.settings import Settings
from src.utils.docker_monitor import HawserDockerMonitor

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


async def main():
    """主程式入口"""
    pipeline = GeoVisioUploadPipeline()
    monitor = HawserDockerMonitor()
    
    # 使用 Settings 讀取監控間隔
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
