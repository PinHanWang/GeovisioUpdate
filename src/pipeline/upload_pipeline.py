"""
GeoVisio 上傳流程管理 (重構優化版)

優化重點:
1. 全域 Session 管理: 統一初始化並注入子模組,解決連線池洩漏問題。
2. 記憶體管理: 增加週期性垃圾回收與物件釋放,適合處理大型 CSV。
3. 更好的清理機制: 確保程式退出時關閉所有非同步資源。
"""

import time
import gc
import asyncio
import datetime
import logging
import logging.config
import aiohttp
from pathlib import Path
from typing import Any
import pandas as pd

# 導入自定義模組
try:
    from src.core.csv_encoding_converter import convert_csv_encoding
    from src.core.image_data_preprocessor import data_preprocessing
    from src.config.logging_config import LOGGING_CONFIG
    from src.config.settings import Settings
    from src.api.geovisio_api_client import GeoVisioAPIClient
    from src.api.image_uploader import ImageUploader
    from src.core.failure_checker import get_failure_tracker
    from src.optimization.duplicate_checker import get_duplicate_checker
    from src.optimization.resource_monitor import simple_resource_monitor
    from src.optimization.sequence_batch_handler import large_seq_handler
except ImportError:
    from ..core.csv_encoding_converter import convert_csv_encoding
    from ..core.image_data_preprocessor import data_preprocessing
    from ..config.logging_config import LOGGING_CONFIG
    from ..config.settings import Settings
    from ..api.geovisio_api_client import GeoVisioAPIClient
    from ..api.image_uploader import ImageUploader
    from ..core.failure_checker import get_failure_tracker
    from ..optimization.duplicate_checker import get_duplicate_checker
    from ..optimization.resource_monitor import simple_resource_monitor
    from ..optimization.sequence_batch_handler import large_seq_handler

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# 各運具類型的序列分割閾值
_VEHICLE_THRESHOLDS: dict[str, dict[str, float]] = {
    "CAR":        {"time_threshold": 500, "distance_threshold": 200.0},
    "MOTORCYCLE": {"time_threshold": 300, "distance_threshold": 20.0},
}


