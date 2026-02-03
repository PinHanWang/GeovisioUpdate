"""
GeoVisio API 客戶端模組 (重構版)

負責 GeoVisio API 的基本操作,包括 Collection 管理和基礎的 HTTP 請求。

優化重點:
- 清楚的職責分離
- 統一的錯誤處理
- 完善的日誌記錄
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict
import aiohttp
import aiofiles
from dotenv import load_dotenv

# 從獨立模組導入異常類別 (避免循環 import)
try:
    from src.module.TMSUpdate.api.exceptions import (
        ImageAlreadyExistsError,
        RetryableUploadError
    )
except ImportError:
    from .exceptions import ImageAlreadyExistsError, RetryableUploadError

logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()


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
    # 延遲導入避免循環 import
    try:
        from src.module.TMSUpdate.api.image_uploader import ImageUploader
        from src.module.TMSUpdate.optimization.duplicate_checker import get_duplicate_checker
        from src.module.TMSUpdate.optimization.resource_monitor import simple_resource_monitor
        from src.module.TMSUpdate.optimization.sequence_batch_handler import large_seq_handler
    except ImportError:
        from .image_uploader import ImageUploader
        from optimization.duplicate_checker import get_duplicate_checker
        from optimization.resource_monitor import simple_resource_monitor
        from optimization.sequence_batch_handler import large_seq_handler
    
    dedup_checker = get_duplicate_checker()
    
    client = GeoVisioAPIClient(base_url=os.getenv("TMS_GEOVISIO_URL"))
    uploader = ImageUploader(
        api_client=client,
        dedup_checker=dedup_checker,
        resource_monitor=simple_resource_monitor,
        seq_handler=large_seq_handler
    )
    return await uploader.upload_sequence(df, collection_id)
