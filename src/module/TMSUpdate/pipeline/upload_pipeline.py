"""
GeoVisio 上傳流程管理 (重構優化版)

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
    from src.module.TMSUpdate.config.settings import Settings
except ImportError:
    from ..core.csv_encoding_converter import convert_csv_encoding
    from ..core.image_data_preprocessor import data_preprocessing
    from ..config.logging_config import LOGGING_CONFIG
    from ..config.settings import Settings

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)


class GeoVisioUploadPipeline:
    def __init__(self):
        """初始化流程管理"""
        # 注意：環境變數由 Settings 模組統一載入，此處不再重複呼叫 load_dotenv()
        
        # ========================================
        # 從 Settings 讀取設定 (統一管理)
        # ========================================
        self.config = {
            'tms_geovisio_url': Settings.TMS_GEOVISIO_URL,
            'csv_file_path': Settings.CSV_FILE_PATH,
            'sequence_delay': Settings.SEQUENCE_DELAY,
            'batch_delay': Settings.BATCH_DELAY,
            'vehicle_type': Settings.VEHICLE_TYPE,
            'enable_deduplication': Settings.ENABLE_DEDUPLICATION,
            'enable_resource_monitor': Settings.ENABLE_RESOURCE_MONITOR,
            'max_pool_size': Settings.MAX_POOL_SIZE,
            # 新增：連線相關設定
            'dns_cache_ttl': Settings.DNS_CACHE_TTL,
            'connect_timeout': Settings.CONNECT_TIMEOUT,
            'read_timeout': Settings.READ_TIMEOUT,
            'keepalive_timeout': Settings.KEEPALIVE_TIMEOUT,
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
        self.data_results: List[Dict] = []

        logger.info("流程管理 - 初始化完成")

    def validate_env(self) -> None:
        """驗證環境變數"""
        # 使用 Settings 的驗證方法
        if not Settings.validate():
            raise ValueError("必要的環境變數未設定，請檢查 .env 檔案")
        
        logs_dir = Path("logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
        
        # 列印目前設定 (方便除錯)
        Settings.print_config()
        logger.info("流程管理 - 環境變數驗證通過")

    async def initialize_modules(self):
        """初始化各功能模組與全域 Session"""
        logger.info("流程管理 - 開始初始化模組與 Session")
        
        # 1. 建立全局連線池 (使用 Settings 配置)
        connector = aiohttp.TCPConnector(
            limit=self.config['max_pool_size'],
            limit_per_host=10,  # 新增：每個主機的連線上限
            ttl_dns_cache=self.config['dns_cache_ttl'],
            keepalive_timeout=self.config['keepalive_timeout'],
            enable_cleanup_closed=True,  # 新增：清理已關閉的連線
            force_close=False,  # 保持連線重用
        )
        
        # 設定更寬鬆的超時
        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=self.config['connect_timeout'],
            sock_read=self.config['read_timeout'],
            sock_connect=self.config['connect_timeout'],  # 新增
        )
        
        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"Accept-Encoding": "gzip, deflate, identity"},
            raise_for_status=False,  # 不自動拋出 HTTP 錯誤，讓我們手動處理
        )
        
        logger.info(
            "流程管理 - Session 建立完成: 連線池=%d, DNS快取=%d秒, 連線超時=%d秒",
            self.config['max_pool_size'],
            self.config['dns_cache_ttl'],
            self.config['connect_timeout']
        )

        # 2. 初始化 API 客戶端並注入 Session
        try:
            from src.module.TMSUpdate.api.geovisio_api_client import GeoVisioAPIClient
            from src.module.TMSUpdate.api.image_uploader import ImageUploader
        except ImportError:
            # 如果是在模組內部運行，才使用相對路徑
            from ..api.geovisio_api_client import GeoVisioAPIClient
            from ..api.image_uploader import ImageUploader
        
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
            from ..api.image_uploader import ImageUploader
        
        self.uploader = ImageUploader(
            api_client=self.api_client,
            dedup_checker=self.dedup_checker,
            resource_monitor=self.resource_monitor,
            seq_handler=self.seq_handler,
            failure_tracker=self.failure_tracker
        )
        
        logger.info("流程管理 - 所有模組初始化完成")

    async def process_csv_file(self, csv_path: Path) -> pd.DataFrame:
        """處理 CSV 檔案並進行前處理"""
        convert_csv_encoding(csv_path, backup=False)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 檔案不存在: {csv_path}")

        logger.info("流程管理 - 開始前處理 CSV: %s", csv_path)
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
        df = df.copy()
        df['GPSTime'] = pd.to_datetime(df['GPSTime'], errors='coerce')
        df['Date'] = df['GPSTime'].dt.date
        return df.groupby('Date')
    def should_skip_date(
        self,
        collection_date: datetime.date,
        cut_off_date: Optional[datetime.date] = None
    ) -> bool:
        """
        檢查是否應該跳過指定日期
        
        Args:
            collection_date: 要檢查的日期
            cut_off_date: 截止日期 (預設從 Settings.CUTOFF_DATE 讀取)
            
        Returns:
            是否跳過
        """
        if cut_off_date is None:
            # 從 Settings 讀取截止日期
            cutoff_str = Settings.CUTOFF_DATE
            if cutoff_str:
                try:
                    cut_off_date = datetime.datetime.strptime(cutoff_str, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning("流程管理 - CUTOFF_DATE 格式錯誤: %s，使用預設值", cutoff_str)
                    cut_off_date = datetime.date(2025, 6, 1)
            else:
                cut_off_date = datetime.date(2025, 6, 1)
        
        skip = collection_date < cut_off_date
        
        if skip:
            logger.info(
                "流程管理 - 跳過日期: %s (早於 %s)",
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
        上傳單個序列（支援續傳）
        
        流程：
        1. 從 CSV 取得序列資訊（總數、KeyName 清單）
        2. 檢查本地資料庫是否已有此序列的影像
        3. 如果有，取得 collection_id 並查詢 API 已上傳數量
        4. 比對數量，決定是否需要續傳
        """
        # ========================================
        # 1. 從 CSV 取得序列資訊
        # ========================================
        seq_sorted_data = seq_data.sort_values(by='GPSTime')
        if seq_sorted_data.empty:
            logger.error("流程管理 - 序列資料為空: ID=%s", seq_id)
            return None
        
        upload_df = seq_sorted_data.copy()
        if pd.api.types.is_datetime64_any_dtype(upload_df['GPSTime']):
            upload_df['GPSTime'] = upload_df['GPSTime'].dt.strftime('%Y-%m-%dT%H:%M:%S.%f').str[:-3]
        
        csv_keynames = set(upload_df['KeyName'].tolist())
        csv_total = len(csv_keynames)
        
        logger.info(
            "流程管理 - 處理序列 %d/%d: ID=%s, 日期=%s, CSV總數=%d",
            seq_count, total_seq, seq_id, collection_date, csv_total
        )
        
        # ========================================
        # 2. 檢查本地資料庫（用第一張影像）
        # ========================================
        first_keyname = upload_df['KeyName'].iloc[0]
        existing_collection_id = None
        
        if self.dedup_checker:
            existing_collection_id = await self.dedup_checker.get_collection_id_by_keyname(first_keyname)
        
        # ========================================
        # 3. 判斷是新序列還是續傳
        # ========================================
        if existing_collection_id:
            # 續傳模式：查詢 API 取得已上傳數量
            logger.info(
                "流程管理 - 發現既有 Collection: %s，檢查上傳狀態...",
                existing_collection_id
            )
            
            uploaded_keynames = await self.api_client.get_uploaded_keynames(existing_collection_id)
            uploaded_count = len(uploaded_keynames)
            
            if uploaded_count >= csv_total:
                # 已完成
                logger.info(
                    "流程管理 - 序列已完成，跳過: ID=%s (已上傳=%d, CSV總數=%d)",
                    seq_id, uploaded_count, csv_total
                )
                return existing_collection_id
            else:
                # 需要續傳
                pending_df = upload_df[~upload_df['KeyName'].isin(uploaded_keynames)]
                pending_count = len(pending_df)
                
                logger.info(
                    "流程管理 - 續傳模式: ID=%s, 已上傳=%d, 待上傳=%d",
                    seq_id, uploaded_count, pending_count
                )
                
                collection_id = existing_collection_id
        else:
            # 新序列：建立新 Collection
            title = f"交工案第一分案(10米道路) Date: {collection_date}; Sequence ID: {seq_id}"
            description = f"Data for {collection_date}; Sequence ID: {seq_id}"
            keywords = ["交工案", "資料蒐集", f"Sequence ID: {seq_id}", f"日期:{collection_date}"]
            
            collection_id = await self.api_client.create_collection(
                title=title, description=description, keywords=keywords
            )
            
            if not collection_id:
                logger.error("流程管理 - 建立 Collection 失敗: ID=%s", seq_id)
                return None
            
            pending_df = upload_df
            logger.info(
                "流程管理 - 新建 Collection: %s, 待上傳=%d 張",
                collection_id, csv_total
            )
        
        # ========================================
        # 4. 執行影像上傳
        # ========================================
        uploaded_result = await self.uploader.upload_sequence(pending_df, collection_id)
        
        if uploaded_result and uploaded_result.get("successful", 0) > 0:
            logger.info(
                "流程管理 - 序列上傳完成: ID=%s, 本次成功=%d",
                seq_id, uploaded_result["successful"]
            )
            return collection_id
        
        return None
    
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
        logger.info("流程管理 - 處理日期: %s", collection_date)
        
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
            logger.warning("流程管理 - 無序列資料: %s", collection_date)
            return {
                "date": collection_date,
                "total_seq": 0,
                "successful_seq": 0,
                "failed_seq": 0
            }
        
        logger.info("流程管理 - 日期 %s 共有 %d 個序列", collection_date, total_seq)
        
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
                    "流程管理 - 序列處理錯誤: ID=%s, 日期=%s, 錯誤=%s",
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
            "流程管理 - 日期完成: %s, 成功=%d/%d",
            collection_date, successful_seq, total_seq
        )
        
        return result
    
    async def run(self):
        """執行主流程"""
        self.stats['start_time'] = time.time()
        
        try:
            self.validate_env()
            await self.initialize_modules()
            
            csv_path = Path(self.config['csv_file_path'])
            processed_data = await self.process_csv_file(csv_path)
            
            if processed_data.empty:
                logger.warning("流程管理 - 無資料需處理")
                return

            grouped_data = self.group_by_date(processed_data)
            num_dates = len(grouped_data)
            self.stats['total_dates'] = num_dates
            
            logger.info("流程管理 - 開始處理 %d 個日期組", num_dates)
            
            self.data_results = []
            for date_count, (collection_date, group) in enumerate(grouped_data, 1):
                logger.info("流程管理 - 處理進度 [%d/%d]: %s", date_count, num_dates, collection_date)
                
                try:
                    result = await self.upload_date_group(collection_date, group)
                    if result:
                        self.data_results.append(result)
                        self.stats['total_sequences'] += result.get('total_seq', 0)
                        self.stats['successful_sequences'] += result.get('successful_seq', 0)
                        self.stats['failed_sequences'] += result.get('failed_seq', 0)
                    
                    # 關鍵優化：每個日期分組處理完後，清理 group 引用並回收記憶體
                    del group
                    gc.collect()

                    if date_count < num_dates:
                        await asyncio.sleep(self.config['batch_delay'])
                
                except asyncio.CancelledError:
                    logger.warning("流程管理 - 收到取消訊號，準備儲存進度...")
                    raise
                except Exception as e:
                    logger.error("日期 %s 處理中斷: %s", collection_date, str(e))

        except asyncio.CancelledError:
            logger.warning("流程管理 - 任務被取消")
            raise
        except Exception as e:
            logger.error("流程發生嚴重錯誤: %s", str(e), exc_info=True)
            raise
        finally:
            self.stats['end_time'] = time.time()
            await self._finalize()

    async def _finalize(self):
        """
        最終處理（無論成功或失敗都會執行）
        
        包含：列印摘要、儲存報告、清理資源
        """
        logger.info("流程管理 - 開始最終處理...")
        
        # 1. 列印統計摘要
        self.print_final_summary()
        
        # 2. 儲存報告（即使是部分完成的）
        await self.save_reports(self.data_results)
        
        # 3. 清理資源
        await self.cleanup()
        
        logger.info("流程管理 - 最終處理完成")

    async def cleanup(self):
        """
        清理所有資源（健壯版）
        
        確保每個資源都嘗試清理，即使某個失敗也不影響其他資源。
        """
        logger.info("流程管理 - 開始清理資源")
        
        # 定義需要清理的資源列表
        cleanup_tasks = [
            ("去重檢查器", self.dedup_checker, "close"),
            ("資源監控器", self.resource_monitor, "close"),
            ("全域 Session", self.session, "close"),
        ]
        
        errors = []
        
        for name, obj, method_name in cleanup_tasks:
            if obj is None:
                continue
            
            try:
                method = getattr(obj, method_name, None)
                if method is None:
                    logger.warning("流程管理 - %s 沒有 %s 方法", name, method_name)
                    continue
                
                # 判斷是否為協程
                if asyncio.iscoroutinefunction(method):
                    await method()
                else:
                    method()
                
                logger.debug("流程管理 - %s 清理成功", name)
                
            except Exception as e:
                errors.append((name, e))
                logger.error("流程管理 - %s 清理失敗: %s", name, str(e))
        
        # 清理完成後的摘要
        if errors:
            logger.warning(
                "流程管理 - 資源清理完成，但有 %d 個錯誤: %s",
                len(errors),
                ", ".join(name for name, _ in errors)
            )
        else:
            logger.info("流程管理 - 所有資源清理完成")
        
        # 重置引用
        self.dedup_checker = None
        self.resource_monitor = None
        self.session = None
        self.api_client = None
        self.uploader = None

    # 其餘輔助方法 (save_reports, print_final_summary 等) 保持邏輯不變 ...
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
                logger.info("流程管理 - 處理結果已儲存: %s", results_path)
            except Exception as e:
                logger.error("流程管理 - 儲存處理結果失敗: %s", str(e))
        
        # ========================================
        # 3. 記錄執行時間
        # ========================================
        if self.stats['start_time'] and self.stats['end_time']:
            elapsed_time = self.stats['end_time'] - self.stats['start_time']
            logger.info("流程管理 - 總執行時間: %.2f 秒", elapsed_time)