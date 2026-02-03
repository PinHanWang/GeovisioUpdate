"""
GeoVisio API 客戶端模組 (重構版)

拆分為兩個主要 Class:
1. GeoVisioAPIClient: 負責 GeoVisio API 的基本操作
2. ImageUploader: 負責影像上傳的複雜邏輯

優化重點:
- 清楚的職責分離
- 統一的錯誤處理
- 完善的日誌記錄
- 支援去重、資源監控、大型序列處理
"""

import json
import os
import io
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiohttp
import aiofiles
import pandas as pd
from aiohttp import ClientTimeout
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()


# ========================================
# 自定義異常
# ========================================
class ImageAlreadyExistsError(Exception):
    """圖片已存在的異常,不應重試"""
    pass


class RetryableUploadError(Exception):
    """可重試的上傳異常"""
    pass


# ========================================
# GeoVisio API 客戶端
# ========================================
class GeoVisioAPIClient:
    """
    GeoVisio API 客戶端
    
    負責與 GeoVisio API 的所有基本互動,
    包括 Collection 管理和基礎的 HTTP 請求。
    
    Attributes:
        base_url: GeoVisio API 基礎 URL
        headers: HTTP 請求標頭
    """
    
    def __init__(self, base_url: str):
        """
        初始化 API 客戶端
        
        Args:
            base_url: GeoVisio API 基礎 URL
        """
        self.base_url = base_url.rstrip('/')
        
        # 修正 Brotli 解碼問題 - 使用 headers 指定接受的編碼
        self.headers = {"Accept-Encoding": "gzip, deflate, identity"}
        
        logger.info("API 客戶端 - 初始化完成,URL: %s", self.base_url)
    
    async def get_all_collections(self) -> Optional[Dict]:
        """
        取得所有 Collection
        
        Returns:
            包含所有 Collection 的字典,失敗時返回 None
        """
        url = f"{self.base_url}/api/collections"
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                logger.debug("API 請求 - 取得所有 Collections")
                
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # 儲存到檔案
                        output_dir = Path('output/geovisio')
                        output_dir.mkdir(parents=True, exist_ok=True)
                        output_file = output_dir / 'all_collections.json'
                        
                        async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
                        
                        logger.info("API 請求 - Collections 已儲存: %s", output_file)
                        return data
                    
                    else:
                        error_text = await response.text()
                        logger.error(
                            "API 請求 - 取得 Collections 失敗,狀態碼: %d, 錯誤: %s",
                            response.status, error_text
                        )
                        return None
            
            except Exception as e:
                logger.error("API 請求 - 取得 Collections 時發生錯誤: %s", str(e))
                return None
    
    async def get_collection_by_id(self, collection_id: str) -> Optional[Dict]:
        """
        取得指定 Collection 的詳細資訊
        
        Args:
            collection_id: Collection ID
            
        Returns:
            Collection 詳細資訊,失敗時返回 None
        """
        url = f"{self.base_url}/api/collections/{collection_id}"
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                logger.debug("API 請求 - 取得 Collection: %s", collection_id)
                
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        # 儲存到檔案
                        output_dir = Path('output/geovisio')
                        output_dir.mkdir(parents=True, exist_ok=True)
                        output_file = output_dir / f'collection_{collection_id}.json'
                        
                        async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
                        
                        logger.info("API 請求 - Collection 已儲存: %s", output_file)
                        return data
                    
                    else:
                        error_text = await response.text()
                        logger.error(
                            "API 請求 - 取得 Collection 失敗,ID: %s, 狀態碼: %d, 錯誤: %s",
                            collection_id, response.status, error_text
                        )
                        return None
            
            except Exception as e:
                logger.error(
                    "API 請求 - 取得 Collection 時發生錯誤,ID: %s, 錯誤: %s",
                    collection_id, str(e)
                )
                return None
    
    async def create_collection(
        self,
        title: str,
        description: str,
        keywords: List[str],
        bbox: Optional[List[float]] = None,
        start_time: Optional[str] = None
    ) -> Optional[str]:
        """
        創建 Collection
        
        Args:
            title: Collection 標題
            description: Collection 描述
            keywords: 關鍵字列表
            bbox: Bounding box (可選)
            start_time: 開始時間 (可選)
            
        Returns:
            創建的 Collection ID,失敗時返回 None
        """
        url = f"{self.base_url}/api/collections"
        
        if keywords is None:
            keywords = ['upload', 'api']
        
        # 建立 extent
        extent = {}
        if bbox:
            extent["spatial"] = {"bbox": [bbox]}
        if start_time is not None:
            extent["temporal"] = {"interval": [[start_time, None]]}
        else:
            extent["temporal"] = {"interval": [[None, None]]}
        
        payload = {
            "title": title,
            "description": description,
            "license": "proprietary",
            "keywords": keywords,
            "extent": extent
        }
        
        async with aiohttp.ClientSession(headers=self.headers) as session:
            try:
                logger.debug("API 請求 - 創建 Collection: %s", title)
                
                async with session.post(url, json=payload) as response:
                    if response.status in [200, 201]:
                        data = await response.json()
                        collection_id = data["id"]
                        logger.info("API 請求 - Collection 已創建: %s", collection_id)
                        return collection_id
                    
                    else:
                        error_text = await response.text()
                        logger.error(
                            "API 請求 - 創建 Collection 失敗,狀態碼: %d, 錯誤: %s",
                            response.status, error_text
                        )
                        return None
            
            except Exception as e:
                logger.error("API 請求 - 創建 Collection 時發生錯誤: %s", str(e))
                return None


