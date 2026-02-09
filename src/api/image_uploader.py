"""
影像上傳管理器模組 (重構優化版)

負責影像上傳的複雜邏輯,包括:
- 重試機制 (Tenacity)
- 去重檢查 (Deduplication)
- 資源監控 (Resource Monitor)
- 記憶體優化 (Streaming Upload & GC)

優化重點:
1. 流式上傳: 使用檔案句柄直接上傳,不預載入記憶體,降低 90% 以上記憶體峰值。
2. 連線複用: 使用注入的全域 Session,避免產生大量 TIME_WAIT 連線。
3. 主動回收: 批次結束後強制觸發 GC,防止容器記憶體持續膨脹。
"""

import os
import gc  # 導入垃圾回收模組
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any, TYPE_CHECKING
import aiohttp
from aiohttp import (
    ClientTimeout,
    ServerDisconnectedError,
    ClientConnectorError,
    ServerTimeoutError,
)
import pandas as pd
from aiohttp import (
    ClientTimeout,
    ServerDisconnectedError,
    ClientConnectorError,
    ServerTimeoutError,
    ClientOSError,  # 新增
    ClientResponseError,  # 新增
)
from tenacity import (
    retry, 
    stop_after_attempt, 
    wait_exponential,  # 改用指數退避
    wait_random_exponential,  # 或隨機指數退避
    retry_if_exception_type,
    before_sleep_log,  # 重試前記錄日誌
    RetryError
)
from dotenv import load_dotenv
# 從獨立模組導入異常類別 (避免循環 import)
try:
    from src.api.exceptions import (
        ImageAlreadyExistsError,
        RetryableUploadError
    )
    from src.config.settings import Settings
except ImportError:
    from .exceptions import ImageAlreadyExistsError, RetryableUploadError
    from ..config.settings import Settings

# Type hint 用 (避免循環 import)
if TYPE_CHECKING:
    from src.module.TMSUpdate.api.geovisio_api_client import GeoVisioAPIClient

logger = logging.getLogger(__name__)


RETRYABLE_EXCEPTIONS = (
    RetryableUploadError,
    asyncio.TimeoutError,
    ServerDisconnectedError,
    ClientConnectorError,
    ServerTimeoutError,
    ConnectionResetError,
    ClientOSError,  # 包含更多網路錯誤
    OSError,  # 底層網路錯誤
    )
# image_uploader.py

import gc
import psutil  # 需要安裝：pip install psutil
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryAwareGC:
    """
    記憶體感知的 GC 管理器
    
    只在記憶體使用率超過閾值時才觸發 GC，
    並且限制 GC 頻率避免過度呼叫。
    """
    
    def __init__(
        self,
        memory_threshold_percent: float = 75.0,
        min_interval_seconds: float = 30.0
    ):
        """
        Args:
            memory_threshold_percent: 記憶體使用率閾值（超過才觸發 GC）
            min_interval_seconds: 兩次 GC 之間的最小間隔
        """
        self.memory_threshold = memory_threshold_percent
        self.min_interval = min_interval_seconds
        self._last_gc_time: float = 0
        self._gc_count: int = 0
    
    def should_collect(self) -> bool:
        """判斷是否應該執行 GC"""
        import time
        
        # 檢查時間間隔
        current_time = time.time()
        if current_time - self._last_gc_time < self.min_interval:
            return False
        
        # 檢查記憶體使用率
        try:
            memory_percent = psutil.virtual_memory().percent
            return memory_percent > self.memory_threshold
        except Exception:
            # psutil 失敗時，使用保守策略（不觸發）
            return False
    
    def collect_if_needed(self, force: bool = False) -> bool:
        """
        按需執行 GC
        
        Args:
            force: 是否強制執行（忽略閾值檢查）
            
        Returns:
            是否實際執行了 GC
        """
        import time
        
        if not force and not self.should_collect():
            return False
        
        # 執行 GC
        collected = gc.collect()
        self._last_gc_time = time.time()
        self._gc_count += 1
        
        try:
            memory_percent = psutil.virtual_memory().percent
            logger.info(
                "記憶體管理 - GC 執行完成: 回收 %d 物件, 目前記憶體使用率 %.1f%%",
                collected, memory_percent
            )
        except Exception:
            logger.info("記憶體管理 - GC 執行完成: 回收 %d 物件", collected)
        
        return True
    
    def get_stats(self) -> dict:
        """取得統計資訊"""
        try:
            mem = psutil.virtual_memory()
            return {
                'gc_count': self._gc_count,
                'memory_percent': mem.percent,
                'memory_available_mb': mem.available / (1024 * 1024),
            }
        except Exception:
            return {'gc_count': self._gc_count}


