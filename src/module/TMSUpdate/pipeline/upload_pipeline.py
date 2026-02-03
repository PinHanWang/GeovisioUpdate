"""
GeoVisio 上傳流程管理器 (重構優化版)

優化重點:
1. 全域 Session 管理: 統一初始化並注入子模組,解決連線池洩漏問題。
2. 記憶體管理: 增加週期性垃圾回收與物件釋放,適合處理大型 CSV。
3. 更好的清理機制: 確保程式退出時關閉所有非同步資源。
"""

import os
import time
import gc
import asyncio
import datetime
import aiohttp
import logging.config
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd
from dotenv import load_dotenv

# 導入自定義模組
try:
    from src.module.TMSUpdate.core.csv_encoding_converter import convert_csv_encoding
    from src.module.TMSUpdate.core.image_data_preprocessor import data_preprocessing
    from src.module.TMSUpdate.config.logging_config import LOGGING_CONFIG
except ImportError:
    from core.csv_encoding_converter import convert_csv_encoding
    from core.image_data_preprocessor import data_preprocessing
    from config.logging_config import LOGGING_CONFIG

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


class GeoVisioUploadPipeline:
    def __init__(self):
        """初始化流程管理器"""
        load_dotenv()
        
        # ========================================
        # 載入環境變數
        # ========================================
        self.config = {
            'tms_geovisio_url': os.getenv("TMS_GEOVISIO_URL"),
            'csv_file_path': os.getenv("CSV_FILE_PATH"),
            'sequence_delay': int(os.getenv("SEQUENCE_DELAY", "3")),
            'batch_delay': int(os.getenv("BATCH_DELAY", "300")),
            'vehicle_type': os.getenv("VEHICLE_TYPE", "CAR"),
            'enable_deduplication': os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true",
            'enable_resource_monitor': os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true",
            'max_pool_size': int(os.getenv("MAX_POOL_SIZE", "10"))  # 新增: 連線池限制
        }
        
        # ========================================
        # 模組實例 (延遲初始化)
        # ========================================
        self.session = None  # 全域 Session
        self.api_client = None
        self.uploader = None
        self.failure_tracker = None
        self.dedup_checker = None
        self.resource_monitor = None
        self.seq_handler = None
        
        self.stats = {
            'start_time': None,
            'end_time': None,
            'total_dates': 0,
            'total_sequences': 0,
            'successful_sequences': 0,
            'failed_sequences': 0
        }
        
        logger.info("流程管理器 - 初始化完成")

    def validate_env(self) -> None:
        """驗證環境變數"""
        if self.config['tms_geovisio_url'] is None:
            raise ValueError("TMS_GEOVISIO_URL 未在環境變數中設定")
        if self.config['csv_file_path'] is None:
            raise ValueError("CSV_FILE_PATH 未在環境變數中設定")
        
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        logger.info("流程管理器 - 環境變數驗證通過")

    async def initialize_modules(self):
        """初始化各功能模組與全域 Session"""
        logger.info("流程管理器 - 開始初始化模組與 Session")
        
        # 1. 建立全局連線池 (核心修改)
        connector = aiohttp.TCPConnector(limit=self.config['max_pool_size'], ttl_dns_cache=300)
        self.session = aiohttp.ClientSession(
            connector=connector,
            headers={"Accept-Encoding": "gzip, deflate, identity"}
        )

        # 2. 初始化 API 客戶端並注入 Session
        try:
            from src.module.TMSUpdate.api.geovisio_api_client import GeoVisioAPIClient
        except ImportError:
            from api.geovisio_api_client import GeoVisioAPIClient
        
        self.api_client = GeoVisioAPIClient(
            base_url=self.config['tms_geovisio_url'],
            session=self.session
        )

        # 3. 初始化其餘模組 (保持原邏輯)
        try:
            from src.module.TMSUpdate.core.failure_checker import get_failure_tracker
            self.failure_tracker = get_failure_tracker()
            self.failure_tracker.clear()
        except Exception:
            logger.warning("失敗追蹤器初始化失敗")

        if self.config['enable_deduplication']:
            try:
                from src.module.TMSUpdate.optimization.duplicate_checker import get_duplicate_checker
                self.dedup_checker = get_duplicate_checker()
                await self.dedup_checker.initialize()
            except Exception as e:
                logger.error("去重檢查器初始化失敗: %s", str(e))
                self.dedup_checker = None

        if self.config['enable_resource_monitor']:
            try:
                from src.module.TMSUpdate.optimization.resource_monitor import simple_resource_monitor
                self.resource_monitor = simple_resource_monitor
                await self.resource_monitor.initialize()
            except Exception as e:
                logger.error("資源監控器初始化失敗: %s", str(e))
                self.resource_monitor = None

        try:
            from src.module.TMSUpdate.optimization.sequence_batch_handler import large_seq_handler
            self.seq_handler = large_seq_handler
        except Exception:
            self.seq_handler = None

        # 4. 初始化上傳器 (自動繼承 api_client 的 session)
        try:
            from src.module.TMSUpdate.api.image_uploader import ImageUploader
        except ImportError:
            from api.image_uploader import ImageUploader
        
        self.uploader = ImageUploader(
            api_client=self.api_client,
            dedup_checker=self.dedup_checker,
            resource_monitor=self.resource_monitor,
            seq_handler=self.seq_handler,
            failure_tracker=self.failure_tracker
        )
        
        logger.info("流程管理器 - 所有模組初始化完成")

    async def process_csv_file(self, csv_path: Path) -> pd.DataFrame:
        """處理 CSV 檔案並進行前處理"""
        convert_csv_encoding(csv_path, backup=False)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 檔案不存在: {csv_path}")

        logger.info("流程管理器 - 開始前處理 CSV: %s", csv_path)
        v_type = self.config['vehicle_type']
        
        # 根據運具類型動態調整參數
        params = {
            "CAR": {"time_threshold": 500, "distance_threshold": 200.0},
            "MOTORCYCLE": {"time_threshold": 300, "distance_threshold": 20.0}
        }.get(v_type, {})

        processed_data = data_preprocessing(csv_path, **params)
        return processed_data

    def group_by_date(self, df: pd.DataFrame) -> pd.core.groupby.DataFrameGroupBy:
        """按日期分組資料"""
        if 'GPSTime' not in df.columns:
            raise KeyError("DataFrame 找不到 'GPSTime' 欄位")
        
        # 使用 normalize() 較省資源且穩定
        df['GPSTime'] = pd.to_datetime(df['GPSTime'], errors='coerce')
        df['Date'] = df['GPSTime'].dt.date
        return df.groupby('Date')

    async def run(self):
        """執行主流程"""
        self.stats['start_time'] = time.time()
        
        try:
            self.validate_env()
            await self.initialize_modules()
            
            csv_path = Path(self.config['csv_file_path'])
            processed_data = await self.process_csv_file(csv_path)
            
            if processed_data.empty:
                logger.warning("流程管理器 - 無資料需處理")
                return

            grouped_data = self.group_by_date(processed_data)
            num_dates = len(grouped_data)
            self.stats['total_dates'] = num_dates
            
            logger.info("流程管理器 - 開始處理 %d 個日期組", num_dates)
            
            date_results = []
            for date_count, (collection_date, group) in enumerate(grouped_data, 1):
                logger.info("流程管理器 - 處理進度 [%d/%d]: %s", date_count, num_dates, collection_date)
                
                try:
                    result = await self.upload_date_group(collection_date, group)
                    if result:
                        date_results.append(result)
                        self.stats['total_sequences'] += result.get('total_seq', 0)
                        self.stats['successful_sequences'] += result.get('successful_seq', 0)
                        self.stats['failed_sequences'] += result.get('failed_seq', 0)
                    
                    # 關鍵優化：每個日期分組處理完後，清理 group 引用並回收記憶體
                    del group
                    gc.collect()

                    if date_count < num_dates:
                        await asyncio.sleep(self.config['batch_delay'])
                
                except Exception as e:
                    logger.error("日期 %s 處理中斷: %s", collection_date, str(e))

            self.print_final_summary()
            await self.save_reports(date_results)
        
        except Exception as e:
            logger.error("流程發生嚴重錯誤: %s", str(e), exc_info=True)
            raise
        finally:
            await self.cleanup()
            self.stats['end_time'] = time.time()

    async def cleanup(self):
        """清理所有資源 (核心修改)"""
        logger.info("流程管理器 - 開始清理資源")
        try:
            if self.dedup_checker:
                await self.dedup_checker.close()
            if self.resource_monitor:
                await self.resource_monitor.close()
            # 關閉全局 Session
            if self.session:
                await self.session.close()
                logger.info("流程管理器 - 全域 Session 已關閉")
        except Exception as e:
            logger.error("清理資源時發生異常: %s", str(e))
        logger.info("流程管理器 - 資源清理完成")

    # 其餘輔助方法 (save_reports, print_final_summary 等) 保持邏輯不變 ...
    async def save_reports(self, date_results: List[Dict]):
        """儲存報告"""
        timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        if self.failure_tracker:
            await self.failure_tracker.save_reports()
        if date_results:
            results_df = pd.DataFrame(date_results)
            results_path = Path("logs") / f"{timestamp}_processing_results.csv"
            results_df.to_csv(results_path, index=False, encoding='utf-8-sig')
            logger.info("報告已儲存: %s", results_path)

    def print_final_summary(self):
        """列印最終摘要"""
        logger.info("=" * 60)
        logger.info("上傳任務完成 - 總日期: %d, 總序列: %d, 成功: %d", 
                    self.stats['total_dates'], self.stats['total_sequences'], self.stats['successful_sequences'])
        logger.info("=" * 60)