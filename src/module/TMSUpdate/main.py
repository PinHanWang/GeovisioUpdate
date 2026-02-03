"""
GeoVisio 上傳流程主程式 (重構版)

將原本的 main 函數重構為 GeoVisioUploadPipeline class,
提供更清晰的職責分離和更好的可維護性。

主要改進:
- 將所有全域函數封裝到 Pipeline class 中
- 清楚的初始化、執行、清理生命週期
- 更好的錯誤處理和資源管理
- 統一的日誌記錄
"""

import os
import sys
import time
import asyncio
import datetime
import logging.config
from pathlib import Path
from typing import Dict, Any, Optional, List
import pandas as pd
from dotenv import load_dotenv

# 導入自定義模組
from src.module.TMSUpdate.core.csv_encoding_converter import convert_csv_encoding
from src.module.TMSUpdate.core.image_data_preprocessor import data_preprocessing
from src.module.TMSUpdate.config.logging_config import LOGGING_CONFIG

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


# ========================================
# GeoVisio 上傳流程管理器
# ========================================
class GeoVisioUploadPipeline:
    """
    GeoVisio 上傳流程管理器
    
    封裝完整的 GeoVisio 影像上傳流程,包括:
    - 環境變數驗證
    - CSV 檔案處理
    - 資料前處理
    - Collection 創建
    - 影像批次上傳
    - 失敗報告生成
    
    Attributes:
        config: 配置字典
        api_client: GeoVisio API 客戶端
        uploader: 影像上傳器
        failure_tracker: 失敗追蹤器
        dedup_checker: 去重檢查器
        resource_monitor: 資源監控器
        seq_handler: 序列批次處理器
    """
    
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
            'enable_resource_monitor': os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"
        }
        
        # ========================================
        # 模組實例 (延遲初始化)
        # ========================================
        self.api_client = None
        self.uploader = None
        self.failure_tracker = None
        self.dedup_checker = None
        self.resource_monitor = None
        self.seq_handler = None
        
        # 統計資訊
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
        """
        驗證環境變數
        
        Raises:
            ValueError: 必要的環境變數未設定
            TypeError: 環境變數型別錯誤
            OSError: 日誌目錄創建失敗
        """
        if self.config['tms_geovisio_url'] is None:
            raise ValueError("TMS_GEOVISIO_URL 未在環境變數中設定")
        
        if not isinstance(self.config['tms_geovisio_url'], str):
            raise TypeError("TMS_GEOVISIO_URL 必須是字串型別")
        
        if self.config['csv_file_path'] is None:
            raise ValueError("CSV_FILE_PATH 未在環境變數中設定")
        
        if not isinstance(self.config['csv_file_path'], str):
            raise TypeError("CSV_FILE_PATH 必須是字串型別")
        
        # 創建日誌目錄
        logs_dir = Path("logs")
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            logger.info("流程管理器 - 日誌目錄已準備: %s", logs_dir)
        except OSError as e:
            logger.error("流程管理器 - 創建日誌目錄失敗: %s", str(e))
            raise OSError(f"創建日誌目錄失敗: {e}") from e
    
    async def initialize_modules(self):
        """
        初始化各功能模組
        
        依序初始化:
        1. API 客戶端
        2. 失敗追蹤器
        3. 去重檢查器
        4. 資源監控器
        5. 序列批次處理器
        6. 影像上傳器
        """
        logger.info("流程管理器 - 開始初始化模組")
        
        # ========================================
        # 1. API 客戶端
        # ========================================
        from src.module.TMSUpdate.api.geovisio_api_client import GeoVisioAPIClient
        
        self.api_client = GeoVisioAPIClient(
            base_url=self.config['tms_geovisio_url']
        )
        logger.info("流程管理器 - API 客戶端已初始化")
        
        # ========================================
        # 2. 失敗追蹤器
        # ========================================
        from src.module.TMSUpdate.core.failure_checker import get_failure_tracker
        
        self.failure_tracker = get_failure_tracker()
        self.failure_tracker.clear()  # 清空舊記錄
        logger.info("流程管理器 - 失敗追蹤器已初始化")
        
        # ========================================
        # 3. 去重檢查器 (可選)
        # ========================================
        if self.config['enable_deduplication']:
            try:
                from src.module.TMSUpdate.optmization.duplicate_checker import get_duplicate_checker
                
                self.dedup_checker = get_duplicate_checker()
                await self.dedup_checker.initialize()
                logger.info("流程管理器 - 去重檢查器已初始化")
            except Exception as e:
                logger.error("流程管理器 - 去重檢查器初始化失敗: %s", str(e))
                logger.warning("流程管理器 - 將繼續執行,但去重功能將被停用")
                self.dedup_checker = None
        
        # ========================================
        # 4. 資源監控器 (可選)
        # ========================================
        if self.config['enable_resource_monitor']:
            try:
                from src.module.TMSUpdate.optmization.resource_monitor import simple_resource_monitor
                
                self.resource_monitor = simple_resource_monitor
                await self.resource_monitor.initialize()
                logger.info("流程管理器 - 資源監控器已初始化")
            except Exception as e:
                logger.error("流程管理器 - 資源監控器初始化失敗: %s", str(e))
                logger.warning("流程管理器 - 將繼續執行,但資源監控功能將被停用")
                self.resource_monitor = None
        
        # ========================================
        # 5. 序列批次處理器
        # ========================================
        try:
            from src.module.TMSUpdate.optmization.sequence_batch_handler import large_seq_handler
            
            self.seq_handler = large_seq_handler
            logger.info("流程管理器 - 序列批次處理器已初始化")
        except Exception as e:
            logger.error("流程管理器 - 序列批次處理器初始化失敗: %s", str(e))
            self.seq_handler = None
        
        # ========================================
        # 6. 影像上傳器
        # ========================================
        from src.module.TMSUpdate.api.geovisio_api_client import ImageUploader
        
        self.uploader = ImageUploader(
            api_client=self.api_client,
            dedup_checker=self.dedup_checker,
            resource_monitor=self.resource_monitor,
            seq_handler=self.seq_handler,
            failure_tracker=self.failure_tracker
        )
        logger.info("流程管理器 - 影像上傳器已初始化")
        
        logger.info("流程管理器 - 所有模組初始化完成")
    
    async def process_csv_file(self, csv_path: Path) -> pd.DataFrame:
        """
        處理 CSV 檔案
        
        Args:
            csv_path: CSV 檔案路徑
            
        Returns:
            處理後的 DataFrame
            
        Raises:
            FileNotFoundError: 檔案不存在
        """
        # 轉換編碼
        convert_csv_encoding(csv_path, backup=False)
        
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 檔案不存在: {csv_path}")
        
        logger.info("流程管理器 - 開始處理 CSV 檔案: %s", csv_path)
        
        # 資料前處理
        vehicle_type = self.config['vehicle_type']
        
        if vehicle_type == "CAR":
            # 10米以上道路
            processed_data = data_preprocessing(
                csv_path,
                time_threshold=500,
                distance_threshold=200.0
            )
        elif vehicle_type == 'MOTORCYCLE':
            # 人行道標線
            processed_data = data_preprocessing(
                csv_path,
                time_threshold=300,
                distance_threshold=20.0
            )
        else:
            # 預設
            processed_data = data_preprocessing(csv_path)
        
        if processed_data.empty:
            logger.warning("流程管理器 - 處理後無資料")
            return processed_data
        
        logger.info("流程管理器 - CSV 處理完成,資料筆數: %d", len(processed_data))
        return processed_data
    
    def group_by_date(self, df: pd.DataFrame) -> pd.core.groupby.DataFrameGroupBy:
        """
        按日期分組
        
        Args:
            df: DataFrame
            
        Returns:
            按日期分組的 GroupBy 物件
            
        Raises:
            KeyError: GPSTime 欄位不存在
            ValueError: GPSTime 欄位無法轉換
        """
        if 'GPSTime' not in df.columns:
            raise KeyError("DataFrame 中找不到 'GPSTime' 欄位")
        
        try:
            if not pd.api.types.is_datetime64_any_dtype(df['GPSTime']):
                df['GPSTime'] = pd.to_datetime(df['GPSTime'], errors='coerce')
            
            df['Date'] = df['GPSTime'].dt.date
            grouped_data = df.groupby('Date')
            
            logger.info("流程管理器 - 資料已按日期分組: %d 個日期", len(grouped_data))
            return grouped_data
        
        except Exception as e:
            logger.error("流程管理器 - 日期分組失敗: %s", str(e))
            raise ValueError(f"處理 GPSTime 欄位失敗: {e}") from e
    
    def should_skip_date(
        self,
        collection_date: datetime.date,
        cut_off_date: Optional[datetime.date] = None
    ) -> bool:
        """
        檢查是否應該跳過指定日期
        
        Args:
            collection_date: 要檢查的日期
            cut_off_date: 截止日期 (預設: 2025-06-01)
            
        Returns:
            是否跳過
        """
        if cut_off_date is None:
            cut_off_date = datetime.date(2025, 6, 1)
        
        skip = collection_date < cut_off_date
        
        if skip:
            logger.info(
                "流程管理器 - 跳過日期: %s (早於 %s)",
                collection_date, cut_off_date
            )
        
        return skip
    
    async def upload_single_sequence(
        self,
        seq_data: pd.DataFrame,
        seq_id: str,
        collection_date: datetime.date,
        seq_count: int,
        total_seq: int
    ) -> Optional[str]:
        """
        上傳單個序列
        
        Args:
            seq_data: 序列資料
            seq_id: 序列 ID
            collection_date: Collection 日期
            seq_count: 序列編號
            total_seq: 總序列數
            
        Returns:
            Collection ID,失敗時返回 None
        """
        logger.info(
            "流程管理器 - 處理序列 %d/%d: ID=%s, 日期=%s",
            seq_count, total_seq, seq_id, collection_date
        )
        
        # 排序資料
        seq_sorted_data = seq_data.sort_values(by='GPSTime')
        
        if seq_sorted_data.empty:
            logger.error(
                "流程管理器 - 序列資料為空,跳過: ID=%s, 日期=%s",
                seq_id, collection_date
            )
            return None
        
        # 創建 Collection
        title = f"交工案第一分案資料蒐集(10米以上道路) Date: {collection_date}; Sequence ID: {seq_id}"
        description = f"Data collection for {collection_date}; Sequence ID: {seq_id}"
        keywords = [
            "交工案", "第一分案", "10米以上道路", "資料蒐集",
            f"Sequence ID:{seq_id}", f"日期:{collection_date}"
        ]
        
        collection_id = await self.api_client.create_collection(
            title=title,
            description=description,
            keywords=keywords
        )
        
        if not collection_id:
            logger.error(
                "流程管理器 - Collection 創建失敗: ID=%s, 日期=%s",
                seq_id, collection_date
            )
            return None
        
        logger.debug("流程管理器 - Collection 已創建: %s", collection_id)
        
        # 上傳影像
        uploaded_result = await self.uploader.upload_sequence(
            seq_sorted_data,
            collection_id
        )
        
        if uploaded_result and uploaded_result.get("successful", 0) > 0:
            successful = uploaded_result["successful"]
            failed = uploaded_result["failed"]
            
            logger.info(
                "流程管理器 - 序列上傳成功: ID=%s, 日期=%s, 成功=%d, 失敗=%d",
                seq_id, collection_date, successful, failed
            )
        else:
            logger.error(
                "流程管理器 - 序列上傳失敗: ID=%s, 日期=%s",
                seq_id, collection_date
            )
        
        return collection_id
    
    async def upload_date_group(
        self,
        collection_date: datetime.date,
        group_data: pd.DataFrame
    ) -> Dict:
        """
        上傳單日資料
        
        Args:
            collection_date: 日期
            group_data: 該日期的資料
            
        Returns:
            上傳結果統計
        """
        logger.info("流程管理器 - 處理日期: %s", collection_date)
        
        # 檢查是否跳過
        if self.should_skip_date(collection_date):
            return {
                "date": collection_date,
                "total_seq": 0,
                "successful_seq": 0,
                "failed_seq": 0,
                "skipped": True
            }
        
        # 按 group_id 分組
        if 'group_id' not in group_data.columns:
            raise ValueError("DataFrame 中找不到 'group_id' 欄位")
        
        seq_data_groups = group_data.groupby('group_id')
        total_seq = len(seq_data_groups)
        
        if total_seq == 0:
            logger.warning("流程管理器 - 無序列資料: %s", collection_date)
            return {
                "date": collection_date,
                "total_seq": 0,
                "successful_seq": 0,
                "failed_seq": 0
            }
        
        logger.info("流程管理器 - 日期 %s 共有 %d 個序列", collection_date, total_seq)
        
        # 上傳所有序列
        successful_seq = 0
        failed_seq = 0
        
        for count, (seq_id, seq_data) in enumerate(seq_data_groups, 1):
            try:
                collection_id = await self.upload_single_sequence(
                    seq_data, seq_id, collection_date, count, total_seq
                )
                
                if collection_id:
                    successful_seq += 1
                else:
                    failed_seq += 1
                
                # 序列間延遲
                if count < total_seq:
                    await asyncio.sleep(self.config['sequence_delay'])
            
            except Exception as e:
                logger.error(
                    "流程管理器 - 序列處理錯誤: ID=%s, 日期=%s, 錯誤=%s",
                    seq_id, collection_date, str(e),
                    exc_info=True
                )
                failed_seq += 1
        
        result = {
            "date": collection_date,
            "total_seq": total_seq,
            "successful_seq": successful_seq,
            "failed_seq": failed_seq
        }
        
        logger.info(
            "流程管理器 - 日期完成: %s, 成功=%d/%d",
            collection_date, successful_seq, total_seq
        )
        
        return result
    
    async def run(self):
        """
        執行完整上傳流程
        
        主要步驟:
        1. 驗證環境變數
        2. 初始化模組
        3. 處理 CSV 檔案
        4. 按日期分組
        5. 依序上傳每日資料
        6. 生成統計報告
        7. 儲存失敗報告
        """
        self.stats['start_time'] = time.time()
        
        try:
            # ========================================
            # 1. 驗證環境變數
            # ========================================
            logger.info("流程管理器 - 驗證環境變數")
            self.validate_env()
            
            # ========================================
            # 2. 初始化模組
            # ========================================
            logger.info("流程管理器 - 初始化模組")
            await self.initialize_modules()
            
            # ========================================
            # 3. 處理 CSV 檔案
            # ========================================
            csv_path = Path(self.config['csv_file_path'])
            processed_data = await self.process_csv_file(csv_path)
            
            if processed_data.empty:
                logger.warning("流程管理器 - 無資料需處理")
                return
            
            # ========================================
            # 4. 按日期分組
            # ========================================
            grouped_data = self.group_by_date(processed_data)
            num_dates = len(grouped_data)
            self.stats['total_dates'] = num_dates
            
            logger.info("流程管理器 - 共有 %d 個日期需處理", num_dates)
            
            # ========================================
            # 5. 依序上傳每日資料
            # ========================================
            date_results = []
            
            for date_count, (collection_date, group) in enumerate(grouped_data, 1):
                logger.info(
                    "流程管理器 - 處理日期 %d/%d: %s",
                    date_count, num_dates, collection_date
                )
                
                try:
                    result = await self.upload_date_group(collection_date, group)
                    
                    if result:
                        date_results.append(result)
                        
                        # 更新統計
                        self.stats['total_sequences'] += result.get('total_seq', 0)
                        self.stats['successful_sequences'] += result.get('successful_seq', 0)
                        self.stats['failed_sequences'] += result.get('failed_seq', 0)
                    
                    # 日期間延遲
                    if date_count < num_dates:
                        logger.info(
                            "流程管理器 - 等待 %d 秒後處理下一日期",
                            self.config['batch_delay']
                        )
                        await asyncio.sleep(self.config['batch_delay'])
                
                except Exception as e:
                    logger.error(
                        "流程管理器 - 日期處理錯誤: %s, 錯誤=%s",
                        collection_date, str(e)
                    )
                    date_results.append({
                        "date": collection_date,
                        "successful_seq": 0,
                        "total_seq": 0,
                        "failed_seq": 0,
                        "error": str(e)
                    })
            
            # ========================================
            # 6. 生成統計報告
            # ========================================
            self.print_final_summary()
            
            # ========================================
            # 7. 儲存報告
            # ========================================
            await self.save_reports(date_results)
        
        except Exception as e:
            logger.error("流程管理器 - 執行過程發生嚴重錯誤: %s", str(e), exc_info=True)
            raise
        
        finally:
            self.stats['end_time'] = time.time()
    
    def print_final_summary(self):
        """列印最終統計報告"""
        logger.info("=" * 80)
        logger.info("最終處理摘要")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "處理日期總數", self.stats['total_dates'])
        logger.info("%-30s: %10d", "序列總數", self.stats['total_sequences'])
        logger.info("%-30s: %10d", "成功序列", self.stats['successful_sequences'])
        logger.info("%-30s: %10d", "失敗序列", self.stats['failed_sequences'])
        
        if self.failure_tracker:
            logger.info("%-30s: %10d", "上傳失敗", self.failure_tracker.get_upload_failure_count())
            logger.info("%-30s: %10d", "Collection 失敗", self.failure_tracker.get_collection_failure_count())
        
        logger.info("=" * 80)
        
        # 顯示去重統計
        if self.dedup_checker:
            self.dedup_checker.print_stats()
    
    async def save_reports(self, date_results: List[Dict]):
        """
        儲存報告
        
        Args:
            date_results: 每日處理結果列表
        """
        timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        
        # ========================================
        # 1. 儲存失敗報告
        # ========================================
        if self.failure_tracker:
            await self.failure_tracker.save_reports()
        
        # ========================================
        # 2. 儲存處理結果統計
        # ========================================
        if date_results:
            try:
                results_df = pd.DataFrame(date_results)
                results_path = Path("logs") / f"{timestamp}_processing_results.csv"
                results_df.to_csv(results_path, index=False, encoding='utf-8-sig')
                logger.info("流程管理器 - 處理結果已儲存: %s", results_path)
            except Exception as e:
                logger.error("流程管理器 - 儲存處理結果失敗: %s", str(e))
        
        # ========================================
        # 3. 記錄執行時間
        # ========================================
        if self.stats['start_time'] and self.stats['end_time']:
            elapsed_time = self.stats['end_time'] - self.stats['start_time']
            logger.info("流程管理器 - 總執行時間: %.2f 秒", elapsed_time)
    
    async def cleanup(self):
        """
        清理資源
        
        關閉所有已初始化的模組
        """
        logger.info("流程管理器 - 開始清理資源")
        
        try:
            # 關閉去重檢查器
            if self.dedup_checker:
                await self.dedup_checker.close()
                logger.info("流程管理器 - 去重檢查器已關閉")
            
            # 關閉資源監控器
            if self.resource_monitor:
                await self.resource_monitor.close()
                logger.info("流程管理器 - 資源監控器已關閉")
        
        except Exception as e:
            logger.error("流程管理器 - 清理資源時發生錯誤: %s", str(e))
        
        logger.info("流程管理器 - 資源清理完成")


# ========================================
# 主程式入口
# ========================================
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