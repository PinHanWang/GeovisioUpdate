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

# 從獨立模組導入異常類別
try:
    from src.module.TMSUpdate.config.settings import Settings
except ImportError:
    from ..config.settings import Settings

try:
    from src.module.TMSUpdate.api.exceptions import (
        ImageAlreadyExistsError,
        RetryableUploadError
    )
except ImportError:
    from .exceptions import ImageAlreadyExistsError, RetryableUploadError

logger = logging.getLogger(__name__)

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
    
    async def health_check(self) -> bool:
        """檢查 GeoVisio API 健康狀態"""
        try:
            async with self.session.get(
                f"{self.base_url}/health",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning("API 健康檢查失敗: %s", str(e))
            return False

    async def get_collection_items(
        self,
        collection_id: str,
        limit: int = 10000
    ) -> List[Dict]:
        """
        取得 Collection 內所有 Items
        
        Args:
            collection_id: Collection ID
            limit: 最大數量
            
        Returns:
            Items 列表
        """
        all_items = []
        
        try:
            # GeoVisio 可能有分頁，需要處理
            path = f"/api/collections/{collection_id}/items"
            params = {"limit": min(limit, 1000)}  # 每次最多取 1000
            
            while True:
                data = await self._request("GET", path, params=params)
                
                if not data:
                    break
                
                items = data.get('features', [])
                all_items.extend(items)
                
                # 檢查是否有下一頁
                links = data.get('links', [])
                next_link = next((l for l in links if l.get('rel') == 'next'), None)
                
                if next_link and len(all_items) < limit:
                    # 取得下一頁的參數
                    from urllib.parse import urlparse, parse_qs
                    next_url = next_link.get('href', '')
                    if next_url:
                        parsed = urlparse(next_url)
                        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
                    else:
                        break
                else:
                    break
            
            logger.debug("API 查詢 - Collection %s 共有 %d 個 items", collection_id, len(all_items))
            return all_items
            
        except Exception as e:
            logger.error("API 查詢 - 取得 items 失敗: %s", str(e))
            return []

    async def get_uploaded_keynames(self, collection_id: str) -> set:
        """
        取得 Collection 內已上傳的 KeyName 集合
        
        用於續傳檢查：取得該 Collection 內已有的影像清單。
        
        Args:
            collection_id: Collection ID
            
        Returns:
            KeyName 集合 (set)
        """
        items = await self.get_collection_items(collection_id)
        
        keynames = set()
        for item in items:
            # 從 properties.original_file:name 取得檔名
            properties = item.get('properties', {})
            original_name = properties.get('original_file:name', '')
            
            if original_name:
                # 移除 .jpg 副檔名
                keyname = original_name.replace('.jpg', '').replace('.JPG', '')
                keynames.add(keyname)
        
        logger.info("API 查詢 - Collection %s 已有 %d 張影像", collection_id, len(keynames))
        return keynames

    async def find_collection_by_sequence(
        self,
        seq_id: str,
        collection_date: str
    ) -> Optional[Dict]:
        """
        根據 Sequence ID 和日期搜尋對應的 Collection
        
        用於續傳：在 API 中搜尋包含特定 Sequence ID 和日期的 Collection。
        
        Args:
            seq_id: 序列 ID
            collection_date: 日期字串 (e.g., '2025-06-01')
            
        Returns:
            Collection 字典，或 None
        """
        try:
            data = await self.get_all_collections()
            if not data:
                return None
            
            collections = data.get('collections', [])
            
            # 在 keywords 中搜尋包含 Sequence ID 和日期的 Collection
            for col in collections:
                keywords = col.get('keywords', [])
                keywords_text = ' '.join(keywords)
                
                # 檢查是否包含 Sequence ID 和日期
                # keywords 格式範例: "交工案第一分案資料蒸集(10米以上道路) Date: 2025-06-01; Sequence ID: 36"
                if f"Sequence ID: {seq_id}" in keywords_text or f"Sequence ID:{seq_id}" in keywords_text:
                    if str(collection_date) in keywords_text:
                        logger.info(
                            "API 查詢 - 找到匹配 Collection: ID=%s, SeqID=%s, Date=%s",
                            col.get('id'), seq_id, collection_date
                        )
                        return col
            
            logger.debug(
                "API 查詢 - 未找到匹配的 Collection: SeqID=%s, Date=%s",
                seq_id, collection_date
            )
            return None
            
        except Exception as e:
            logger.error("API 查詢 - 搜尋 Collection 失敗: %s", str(e))
            return None

# ========================================
# 向後相容函數 (修正：這些函數現在應僅作為快速 Entry Point，不建議高頻使用)
# ========================================

async def _get_compat_client():
    """內部輔助：建立一個臨時的 Client"""
    session = aiohttp.ClientSession()
    client = GeoVisioAPIClient(
        base_url=Settings.TMS_GEOVISIO_URL,  # 使用 Settings
        session=session
    )
    return client, session

# import warnings

# async def create_collection(title, description, keywords, bbox=None, start_time=None):
#     """向後相容函數 - 建議使用 GeoVisioAPIClient 類別"""
#     warnings.warn(
#         "create_collection() 將在未來版本移除，請使用 GeoVisioAPIClient 類別",
#         DeprecationWarning,
#         stacklevel=2

#     )
#     client, session = await _get_compat_client()
#     try:
#         return await client.create_collection(title, description, keywords, bbox, start_time)
#     finally:
#         await session.close()

# async def get_all_collections():
#     client, session = await _get_compat_client()
#     try:
#         return await client.get_all_collections()
#     finally:
#         await session.close()

# async def get_collection_by_items_id(collection_id):
#     client, session = await _get_compat_client()
#     try:
#         return await client.get_collection_by_id(collection_id)
#     finally:
#         await session.close()
