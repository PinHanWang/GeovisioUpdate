"""
GeoVisio API 客戶端模組 (重構優化版)

負責 GeoVisio API 的基本操作。
優化重點：
- 支援外部 Session 注入，解決連線池資源洩漏。
- 統一請求處理機制。
- 強化資源清理與錯誤日誌。
"""

import json
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import aiohttp
import aiofiles
from dotenv import load_dotenv

# 從獨立模組導入異常類別
try:
    from src.module.TMSUpdate.api.exceptions import (
        ImageAlreadyExistsError,
        RetryableUploadError
    )
except ImportError:
    from .exceptions import ImageAlreadyExistsError, RetryableUploadError

logger = logging.getLogger(__name__)
load_dotenv()

# ========================================
# GeoVisio API 客戶端
# ========================================
class GeoVisioAPIClient:
    """
    GeoVisio API 客戶端
    
    Attributes:
        base_url: GeoVisio API 基礎 URL
        session: 外部傳入的 aiohttp.ClientSession 實例
    """
    
    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        """
        初始化 API 客戶端
        
        Args:
            base_url: GeoVisio API 基礎 URL
            session: aiohttp 連線會話 (建議由 Pipeline 統一管理生命週期)
        """
        self.base_url = base_url.rstrip('/')
        self.session = session
        
        # 修正編碼問題
        self.headers = {"Accept-Encoding": "gzip, deflate, identity"}
        logger.info("API 客戶端 - 初始化完成, URL: %s", self.base_url)

    async def _request(self, method: str, path: str, **kwargs) -> Optional[Any]:
        """
        統一請求處理封裝
        """
        url = f"{self.base_url}{path}"
        # 合併全域 headers
        kwargs['headers'] = {**self.headers, **kwargs.get('headers', {})}
        
        try:
            async with self.session.request(method, url, **kwargs) as response:
                if response.status in [200, 201, 202]:
                    return await response.json()
                else:
                    error_text = await response.text()
                    logger.error(
                        "API 請求失敗 - Method: %s, Path: %s, Status: %d, Error: %s",
                        method, path, response.status, error_text
                    )
                    return None
        except Exception as e:
            logger.error("API 請求發生異常 - Path: %s, Error: %s", path, str(e))
            return None

    async def _save_json_output(self, data: Dict, filename: str):
        """儲存 API 回應到檔案 (輔助方法)"""
        try:
            output_dir = Path('output/geovisio')
            output_dir.mkdir(parents=True, exist_ok=True)
            output_file = output_dir / filename
            
            async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=4))
            logger.debug("API 數據已快取至: %s", output_file)
        except Exception as e:
            logger.warning("無法儲存 API 快取檔案: %s", str(e))

    async def get_all_collections(self) -> Optional[Dict]:
        """取得所有 Collection"""
        data = await self._request("GET", "/api/collections")
        if data:
            await self._save_json_output(data, 'all_collections.json')
        return data
    
    async def get_collection_by_id(self, collection_id: str) -> Optional[Dict]:
        """取得指定 Collection 的詳細資訊"""
        data = await self._request("GET", f"/api/collections/{collection_id}")
        if data:
            await self._save_json_output(data, f'collection_{collection_id}.json')
        return data
    
    async def create_collection(
        self,
        title: str,
        description: str,
        keywords: List[str],
        bbox: Optional[List[float]] = None,
        start_time: Optional[str] = None
    ) -> Optional[str]:
        """創建 Collection"""
        if keywords is None:
            keywords = ['upload', 'api']
        
        # 建立 extent 結構
        extent = {
            "spatial": {"bbox": [bbox]} if bbox else None,
            "temporal": {"interval": [[start_time, None]]} if start_time else {"interval": [[None, None]]}
        }
        # 移除 None 值
        extent = {k: v for k, v in extent.items() if v is not None}
        
        payload = {
            "title": title,
            "description": description,
            "license": "proprietary",
            "keywords": keywords,
            "extent": extent
        }
        
        data = await self._request("POST", "/api/collections", json=payload)
        if data and "id" in data:
            logger.info("API 請求 - Collection 已創建: %s", data["id"])
            return data["id"]
        return None

# ========================================
# 向後相容函數 (修正：這些函數現在應僅作為快速 Entry Point，不建議高頻使用)
# ========================================

async def _get_compat_client():
    """內部輔助：建立一個臨時的 Client (注意：這會產生一次性 Session)"""
    session = aiohttp.ClientSession()
    client = GeoVisioAPIClient(base_url=os.getenv("TMS_GEOVISIO_URL"), session=session)
    return client, session

async def create_collection(title, description, keywords, bbox=None, start_time=None):
    client, session = await _get_compat_client()
    try:
        return await client.create_collection(title, description, keywords, bbox, start_time)
    finally:
        await session.close()

async def get_all_collections():
    client, session = await _get_compat_client()
    try:
        return await client.get_all_collections()
    finally:
        await session.close()

async def get_collection_by_items_id(collection_id):
    client, session = await _get_compat_client()
    try:
        return await client.get_collection_by_id(collection_id)
    finally:
        await session.close()
