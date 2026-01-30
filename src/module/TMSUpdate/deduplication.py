# src/module/TMSUpdate/deduplication_fixed.py
"""
修正後的去重檢查模組
支援:
1. KeyName 檢查 (資料庫)
2. MD5 檢查 (資料庫)
3. URL 下載計算 MD5 (當本地檔案不存在時)
"""

import hashlib
import os
import logging
from pathlib import Path
from typing import Optional, Set, Tuple
import aiohttp
import asyncpg
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()
IMAGE_BASE_PATH = os.getenv("IMAGE_BASE_PATH")


class DeduplicationChecker:
    """去重檢查器 - 支援本地檔案和遠端 URL"""
    
    def __init__(self, db_url: Optional[str] = None):
        """
        初始化去重檢查器
        
        Args:
            db_url: PostgreSQL 連線字串
        """
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.db_pool = None
        
        # 本地快取
        self.md5_cache: Set[str] = set()
        self.keyname_cache: Set[str] = set()
        
        # 統計
        self.stats = {
            'checked': 0,
            'duplicates_md5': 0,
            'duplicates_keyname': 0,
            'cache_hits': 0,
            'md5_calculated': 0,
            'md5_skipped': 0
        }
    
    async def initialize(self):
        """初始化資料庫連線池"""
        if self.db_url:
            try:
                self.db_pool = await asyncpg.create_pool(
                    self.db_url,
                    min_size=2,
                    max_size=5,
                    timeout=30
                )
                logger.info("✅ 去重檢查器初始化成功")
                
                # 載入現有的 KeyName 到快取
                await self._load_existing_keynames()
                
            except Exception as e:
                logger.warning(f"⚠️  無法連線到資料庫,去重功能將被停用: {e}")
                self.db_pool = None
        else:
            logger.warning("⚠️  未提供資料庫連線,去重功能將被停用")
    
    async def close(self):
        """關閉資料庫連線池"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("✅ 去重檢查器已關閉")
    
    async def _load_existing_keynames(self, limit: int = 50000):
        """
        載入現有的 KeyName 到快取
        
        Args:
            limit: 載入的最大數量
        """
        if not self.db_pool:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                # 載入最近的 originalFileName
                # 使用子查詢來處理 DISTINCT + ORDER BY
                records = await conn.fetch(
                    """
                    SELECT DISTINCT filename
                    FROM (
                        SELECT 
                            metadata->>'originalFileName' as filename,
                            inserted_at
                        FROM pictures 
                        WHERE metadata->>'originalFileName' IS NOT NULL
                        ORDER BY inserted_at DESC
                        LIMIT $1 * 2
                    ) sub
                    LIMIT $1
                    """,
                    limit
                )
                
                # 儲存完整檔名到快取
                self.keyname_cache = {r['filename'] for r in records if r['filename']}
                logger.info(f"📦 載入 {len(self.keyname_cache)} 個檔名到快取")
                
        except Exception as e:
            logger.error(f"❌ 載入檔名快取失敗: {e}")
    
    @staticmethod
    def calculate_md5_from_bytes(data: bytes) -> str:
        """
        從 bytes 計算 MD5
        
        Args:
            data: 檔案內容
            
        Returns:
            MD5 字串
        """
        return hashlib.md5(data).hexdigest()
    
    @staticmethod
    def calculate_md5_from_file(file_path: str) -> str:
        """
        從本地檔案計算 MD5
        
        Args:
            file_path: 檔案路徑
            
        Returns:
            MD5 字串
        """
        md5_hash = hashlib.md5()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        
        return md5_hash.hexdigest()
    
    async def calculate_md5_from_url(
        self, 
        url: str, 
        session: Optional[aiohttp.ClientSession] = None
    ) -> Optional[str]:
        """
        從 URL 下載並計算 MD5
        
        Args:
            url: 影像 URL
            session: 可選的 aiohttp session
            
        Returns:
            MD5 字串,失敗時返回 None
        """
        close_session = False
        
        try:
            if session is None:
                session = aiohttp.ClientSession()
                close_session = True
            
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    md5 = self.calculate_md5_from_bytes(data)
                    logger.debug(f"✅ 從 URL 計算 MD5: {md5[:8]}... (大小: {len(data)} bytes)")
                    return md5
                else:
                    logger.error(f"❌ 無法下載 URL: {url} (HTTP {resp.status})")
                    return None
        
        except Exception as e:
            logger.error(f"❌ 從 URL 計算 MD5 失敗: {e}")
            return None
        
        finally:
            if close_session and session:
                await session.close()
    
    async def check_md5_exists(self, md5: str) -> bool:
        """
        檢查 MD5 是否已存在
        
        Args:
            md5: MD5 字串
            
        Returns:
            是否已存在
        """
        if not md5:
            return False
        
        # 1. 先檢查快取
        if md5 in self.md5_cache:
            self.stats['cache_hits'] += 1
            return True
        
        # 2. 查詢資料庫
        if not self.db_pool:
            return False
        
        try:
            async with self.db_pool.acquire() as conn:
                exists = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM pictures 
                        WHERE original_content_md5 = $1::uuid
                    )
                    """,
                    md5
                )
                
                if exists:
                    # 加入快取
                    self.md5_cache.add(md5)
                    return True
                
                return False
                
        except Exception as e:
            logger.error(f"❌ 檢查 MD5 時發生錯誤: {e}")
            return False
    
    async def check_keyname_exists(self, keyname: str) -> bool:
        """
        檢查 keyname 是否已存在
        
        Args:
            keyname: 檔案名稱 (不含副檔名,例如: 20250618093828079_S9D3DPLAR)
            
        Returns:
            是否已存在
        """
        if not keyname:
            return False
        
        # 加上 .jpg 副檔名
        filename = f"{keyname}.jpg"
        
        # 1. 先檢查快取
        if filename in self.keyname_cache:
            self.stats['cache_hits'] += 1
            logger.debug(f"🎯 檔名快取命中: {filename}")
            return True
        
        # 2. 查詢資料庫
        if not self.db_pool:
            return False
        
        try:
            async with self.db_pool.acquire() as conn:
                exists = await conn.fetchval(
                    """
                    SELECT EXISTS(
                        SELECT 1 FROM pictures 
                        WHERE metadata->>'originalFileName' = $1
                    )
                    """,
                    filename
                )
                
                if exists:
                    # 加入快取
                    self.keyname_cache.add(filename)
                    logger.debug(f"🎯 檔名資料庫命中: {filename}")
                    return True
                
                logger.debug(f"✨ 檔名不存在: {filename}")
                return False
                
        except Exception as e:
            logger.error(f"❌ 檢查 keyname 時發生錯誤: {e}")
            return False
    
    async def should_skip_upload(
        self, 
        keyname: str,
        img_url: Optional[str] = None,
        check_md5: bool = True,
        session: Optional[aiohttp.ClientSession] = None
    ) -> Tuple[bool, str]:
        """
        判斷是否應該跳過上傳
        
        Args:
            keyname: 檔案名稱 (不含副檔名,例如: 20250618093828079_S9D3DPLAR)
            img_url: 影像 URL (用於下載計算 MD5)
            check_md5: 是否檢查 MD5
            session: 可選的 aiohttp session
            
        Returns:
            (should_skip, reason): 是否跳過, 跳過原因
        """
        self.stats['checked'] += 1
        
        # ========================================
        # 1. 檢查 originalFileName (最快,優先)
        # ========================================
        if await self.check_keyname_exists(keyname):
            self.stats['duplicates_keyname'] += 1
            return (True, f"檔名已存在: {keyname}.jpg")
        
        # ========================================
        # 2. 檢查 MD5 (可選)
        # ========================================
        if check_md5:
            md5 = None
            
            # 2.1 嘗試從本地檔案計算 MD5
            if IMAGE_BASE_PATH:
                image_path = os.path.join(IMAGE_BASE_PATH, f"{keyname}.jpg")
                
                if os.path.exists(image_path):
                    try:
                        md5 = self.calculate_md5_from_file(image_path)
                        self.stats['md5_calculated'] += 1
                        logger.debug(f"📁 從本地檔案計算 MD5: {keyname}")
                    except Exception as e:
                        logger.error(f"❌ 計算本地檔案 MD5 失敗 ({keyname}): {e}")
            
            # 2.2 如果本地檔案不存在,嘗試從 URL 下載計算
            if md5 is None and img_url:
                logger.debug(f"🌐 嘗試從 URL 計算 MD5: {keyname}")
                md5 = await self.calculate_md5_from_url(img_url, session)
                
                if md5:
                    self.stats['md5_calculated'] += 1
            
            # 2.3 檢查 MD5 是否存在
            if md5:
                if await self.check_md5_exists(md5):
                    self.stats['duplicates_md5'] += 1
                    return (True, f"MD5 重複: {md5[:8]}...")
            else:
                # MD5 計算失敗,記錄但不阻止上傳
                self.stats['md5_skipped'] += 1
                logger.warning(f"⚠️  無法計算 MD5: {keyname} (但仍會繼續上傳)")
        
        # ========================================
        # 3. 不重複,可以上傳
        # ========================================
        return (False, "可上傳")
    
    def get_stats(self) -> dict:
        """取得統計資訊"""
        return {
            **self.stats,
            'cache_size_md5': len(self.md5_cache),
            'cache_size_keyname': len(self.keyname_cache)
        }
    
    def print_stats(self):
        """列印統計資訊"""
        stats = self.get_stats()
        logger.info("=" * 60)
        logger.info("📊 去重檢查統計")
        logger.info("=" * 60)
        logger.info(f"檢查總數:        {stats['checked']}")
        logger.info(f"KeyName 重複:    {stats['duplicates_keyname']}")
        logger.info(f"MD5 重複:        {stats['duplicates_md5']}")
        logger.info(f"快取命中:        {stats['cache_hits']}")
        logger.info(f"MD5 已計算:      {stats['md5_calculated']}")
        logger.info(f"MD5 跳過:        {stats['md5_skipped']}")
        logger.info(f"快取大小 (MD5):  {stats['cache_size_md5']}")
        logger.info(f"快取大小 (Key):  {stats['cache_size_keyname']}")
        logger.info("=" * 60)


# 全域實例
dedup_checker = DeduplicationChecker()


if __name__ == "__main__":
    import asyncio
    
    async def test():
        checker = DeduplicationChecker()
        await checker.initialize()
        
        # 測試 1: 檢查 KeyName
        keyname = "20250618093828079_S9D3DPLAR"
        url = "https://roadapp.nat.gov.tw/CCImage/TTU11402/S9CR0PKTG/20250618093828079_S9D3DPLAR.jpg"
        
        print(f"\n測試 KeyName: {keyname}")
        should_skip, reason = await checker.should_skip_upload(
            keyname, 
            img_url=url,
            check_md5=True
        )
        
        print(f"是否跳過: {should_skip}")
        print(f"原因: {reason}")
        
        # 測試 2: 再次檢查 (測試快取)
        print(f"\n再次測試 (應該使用快取):")
        should_skip, reason = await checker.should_skip_upload(keyname)
        print(f"是否跳過: {should_skip}")
        print(f"原因: {reason}")
        
        # 顯示統計
        checker.print_stats()
        
        await checker.close()
    
    asyncio.run(test())