# 全域實例
memory_gc = MemoryAwareGC(
    memory_threshold_percent=75.0,
    min_interval_seconds=30.0
)

# ========================================
# 影像上傳管理器
# ========================================
class ImageUploader:
    """
    影像上傳管理器
    
    負責影像上傳的複雜邏輯,包括流式傳輸與自動資源管理。
    """
    
    def __init__(
        self,
        api_client: "GeoVisioAPIClient",
        dedup_checker=None,
        resource_monitor=None,
        seq_handler=None,
        failure_tracker=None
    ):
        """
        初始化上傳管理器
        
        Args:
            api_client: GeoVisioAPIClient 實例 (需包含已初始化的 session)
            dedup_checker: 去重檢查器
            resource_monitor: 資源監控器
            seq_handler: 序列批次處理器
            failure_tracker: 失敗追蹤器
        """
        self.api_client = api_client
        # 重要修改：直接使用注入的全域 Session，不再於內部自行建立
        self.session = api_client.session 
        
        self.dedup_checker = dedup_checker
        self.resource_monitor = resource_monitor
        self.seq_handler = seq_handler
        self.failure_tracker = failure_tracker
        
        # 從 Settings 讀取設定 (統一管理)
        self.image_base_path = Settings.IMAGE_BASE_PATH
        self.max_concurrent = Settings.MAX_CONCURRENT_UPLOADS
        self.upload_timeout = Settings.UPLOAD_TIMEOUT
        
        # 功能開關
        self.enable_deduplication = Settings.ENABLE_DEDUPLICATION
        self.enable_md5_check = Settings.ENABLE_MD5_CHECK
        self.enable_resource_monitor = Settings.ENABLE_RESOURCE_MONITOR
        
        # 重試設定
        self.retry_attempts = Settings.RETRY_ATTEMPTS
        self.retry_min_wait = getattr(Settings, 'RETRY_MIN_WAIT', 1)  # 最小等待 1 秒
        self.retry_max_wait = getattr(Settings, 'RETRY_MAX_WAIT', 30)  # 最大等待 30 秒
        self.retry_delay = Settings.RETRY_DELAY
        
        # 去重失敗行為
        self.dedup_failure_behavior = Settings.DEDUP_FAILURE_BEHAVIOR

        self.memory_gc = MemoryAwareGC(
            memory_threshold_percent=75.0,
            min_interval_seconds=30.0
        )
        
        logger.info("影像上傳 - 初始化完成 (連線複用與流式傳輸模式)")
        logger.info("影像上傳 - 參數設定：併發數量: %d, 超時: %d 秒, 重試: %d 次",
                    self.max_concurrent, self.upload_timeout, self.retry_attempts)

    def _log_retry_error(self, retry_state):
        """重試失敗回調函數"""
        if hasattr(retry_state, 'args') and len(retry_state.args) >= 3:
            collection_id = retry_state.args[1]
            keyname = retry_state.args[2]
        else:
            collection_id = retry_state.kwargs.get('collection_id', 'Unknown')
            keyname = retry_state.kwargs.get('keyname', 'Unknown')
        
        error_msg = str(retry_state.outcome.exception()) if retry_state.outcome and retry_state.outcome.exception() else "Unknown error"
        
        # 409 或已存在錯誤視為成功，其餘記錄失敗
        if "409" in error_msg or "already exist" in error_msg.lower() or isinstance(retry_state.outcome.exception(), ImageAlreadyExistsError):
            logger.info("影像上傳 - 影像已存在,視為成功: KeyName=%s", keyname)
            return
        
        logger.error("影像上傳 - 重試後仍失敗: KeyName=%s, 錯誤=%s", keyname, error_msg)
        
        if self.failure_tracker:
            self.failure_tracker.record_upload_failure(
                keyname=keyname,
                collection_id=collection_id,
                error=error_msg,
                retry_count=retry_state.attempt_number
            )
            self.failure_tracker.record_collection_failure(collection_id)

    async def _upload_single_image_impl(
        self,
        session: aiohttp.ClientSession,
        collection_id: str,
        keyname: str,
        gps_time: Any,
        gps_x: float,
        gps_y: float,
        speed: float,
        img_url: str,
        seq: int
    ) -> bool:
        """上傳單張影像的實際實現"""
        # --- 新增：處理 Pandas Timestamp 序列化問題 ---
        formatted_gps_time = gps_time
        if hasattr(gps_time, 'isoformat'):
            # 如果是 Pandas Timestamp 或 datetime 物件，轉為字串
            formatted_gps_time = gps_time.isoformat()
        elif not isinstance(gps_time, str):
            formatted_gps_time = str(gps_time)
        # --------------------------------------------

        # 1. 去重檢查
        if self.enable_deduplication and self.dedup_checker:
            try:
                should_skip, reason = await self.dedup_checker.should_skip_upload(
                    keyname=keyname,
                    img_url=img_url,
                    check_md5=self.enable_md5_check,
                    session=session
                )
                if should_skip:
                    logger.info("影像上傳 - 跳過重複: KeyName=%s, 原因=%s", keyname, reason)
                    raise ImageAlreadyExistsError(reason)
            except ImageAlreadyExistsError:
                raise
            except Exception as e:
                logger.warning("影像上傳 - 重複性檢查失敗, KeyName=%s, 錯誤=%s", keyname, str(e))
                # 根據設定決定失敗時的行為
                if self.dedup_failure_behavior == "skip":
                    logger.warning("影像上傳 - 重複性檢查失敗策略為 skip，跳過此影像: %s", keyname)
                    raise ImageAlreadyExistsError(f"重複性檢查失敗，保守跳過: {keyname}")
        
        # 2. 準備上傳
        url = f"{self.api_client.base_url}/api/collections/{collection_id}/items"
        image_path = os.path.join(self.image_base_path, f'{keyname}.jpg')
        
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"影像檔案不存在: {image_path}")

        try:
            with open(image_path, 'rb') as img_file:
                form_data = aiohttp.FormData()
                form_data.add_field("position", str(seq))
                form_data.add_field("isBlurred", "true")
                form_data.add_field("override_capture_time", formatted_gps_time)
                form_data.add_field("override_latitude", str(gps_y))
                form_data.add_field("override_longitude", str(gps_x))
                
                form_data.add_field(
                    'picture',
                    img_file,
                    filename=os.path.basename(image_path),
                    content_type='image/jpeg'
                )

                timeout = ClientTimeout(total=self.upload_timeout)
                
                async with session.post(url, data=form_data, timeout=timeout) as resp:
                    if resp.status in [200, 201, 202]:
                        logger.debug("影像上傳 - 成功: KeyName=%s", keyname)
                        return True
                    elif resp.status == 409:
                        error_text = await resp.text()
                        logger.info("影像上傳 - 影像已存在 (409): KeyName=%s", keyname)
                        raise ImageAlreadyExistsError(f"影像已存在: {error_text}")
                    elif resp.status >= 500:
                        # 伺服器錯誤，應該重試
                        error_text = await resp.text()
                        raise RetryableUploadError(
                            f"伺服器錯誤 (HTTP {resp.status}): {error_text[:200]}"
                        )
                    else:
                        # 4xx 客戶端錯誤（除了 409），不應重試
                        error_text = await resp.text()
                        logger.error(
                            "影像上傳 - 客戶端錯誤 (不重試): KeyName=%s, HTTP %d, %s",
                            keyname, resp.status, error_text[:200]
                        )
                        return False

        except ImageAlreadyExistsError:
            raise  # 直接拋出，讓上層處理
        
        except (ServerDisconnectedError, ClientConnectorError, 
                ServerTimeoutError, asyncio.TimeoutError,
                ConnectionResetError, ClientOSError, OSError) as e:
            # ✅ 網路相關錯誤，記錄後重新拋出以觸發重試
            logger.warning(
                "影像上傳 - 網路錯誤 (將重試): KeyName=%s, 類型=%s, 錯誤=%s",
                keyname, type(e).__name__, str(e)
            )
            raise RetryableUploadError(f"網路錯誤: {type(e).__name__} - {str(e)}")
        
        except FileNotFoundError:
            raise  # 檔案不存在，不重試
        
        except Exception as e:
            # 其他未預期錯誤，記錄完整資訊
            logger.error(
                "影像上傳 - 未預期例外: KeyName=%s, 類型=%s, 錯誤=%s",
                keyname, type(e).__name__, str(e),
                exc_info=True  # 包含完整 traceback
            )
            # 將未知錯誤也包裝成可重試（保守策略）
            raise RetryableUploadError(f"未預期錯誤: {type(e).__name__} - {str(e)}")

    async def safe_upload_image(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        collection_id: str,
        keyname: str,
        gps_time: str,
        gps_x: float,
        gps_y: float,
        speed: float,
        img_url: str,
        seq: int
    ) -> bool:
        """安全上傳影像（增強版重試機制）"""
        async with semaphore:
            try:
                # 使用指數退避策略：1s, 2s, 4s, 8s, 16s...（上限 30s）
                upload_with_retry = retry(
                    stop=stop_after_attempt(self.retry_attempts),
                    wait=wait_exponential(
                        multiplier=1,
                        min=self.retry_min_wait,
                        max=self.retry_max_wait
                    ),
                    retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
                    before_sleep=self._log_retry_attempt,  # 重試前記錄
                    retry_error_callback=self._log_retry_exhausted,  # 重試用盡時記錄
                    reraise=False  # 不重新拋出，讓 callback 處理
                )(self._upload_single_image_impl)
                
                result = await upload_with_retry(
                    session, collection_id, keyname, gps_time,
                    gps_x, gps_y, speed, img_url, seq
                )
                return True if result else False
                
            except ImageAlreadyExistsError:
                return True
            except Exception as e:
                # 只有非重試類型的異常才會到這裡
                logger.error(
                    "影像上傳 - 非預期錯誤 (非網路問題): KeyName=%s, 類型=%s, 錯誤=%s",
                    keyname, type(e).__name__, str(e)
                )
                return False

    def _log_retry_attempt(self, retry_state):
        """重試前記錄日誌"""
        exception = retry_state.outcome.exception()
        attempt = retry_state.attempt_number
        wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
        
        # 嘗試從 args 取得 keyname
        keyname = "Unknown"
        if hasattr(retry_state, 'args') and len(retry_state.args) >= 3:
            keyname = retry_state.args[2]
        
        logger.warning(
            "影像上傳 - 重試中: KeyName=%s, 第 %d 次嘗試, 等待 %.1f 秒, 錯誤類型=%s",
            keyname, attempt, wait_time, type(exception).__name__
        )

    def _log_retry_exhausted(self, retry_state):
        """重試用盡時的回調"""
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        
        # 嘗試從 args 取得資訊
        keyname = "Unknown"
        collection_id = "Unknown"
        if hasattr(retry_state, 'args') and len(retry_state.args) >= 3:
            collection_id = retry_state.args[1]
            keyname = retry_state.args[2]
        
        error_msg = str(exception) if exception else "Unknown error"
        error_type = type(exception).__name__ if exception else "Unknown"
        
        # 409 或已存在錯誤視為成功
        if exception and isinstance(exception, ImageAlreadyExistsError):
            logger.info("影像上傳 - 影像已存在，視為成功: KeyName=%s", keyname)
            return True  # 返回成功
        
        logger.error(
            "影像上傳 - 重試用盡: KeyName=%s, 嘗試次數=%d, 錯誤類型=%s, 錯誤=%s",
            keyname, retry_state.attempt_number, error_type, error_msg
        )
        
        # 記錄到失敗追蹤器
        if self.failure_tracker:
            self.failure_tracker.record_upload_failure(
                keyname=keyname,
                collection_id=collection_id,
                error=f"[{error_type}] {error_msg}",
                retry_count=retry_state.attempt_number
            )
            self.failure_tracker.record_collection_failure(collection_id)
        
        return False  # 返回失敗
    
    async def upload_sequence(self, df: pd.DataFrame, collection_id: str) -> Dict[str, int]:
        """上傳完整序列 (整合資源管理與批次清理)"""
        if df.empty:
            return {"successful": 0, "failed": 0, "total": 0}

        # 1. 取得批次配置 (動態或預設)
        sequence_size = len(df)
        if self.seq_handler:
            batch_config = self.seq_handler.get_batch_config(sequence_size)
        else:
            batch_config = {'batch_size': 30, 'batch_delay': 15, 'max_concurrent': 2}
        
        # 資源監控動態調整
        if self.enable_resource_monitor and self.resource_monitor:
            batch_size = await self.resource_monitor.get_dynamic_batch_size(batch_config['batch_size'], sequence_size)
            batch_delay = await self.resource_monitor.get_dynamic_batch_delay(batch_config['batch_delay'])
        else:
            batch_size, batch_delay = batch_config['batch_size'], batch_config['batch_delay']
        
        logger.info("影像上傳 - 序列啟動: %d 張, Batch: %d, 併發限制: %d", sequence_size, batch_size, self.max_concurrent)

        # 2. 分批處理
        batches = [df.iloc[i:i + batch_size] for i in range(0, len(df), batch_size)]
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        total_successful = 0
        total_failed = 0

        # 直接使用注入的 self.session
        for batch_num, batch_df in enumerate(batches, 1):
            logger.info("影像上傳 - 處理批次 %d/%d (資料筆數: %d)", batch_num, len(batches), len(batch_df))
            
            # 資源預檢查
            if self.enable_resource_monitor and self.resource_monitor:
                is_safe, _ = await self.resource_monitor.check_resources()
                if not is_safe:
                    logger.warning("影像上傳 - 系統資源緊張, 等待恢復...")
                    await self.resource_monitor.wait_for_resources(max_wait=300)

            tasks = []
            for index, row in batch_df.iterrows():
                # 欄位完整性檢查
                if pd.isna(row.get('KeyName')) or pd.isna(row.get('GPSTime')):
                    total_failed += 1
                    continue
                
                task = self.safe_upload_image(
                    self.session, semaphore, collection_id,
                    row['KeyName'], row['GPSTime'], row['GPS_X'], row['GPS_Y'],
                    row['speed'], row['url'], int(index) + 1
                )
                tasks.append(task)
            
            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                batch_successful = sum(1 for r in results if r is True)
                total_successful += batch_successful
                total_failed += (len(tasks) - batch_successful)
                
                # 重要優化：顯式釋放任務物件記憶體並觸發 GC
                tasks.clear()
                self.memory_gc.collect_if_needed()
                
                logger.info("影像上傳 - 批次 %d 完成: 成功 %d, 失敗 %d", batch_num, batch_successful, len(results)-batch_successful)

            # 批次延遲
            if batch_num < len(batches):
                await asyncio.sleep(batch_delay)

        self.memory_gc.collect_if_needed(force=True)
        
        return {
            "successful": total_successful,
            "failed": total_failed,
            "total": total_successful + total_failed
        }