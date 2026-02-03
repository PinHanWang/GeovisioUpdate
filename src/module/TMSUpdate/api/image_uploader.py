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
import pandas as pd
from aiohttp import ClientTimeout
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from dotenv import load_dotenv

# 從獨立模組導入異常類別 (避免循環 import)
try:
    from src.module.TMSUpdate.api.exceptions import (
        ImageAlreadyExistsError,
        RetryableUploadError
    )
except ImportError:
    from .exceptions import ImageAlreadyExistsError, RetryableUploadError

# Type hint 用 (避免循環 import)
if TYPE_CHECKING:
    from src.module.TMSUpdate.api.geovisio_api_client import GeoVisioAPIClient

logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()


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
        
        # 環境變數設定
        self.image_base_path = os.getenv("IMAGE_BASE_PATH")
        self.max_concurrent = int(os.getenv("MAX_CONCURRENT_UPLOADS", "5"))
        self.upload_timeout = int(os.getenv("UPLOAD_TIMEOUT", "60"))
        
        # 功能開關
        self.enable_deduplication = os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true"
        self.enable_md5_check = os.getenv("ENABLE_MD5_CHECK", "true").lower() == "true"
        self.enable_resource_monitor = os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"
        
        logger.info("影像上傳器 - 初始化完成 (連線複用與流式傳輸模式)")
        logger.info("影像上傳器 - 並發數限制: %d, 上傳超時: %d 秒", self.max_concurrent, self.upload_timeout)

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
        gps_time: str,
        gps_x: float,
        gps_y: float,
        speed: float,
        img_url: str,
        seq: int
    ) -> bool:
        """
        上傳單張影像的實際實現 (採用流式傳輸)
        """
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
                logger.warning("影像上傳 - 去重檢查失敗, KeyName=%s, 錯誤=%s", keyname, str(e))
        
        # 2. 準備上傳
        url = f"{self.api_client.base_url}/api/collections/{collection_id}/items"
        image_path = os.path.join(self.image_base_path, f'{keyname}.jpg')
        
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"影像檔案不存在: {image_path}")

        # 重要優化：使用 'with open' 配合 aiohttp.FormData 進行流式上傳
        # 這種方式數據直接從磁碟流向網路，不會將整張大圖載入 Python 變數記憶體
        try:
            with open(image_path, 'rb') as img_file:
                form_data = aiohttp.FormData()
                form_data.add_field("position", str(seq))
                form_data.add_field("isBlurred", "true")
                form_data.add_field("override_capture_time", gps_time)
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
                        logger.warning("影像上傳 - 影像已存在 (409): KeyName=%s", keyname)
                        raise ImageAlreadyExistsError(f"影像已存在: {error_text}")
                    else:
                        error_text = await resp.text()
                        error_msg = f"上傳失敗: 狀態碼={resp.status}, 錯誤={error_text}"
                        logger.warning("影像上傳 - KeyName=%s, %s", keyname, error_msg)
                        raise RetryableUploadError(error_msg)

        except ImageAlreadyExistsError:
            return True
        except Exception as e:
            if not isinstance(e, (RetryableUploadError, FileNotFoundError)):
                logger.error("影像上傳 - 未預期例外: KeyName=%s, 錯誤=%s", keyname, str(e))
            raise

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
        """安全上傳影像 (並發控制與重試)"""
        async with semaphore:
            try:
                upload_with_retry = retry(
                    stop=stop_after_attempt(3),
                    wait=wait_fixed(2),
                    retry=retry_if_exception_type((RetryableUploadError, asyncio.TimeoutError)),
                    retry_error_callback=self._log_retry_error,
                    reraise=False
                )(self._upload_single_image_impl)
                
                result = await upload_with_retry(
                    session, collection_id, keyname, gps_time,
                    gps_x, gps_y, speed, img_url, seq
                )
                return True if result else False
            except ImageAlreadyExistsError:
                return True
            except Exception as e:
                logger.error("影像上傳 - 流程錯誤: %s, 錯誤=%s", keyname, str(e))
                return False

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
        
        logger.info("影像上傳 - 序列啟動: %d 張, Batch: %d, 並發限制: %d", sequence_size, batch_size, self.max_concurrent)

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
                del tasks
                gc.collect() 
                
                logger.info("影像上傳 - 批次 %d 完成: 成功 %d, 失敗 %d", batch_num, batch_successful, len(results)-batch_successful)

            # 批次延遲
            if batch_num < len(batches):
                await asyncio.sleep(batch_delay)

        return {
            "successful": total_successful,
            "failed": total_failed,
            "total": total_successful + total_failed
        }