class GeoVisioUploadPipeline:
    def __init__(self) -> None:
        """初始化流程管理"""
        # 模組實例 (延遲初始化)
        self.session: aiohttp.ClientSession | None = None  # 全域 Session
        self.api_client: GeoVisioAPIClient | None = None
        self.uploader: ImageUploader | None = None
        self.failure_tracker = None
        self.dedup_checker = None
        self.resource_monitor = None
        self.seq_handler = None
        self._specified_dates_cache: list | None = None  # 快取已解析的指定日期

        self.stats: dict[str, Any] = {
            'start_time': None,
            'end_time': None,
            'total_csv': 0,
            'total_dates': 0,
            'total_sequences': 0,
            'successful_sequences': 0,
            'failed_sequences': 0
        }
        self.data_results: list[dict] = []

        logger.info("流程管理 - 初始化完成")

    def validate_env(self) -> None:
        """驗證環境變數"""
        if not Settings.validate():
            raise ValueError("必要的環境變數未設定，請檢查 .env 檔案")

        Path("logs").mkdir(parents=True, exist_ok=True)

        Settings.print_config()
        logger.info("流程管理 - 環境變數驗證通過")

    async def initialize_modules(self) -> None:
        """初始化各功能模組與全域 Session"""
        logger.info("流程管理 - 開始初始化模組與 Session")

        # 1. 建立全局連線池
        connector = aiohttp.TCPConnector(
            limit=Settings.MAX_POOL_SIZE,
            # GeoVisio API 只有單一主機，per-host 上限等於全域上限即可，
            # 避免它比 MAX_CONCURRENT_UPLOADS 更早成為併發瓶頸
            limit_per_host=Settings.MAX_POOL_SIZE,
            ttl_dns_cache=Settings.DNS_CACHE_TTL,
            keepalive_timeout=Settings.KEEPALIVE_TIMEOUT,
            enable_cleanup_closed=True,
            force_close=False,
        )

        timeout = aiohttp.ClientTimeout(
            total=None,
            connect=Settings.CONNECT_TIMEOUT,
            sock_read=Settings.READ_TIMEOUT,
            sock_connect=Settings.CONNECT_TIMEOUT,
        )

        self.session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={"Accept-Encoding": "gzip, deflate, identity"},
            raise_for_status=False,
        )

        logger.info(
            "流程管理 - Session 建立完成: 連線池=%d, DNS快取=%d秒, 連線超時=%d秒",
            Settings.MAX_POOL_SIZE,
            Settings.DNS_CACHE_TTL,
            Settings.CONNECT_TIMEOUT
        )

        # 2. 初始化 API 客戶端並注入 Session
        self.api_client = GeoVisioAPIClient(
            base_url=Settings.TMS_GEOVISIO_URL,
            session=self.session,
            auth_config=Settings.get_auth_config()
        )

        # 3. 初始化其餘模組
        try:
            self.failure_tracker = get_failure_tracker()
            self.failure_tracker.clear()
        except Exception:
            logger.warning("失敗追蹤器初始化失敗")

        if Settings.ENABLE_DEDUPLICATION:
            try:
                self.dedup_checker = get_duplicate_checker()
                await self.dedup_checker.initialize()
            except Exception as e:
                logger.error("去重檢查器初始化失敗: %s", str(e))
                self.dedup_checker = None

        if Settings.ENABLE_RESOURCE_MONITOR:
            try:
                self.resource_monitor = simple_resource_monitor
                await self.resource_monitor.initialize()
            except Exception as e:
                logger.error("資源監控器初始化失敗: %s", str(e))
                self.resource_monitor = None

        self.seq_handler = large_seq_handler

        # 4. 初始化上傳器
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
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 檔案不存在: {csv_path}")
        # 編碼偵測/轉換與 pandas 前處理都是同步阻塞操作，丟到執行緒池執行，
        # 避免卡住同一個 event loop 上的 Docker 監控等背景協程
        await asyncio.to_thread(convert_csv_encoding, csv_path, backup=False)

        logger.info("流程管理 - 開始前處理 CSV: %s", csv_path)
        params = _VEHICLE_THRESHOLDS.get(Settings.VEHICLE_TYPE, {})
        return await asyncio.to_thread(data_preprocessing, csv_path, **params)

    def group_by_date(self, df: pd.DataFrame) -> pd.core.groupby.DataFrameGroupBy:
        """按日期分組資料"""
        if 'GPSTime' not in df.columns:
            raise KeyError("DataFrame 找不到 'GPSTime' 欄位")

        df = df.copy()
        df['GPSTime'] = pd.to_datetime(df['GPSTime'], errors='coerce')
        df['Date'] = df['GPSTime'].dt.date
        return df.groupby('Date')

    def should_skip_date(self, collection_date: datetime.date) -> bool:
        """
        檢查是否應該跳過指定日期

        支援三種模式 (依優先順序):
        1. SPECIFIED_DATES: 只處理指定的日期列表 (最高優先)
        2. CUTOFF_DATE: 跳過早於該日期的資料
        3. 都未設定: 處理所有日期

        Returns:
            True = 跳過此日期, False = 處理此日期
        """
        # 模式 1: 指定日期列表 (最高優先)：快取解析結果，避免每次呼叫都重新分割字串
        if self._specified_dates_cache is None:
            self._specified_dates_cache = Settings.get_specified_dates()
        specified_dates = self._specified_dates_cache

        if specified_dates:
            if collection_date in specified_dates:
                logger.info(
                    "流程管理 - 處理指定日期: %s ✓ (共 %d 天待處理)",
                    collection_date, len(specified_dates)
                )
                return False
            logger.info("流程管理 - 跳過日期: %s (不在指定日期列表中)", collection_date)
            return True

        # 模式 2: 截止日期 (次優先)
        if Settings.CUTOFF_DATE:
            try:
                cutoff_date = datetime.datetime.strptime(Settings.CUTOFF_DATE, "%Y-%m-%d").date()
                if collection_date < cutoff_date:
                    logger.info(
                        "流程管理 - 跳過日期: %s (早於截止日期 %s)",
                        collection_date, cutoff_date
                    )
                    return True
            except ValueError:
                logger.warning(
                    "流程管理 - CUTOFF_DATE 格式錯誤: %s，忽略此設定",
                    Settings.CUTOFF_DATE
                )

        # 模式 3: 處理所有日期
        return False

    async def upload_single_sequence(
        self,
        seq_data: pd.DataFrame,
        seq_id: str,
        collection_date: datetime.date,
    ) -> str | None:
        """
        上傳單個序列（支援續傳）

        流程：
        1. 從 CSV 取得序列資訊（總數、KeyName 清單）
        2. 檢查本地資料庫是否已有此序列的影像
        3. 如果有，取得 collection_id 並查詢 API 已上傳數量
        4. 比對數量，決定是否需要續傳
        """
        # 1. 從 CSV 取得序列資訊
        upload_df = seq_data.sort_values(by='GPSTime').copy()
        if upload_df.empty:
            logger.error("流程管理 - 序列資料為空: ID=%s", seq_id)
            return None

        if pd.api.types.is_datetime64_any_dtype(upload_df['GPSTime']):
            upload_df['GPSTime'] = upload_df['GPSTime'].dt.strftime('%Y-%m-%dT%H:%M:%S.%f').str[:-3]

        csv_total = upload_df['KeyName'].nunique()

        # 2. 檢查本地資料庫（用第一張影像判斷是否有既有記錄）
        first_keyname_exists = False
        if self.dedup_checker:
            first_keyname = upload_df['KeyName'].iloc[0]
            first_keyname_exists = await self.dedup_checker.check_keyname_exists_in_db(first_keyname)

        # 3. 判斷是新序列還是續傳
        if first_keyname_exists:
            existing_collection = await self.api_client.find_collection_by_sequence(
                seq_id=str(seq_id),
                collection_date=str(collection_date)
            )
        else:
            existing_collection = None

        if existing_collection:
            # 續傳模式：查詢 API 取得已上傳數量
            collection_id = existing_collection.get('id')
            logger.info("流程管理 - 發現既有 Collection: %s，檢查上傳狀態...", collection_id)

            uploaded_keynames = await self.api_client.get_uploaded_keynames(collection_id)
            uploaded_count = len(uploaded_keynames)

            if uploaded_count >= csv_total:
                logger.info(
                    "流程管理 - 序列已完成，跳過: ID=%s (已上傳=%d, CSV總數=%d)",
                    seq_id, uploaded_count, csv_total
                )
                return collection_id

            pending_df = upload_df[~upload_df['KeyName'].isin(uploaded_keynames)]
            logger.info(
                "流程管理 - 續傳模式: ID=%s, 已上傳=%d, 待上傳=%d",
                seq_id, uploaded_count, len(pending_df)
            )
        else:
            # 新序列：建立新 Collection
            title = f"{Settings.PROJECT_NAME} Date: {collection_date}; Sequence ID: {seq_id}"
            description = f"Data for {collection_date}; Sequence ID: {seq_id}"
            keywords = ["交工案", "資料蒐集", f"Sequence ID: {seq_id}", f"日期:{collection_date}"]

            collection_id = await self.api_client.create_collection(
                title=title, description=description, keywords=keywords
            )

            if not collection_id:
                logger.error("流程管理 - 建立 Collection 失敗: ID=%s", seq_id)
                return None

            pending_df = upload_df
            logger.info("流程管理 - 新建 Collection: %s, 待上傳=%d 張", collection_id, csv_total)

        # 4. 執行影像上傳
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
    ) -> dict[str, Any]:
        """
        上傳單日資料

        Returns:
            上傳結果統計
        """
        logger.info("流程管理 - 處理日期: %s", collection_date)

        if self.should_skip_date(collection_date):
            return {"date": collection_date, "total_seq": 0, "successful_seq": 0, "failed_seq": 0, "skipped": True}

        if 'group_id' not in group_data.columns:
            raise ValueError("DataFrame 中找不到 'group_id' 欄位")

        seq_data_groups = group_data.groupby('group_id')
        total_seq = len(seq_data_groups)

        if total_seq == 0:
            logger.warning("流程管理 - 無序列資料: %s", collection_date)
            return {"date": collection_date, "total_seq": 0, "successful_seq": 0, "failed_seq": 0, "skipped": False}

        logger.info("流程管理 - 日期 %s 共有 %d 個序列", collection_date, total_seq)

        successful_seq = 0
        failed_seq = 0

        for count, (seq_id, seq_data) in enumerate(seq_data_groups, 1):
            logger.info(
                "流程管理 - 處理序列 %d/%d: ID=%s, 日期=%s",
                count, total_seq, seq_id, collection_date
            )
            try:
                collection_id = await self.upload_single_sequence(seq_data, seq_id, collection_date)

                if collection_id:
                    successful_seq += 1
                else:
                    failed_seq += 1

                if count < total_seq:
                    await asyncio.sleep(Settings.SEQUENCE_DELAY)

            except Exception as e:
                logger.error(
                    "流程管理 - 序列處理錯誤: ID=%s, 日期=%s, 錯誤=%s",
                    seq_id, collection_date, str(e),
                    exc_info=True
                )
                failed_seq += 1

        logger.info(
            "流程管理 - 日期完成: %s, 成功=%d/%d",
            collection_date, successful_seq, total_seq
        )

        return {
            "date": collection_date,
            "total_seq": total_seq,
            "successful_seq": successful_seq,
            "failed_seq": failed_seq,
            "skipped": False
        }

    async def _process_single_csv(self, csv_path: Path, csv_index: int, csv_total: int) -> None:
        """處理單一 CSV 檔案"""
        logger.info("=" * 60)
        logger.info("流程管理 - 處理 CSV [%d/%d]: %s", csv_index, csv_total, csv_path.name)
        logger.info("=" * 60)

        processed_data = await self.process_csv_file(csv_path)

        if processed_data.empty:
            logger.warning("流程管理 - CSV 無資料需處理: %s", csv_path.name)
            return

        grouped_data = self.group_by_date(processed_data)
        num_dates = len(grouped_data)
        self.stats['total_dates'] += num_dates

        logger.info("流程管理 - CSV %s 包含 %d 個日期組", csv_path.name, num_dates)

        for date_count, (collection_date, group) in enumerate(grouped_data, 1):
            logger.info(
                "流程管理 - [CSV %d/%d] 日期進度 [%d/%d]: %s",
                csv_index, csv_total, date_count, num_dates, collection_date
            )

            try:
                result = await self.upload_date_group(collection_date, group)
                if result:
                    self.data_results.append(result)
                    self.stats['total_sequences'] += result.get('total_seq', 0)
                    self.stats['successful_sequences'] += result.get('successful_seq', 0)
                    self.stats['failed_sequences'] += result.get('failed_seq', 0)

                del group
                gc.collect()

                if date_count < num_dates:
                    await asyncio.sleep(Settings.BATCH_DELAY)

            except asyncio.CancelledError:
                logger.warning("流程管理 - 收到取消訊號，準備儲存進度...")
                raise
            except Exception as e:
                logger.error("日期 %s 處理中斷: %s", collection_date, str(e))

        del processed_data, grouped_data
        gc.collect()
        logger.info("流程管理 - CSV 處理完成: %s", csv_path.name)

    async def run(self) -> None:
        """執行主流程（支援多 CSV 批次處理）"""
        self.stats['start_time'] = time.time()

        try:
            self.validate_env()
            await self.initialize_modules()

            csv_files = Settings.get_csv_files()
            if not csv_files:
                logger.error("流程管理 - 找不到任何 CSV 檔案")
                return

            csv_total = len(csv_files)
            self.stats['total_csv'] = csv_total
            logger.info("流程管理 - 共找到 %d 個 CSV 檔案待處理", csv_total)
            for i, f in enumerate(csv_files, 1):
                logger.info("  [%d] %s", i, f.name)

            for csv_index, csv_path in enumerate(csv_files, 1):
                try:
                    await self._process_single_csv(csv_path, csv_index, csv_total)

                    if csv_index < csv_total:
                        logger.info("流程管理 - CSV 間延遲 %d 秒...", Settings.BATCH_DELAY)
                        await asyncio.sleep(Settings.BATCH_DELAY)

                except asyncio.CancelledError:
                    logger.warning("流程管理 - 任務被取消")
                    raise
                except Exception as e:
                    logger.error(
                        "流程管理 - CSV 處理失敗: %s, 錯誤: %s，繼續處理下一個",
                        csv_path.name, str(e), exc_info=True
                    )

        except asyncio.CancelledError:
            logger.warning("流程管理 - 任務被取消")
            raise
        except Exception as e:
            logger.error("流程發生嚴重錯誤: %s", str(e), exc_info=True)
            raise
        finally:
            self.stats['end_time'] = time.time()
            await self._finalize()

    async def _finalize(self) -> None:
        """最終處理（無論成功或失敗都會執行）"""
        logger.info("流程管理 - 開始最終處理...")
        self.print_final_summary()
        await self.save_reports(self.data_results)
        await self.cleanup()
        logger.info("流程管理 - 最終處理完成")

    async def cleanup(self) -> None:
        """清理所有資源（確保每個資源都嘗試清理，即使某個失敗也不影響其他資源）"""
        logger.info("流程管理 - 開始清理資源")

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
                if asyncio.iscoroutinefunction(method):
                    await method()
                else:
                    method()
                logger.debug("流程管理 - %s 清理成功", name)
            except Exception as e:
                errors.append((name, e))
                logger.error("流程管理 - %s 清理失敗: %s", name, str(e))

        if errors:
            logger.warning(
                "流程管理 - 資源清理完成，但有 %d 個錯誤: %s",
                len(errors),
                ", ".join(name for name, _ in errors)
            )
        else:
            logger.info("流程管理 - 所有資源清理完成")

        self.dedup_checker = None
        self.resource_monitor = None
        self.session = None
        self.api_client = None
        self.uploader = None

    def print_final_summary(self) -> None:
        """列印最終統計報告"""
        logger.info("=" * 80)
        logger.info("最終處理摘要")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "CSV 檔案總數", self.stats['total_csv'])
        logger.info("%-30s: %10d", "處理日期總數", self.stats['total_dates'])
        logger.info("%-30s: %10d", "序列總數", self.stats['total_sequences'])
        logger.info("%-30s: %10d", "成功序列", self.stats['successful_sequences'])
        logger.info("%-30s: %10d", "失敗序列", self.stats['failed_sequences'])

        if self.failure_tracker:
            logger.info("%-30s: %10d", "上傳失敗", self.failure_tracker.get_upload_failure_count())
            logger.info("%-30s: %10d", "Collection 失敗", self.failure_tracker.get_collection_failure_count())

        logger.info("=" * 80)

        if self.dedup_checker:
            self.dedup_checker.print_stats()

    async def save_reports(self, date_results: list[dict]) -> None:
        """儲存報告"""
        timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')

        if self.failure_tracker:
            await self.failure_tracker.save_reports()

        if date_results:
            try:
                results_df = pd.DataFrame(date_results)
                results_path = Path("logs") / f"{timestamp}_processing_results.csv"
                results_df.to_csv(results_path, index=False, encoding='utf-8-sig')
                logger.info("流程管理 - 處理結果已儲存: %s", results_path)
            except Exception as e:
                logger.error("流程管理 - 儲存處理結果失敗: %s", str(e))

        if self.stats['start_time'] and self.stats['end_time']:
            elapsed_time = self.stats['end_time'] - self.stats['start_time']
            logger.info("流程管理 - 總執行時間: %.2f 秒", elapsed_time)