# ========================================
# 影像上傳管理器
# ========================================
class ImageUploader:
    """
    影像上傳管理器
    
    負責影像上傳的複雜邏輯,包括:
    - 重試機制
    - 去重檢查
    - 資源監控
    - 批次上傳
    
    Attributes:
        api_client: GeoVisioAPIClient 實例
        dedup_checker: 去重檢查器 (可選)
        resource_monitor: 資源監控器 (可選)
        seq_handler: 序列批次處理器 (可選)
        failure_tracker: 失敗追蹤器 (可選)
    """
    
    def __init__(
        self,
        api_client: GeoVisioAPIClient,
        dedup_checker=None,
        resource_monitor=None,
        seq_handler=None,
        failure_tracker=None
    ):
        """
        初始化上傳管理器
        
        Args:
            api_client: GeoVisioAPIClient 實例
            dedup_checker: 去重檢查器 (可選)
            resource_monitor: 資源監控器 (可選)
            seq_handler: 序列批次處理器 (可選)
            failure_tracker: 失敗追蹤器 (可選)
        """
        self.api_client = api_client
        self.dedup_checker = dedup_checker
        self.resource_monitor = resource_monitor
        self.seq_handler = seq_handler
        self.failure_tracker = failure_tracker
        
        # 環境變數
        self.image_base_path = os.getenv("IMAGE_BASE_PATH")
        self.max_concurrent = int(os.getenv("MAX_CONCURRENT_UPLOADS", "5"))
        self.upload_timeout = int(os.getenv("UPLOAD_TIMEOUT", "60"))
        
        # 功能開關
        self.enable_deduplication = os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true"
        self.enable_md5_check = os.getenv("ENABLE_MD5_CHECK", "true").lower() == "true"
        self.enable_resource_monitor = os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"
        
        logger.info("影像上傳器 - 初始化完成")
        logger.info("影像上傳器 - 並發數: %d, 超時: %d 秒", self.max_concurrent, self.upload_timeout)
    
    def _log_retry_error(self, retry_state):
        """
        重試失敗回調函數
        
        Args:
            retry_state: tenacity 重試狀態
        """
        # 解析參數
        if hasattr(retry_state, 'args') and len(retry_state.args) >= 3:
            collection_id = retry_state.args[1]
            keyname = retry_state.args[2]
        else:
            collection_id = retry_state.kwargs.get('collection_id', 'Unknown')
            keyname = retry_state.kwargs.get('keyname', 'Unknown')
        
        error_msg = str(retry_state.outcome.exception()) if retry_state.outcome and retry_state.outcome.exception() else "Unknown error"
        
        # 409 或已存在錯誤視為成功
        if "409" in error_msg or "already exist" in error_msg.lower() or isinstance(retry_state.outcome.exception(), ImageAlreadyExistsError):
            logger.info(
                "影像上傳 - 影像已存在,視為成功: KeyName=%s, Collection=%s",
                keyname, collection_id
            )
            return
        
        # 記錄失敗
        logger.error(
            "影像上傳 - 重試後仍失敗: KeyName=%s, Collection=%s, 錯誤=%s",
            keyname, collection_id, error_msg
        )
        
        # 記錄到失敗追蹤器
        if self.failure_tracker:
            self.failure_tracker.record_upload_failure(
                keyname=keyname,
                collection_id=collection_id,
                error=error_msg,
                retry_count=retry_state.attempt_number
            )
            self.failure_tracker.record_collection_failure(collection_id)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(2),
        retry=retry_if_exception_type((
            RetryableUploadError,
            asyncio.TimeoutError,
            FileNotFoundError
        ))
    )
    async def upload_single_image(
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
        上傳單張影像 (帶重試)
        
        Args:
            session: aiohttp ClientSession
            collection_id: Collection ID
            keyname: 影像 KeyName
            gps_time: GPS 時間
            gps_x: GPS 經度
            gps_y: GPS 緯度
            speed: 速度
            img_url: 影像 URL
            seq: 序號
            
        Returns:
            上傳成功返回 True
            
        Raises:
            ImageAlreadyExistsError: 影像已存在
            RetryableUploadError: 可重試的錯誤
            FileNotFoundError: 檔案不存在
        """
        # ========================================
        # 1. 去重檢查
        # ========================================
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
                logger.warning("影像上傳 - 去重檢查失敗,KeyName=%s, 錯誤=%s", keyname, str(e))
        
        # ========================================
        # 2. 準備上傳
        # ========================================
        url = f"{self.api_client.base_url}/api/collections/{collection_id}/items"
        
        data = {
            "position": seq,
            "isBlurred": "true",
            "override_capture_time": gps_time,
            "override_latitude": float(gps_y),
            "override_longitude": float(gps_x)
        }
        
        try:
            logger.debug(
                "影像上傳 - 開始: KeyName=%s, Seq=%d, Collection=%s",
                keyname, seq, collection_id
            )
            
            # 讀取影像檔案
            image_path = os.path.join(self.image_base_path, f'{keyname}.jpg')
            
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"影像檔案不存在: {image_path}")
            
            try:
                async with aiofiles.open(image_path, "rb") as f:
                    image_bytes = await f.read()
            except Exception as e:
                logger.error("影像上傳 - 讀取檔案失敗: %s, 錯誤=%s", image_path, str(e))
                raise e
            
            image_data = io.BytesIO(image_bytes)
            
            # 準備 FormData
            form_data = aiohttp.FormData()
            for k, v in data.items():
                form_data.add_field(k, str(v))
            form_data.add_field(
                'picture',
                image_data,
                filename=Path(image_path).name,
                content_type='image/jpeg'
            )
            
            timeout = ClientTimeout(total=self.upload_timeout)
            
            # ========================================
            # 3. 執行上傳
            # ========================================
            async with session.post(url, data=form_data, timeout=timeout) as post_response:
                if post_response.status in [200, 201, 202]:
                    logger.info("影像上傳 - 成功: KeyName=%s", keyname)
                    return True
                
                elif post_response.status == 409:
                    error_text = await post_response.text()
                    logger.warning(
                        "影像上傳 - 影像已存在 (409),視為成功: KeyName=%s",
                        keyname
                    )
                    raise ImageAlreadyExistsError(f"影像已存在: {error_text}")
                
                else:
                    error_text = await post_response.text()
                    error_msg = f"上傳失敗: 狀態碼={post_response.status}, 錯誤={error_text}"
                    logger.warning("影像上傳 - KeyName=%s, %s", keyname, error_msg)
                    raise RetryableUploadError(error_msg)
        
        except ImageAlreadyExistsError:
            return True
        
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.error("影像上傳 - 超時/取消: KeyName=%s, 錯誤=%s", keyname, str(e))
            raise
        
        except FileNotFoundError:
            raise
        
        except Exception as e:
            logger.error("影像上傳 - 例外: KeyName=%s, 錯誤=%s", keyname, str(e))
            raise RetryableUploadError(str(e))
        
        finally:
            if 'image_data' in locals() and image_data is not None:
                image_data.close()
    
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
        """
        安全上傳影像 (帶並發控制)
        
        Args:
            session: aiohttp ClientSession
            semaphore: 並發控制信號量
            collection_id: Collection ID
            keyname: 影像 KeyName
            gps_time: GPS 時間
            gps_x: GPS 經度
            gps_y: GPS 緯度
            speed: 速度
            img_url: 影像 URL
            seq: 序號
            
        Returns:
            上傳成功返回 True,失敗返回 False
        """
        async with semaphore:
            try:
                # 使用重試機制的上傳,並傳遞 retry_error_callback
                upload_method = retry(
                    stop=stop_after_attempt(3),
                    wait=wait_fixed(2),
                    retry=retry_if_exception_type((
                        RetryableUploadError,
                        asyncio.TimeoutError,
                        FileNotFoundError
                    )),
                    retry_error_callback=self._log_retry_error
                )(self.upload_single_image)
                
                result = await upload_method(
                    session, collection_id, keyname, gps_time,
                    gps_x, gps_y, speed, img_url, seq
                )
                return True if result else False
            
            except Exception as e:
                logger.error(
                    "影像上傳 - 所有重試後仍失敗: KeyName=%s, 錯誤=%s",
                    keyname, str(e)
                )
                return False
    
    async def upload_sequence(
        self,
        df: pd.DataFrame,
        collection_id: str
    ) -> Dict[str, int]:
        """
        上傳完整序列 (整合資源監控和大型序列處理)
        
        Args:
            df: 包含影像資訊的 DataFrame
            collection_id: Collection ID
            
        Returns:
            上傳結果統計 {successful, failed, total}
        """
        if df.empty:
            logger.warning("影像上傳 - DataFrame 為空,無影像需上傳")
            return {"successful": 0, "failed": 0, "total": 0}
        
        # ========================================
        # 1. 大型序列處理
        # ========================================
        sequence_size = len(df)
        
        if self.seq_handler:
            batch_config = self.seq_handler.get_batch_config(sequence_size)
        else:
            # 預設配置
            batch_config = {
                'batch_size': 30,
                'batch_delay': 15,
                'max_concurrent': 2
            }
        
        base_batch_size = batch_config['batch_size']
        base_batch_delay = batch_config['batch_delay']
        max_concurrent = batch_config['max_concurrent']
        
        # 資源監控動態調整
        if self.enable_resource_monitor and self.resource_monitor:
            batch_size = await self.resource_monitor.get_dynamic_batch_size(
                base_batch_size,
                sequence_size
            )
            batch_delay = await self.resource_monitor.get_dynamic_batch_delay(
                base_batch_delay
            )
        else:
            batch_size = base_batch_size
            batch_delay = base_batch_delay
        
        logger.info(
            "影像上傳 - 序列大小: %d 張, Batch: %d, Delay: %d 秒, 並發: %d",
            sequence_size, batch_size, batch_delay, max_concurrent
        )
        
        # ========================================
        # 2. 分批處理
        # ========================================
        if self.seq_handler:
            batches = self.seq_handler.split_into_batches(df, batch_size)
        else:
            # 手動分批
            batches = [df.iloc[i:i + batch_size] for i in range(0, len(df), batch_size)]
        
        semaphore = asyncio.Semaphore(max_concurrent)
        timeout = ClientTimeout(total=self.upload_timeout * 2)
        
        total_successful = 0
        total_failed = 0
        
        headers = {"Accept-Encoding": "gzip, deflate, identity"}
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            for batch_num, batch_df in enumerate(batches, 1):
                logger.info("影像上傳 - 處理批次: %d/%d", batch_num, len(batches))
                
                # ========================================
                # 3. 資源檢查
                # ========================================
                if self.enable_resource_monitor and self.resource_monitor:
                    is_safe, stats = await self.resource_monitor.check_resources()
                    
                    if not is_safe:
                        logger.warning(
                            "影像上傳 - 資源不足 (Job Queue: %d),等待恢復...",
                            stats['job_queue_count']
                        )
                        success = await self.resource_monitor.wait_for_resources(max_wait=300)
                        
                        if not success:
                            logger.error("影像上傳 - 資源等待超時,繼續處理但失敗率可能較高")
                
                # ========================================
                # 4. 批次上傳
                # ========================================
                tasks = []
                
                for index, row in batch_df.iterrows():
                    required_columns = ['KeyName', 'GPSTime', 'GPS_X', 'GPS_Y', 'speed', 'url']
                    missing_columns = [
                        col for col in required_columns if col not in row or pd.isna(row[col])
                    ]
                    
                    if missing_columns:
                        logger.warning(
                            "影像上傳 - 跳過缺少欄位的行: %s",
                            ', '.join(missing_columns)
                        )
                        total_failed += 1
                        continue
                    
                    keyname = row['KeyName']
                    gps_time = row['GPSTime']
                    gps_x = row['GPS_X']
                    gps_y = row['GPS_Y']
                    speed = row['speed']
                    img_url = row['url']
                    seq = int(index) + 1
                    
                    task = self.safe_upload_image(
                        session, semaphore, collection_id, keyname, gps_time,
                        gps_x, gps_y, speed, img_url, seq
                    )
                    tasks.append(task)
                
                if tasks:
                    try:
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        
                        batch_successful = sum(1 for r in results if r is True)
                        batch_failed = len(results) - batch_successful
                        
                        total_successful += batch_successful
                        total_failed += batch_failed
                        
                        logger.info(
                            "影像上傳 - 批次完成: %d, 成功: %d, 失敗: %d",
                            batch_num, batch_successful, batch_failed
                        )
                    
                    except Exception as e:
                        logger.error("影像上傳 - 批次錯誤: %d, 錯誤=%s", batch_num, str(e))
                        total_failed += len(tasks)
                
                # 批次間延遲
                if batch_num < len(batches):
                    logger.debug("影像上傳 - 批次延遲: %d 秒", batch_delay)
                    await asyncio.sleep(batch_delay)
        
        # ========================================
        # 5. 返回結果
        # ========================================
        logger.info(
            "影像上傳 - 序列完成: 成功=%d, 失敗=%d, 總計=%d",
            total_successful, total_failed, total_successful + total_failed
        )
        
        return {
            "successful": total_successful,
            "failed": total_failed,
            "total": total_successful + total_failed
        }


# ========================================
# 向後相容函數 (保留舊的函數接口)
# ========================================
async def create_collection(title, description, keywords, bbox=None, start_time=None):
    """向後相容的 create_collection 函數"""
    client = GeoVisioAPIClient(base_url=os.getenv("TMS_GEOVISIO_URL"))
    return await client.create_collection(title, description, keywords, bbox, start_time)


async def get_all_collections():
    """向後相容的 get_all_collections 函數"""
    client = GeoVisioAPIClient(base_url=os.getenv("TMS_GEOVISIO_URL"))
    return await client.get_all_collections()


async def get_collection_by_items_id(collection_id):
    """向後相容的 get_collection_by_items_id 函數"""
    client = GeoVisioAPIClient(base_url=os.getenv("TMS_GEOVISIO_URL"))
    return await client.get_collection_by_id(collection_id)


async def upload_images_to_geovisio(df, collection_id):
    """向後相容的 upload_images_to_geovisio 函數"""
    # 這裡需要從外部傳入依賴,暫時用 None
    from src.module.TMSUpdate.optmization.duplicate_checker import dedup_checker
    from src.module.TMSUpdate.optmization.resource_monitor import simple_resource_monitor
    from src.module.TMSUpdate.optmization.sequence_batch_handler import large_seq_handler
    
    client = GeoVisioAPIClient(base_url=os.getenv("TMS_GEOVISIO_URL"))
    uploader = ImageUploader(
        api_client=client,
        dedup_checker=dedup_checker,
        resource_monitor=simple_resource_monitor,
        seq_handler=large_seq_handler
    )
    return await uploader.upload_sequence(df, collection_id)