"""
重複性檢查模組 (重構優化版)

功能:
1. KeyName 檢查 (基於 metadata->>'originalFileName')
2. MD5 檢查 (基於 original_content_md5)
3. 支援本地檔案和遠端 URL 的 MD5 計算
4. 快取機制提升性能

優化重點:
- 統一中文日誌訊息
- 清楚的日誌等級分類
- 移除過多的 emoji
- 完善的 docstring
"""

import hashlib
import os
import asyncio
import logging
from pathlib import Path
from collections import OrderedDict
from typing import Optional, Set, Tuple
import aiohttp
import asyncpg
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

# 導入設定
try:
    from src.config.settings import Settings
except ImportError:
    from ..config.settings import Settings

# 取得日誌器
logger = logging.getLogger(__name__)

# 載入環境變數
IMAGE_BASE_PATH = Settings.IMAGE_BASE_PATH

# MD5 下載時視為暫時性、值得重試的網路錯誤
MD5_DOWNLOAD_RETRYABLE_EXCEPTIONS = (
    aiohttp.ServerDisconnectedError,
    aiohttp.ClientConnectorError,
    aiohttp.ServerTimeoutError,
    aiohttp.ClientOSError,
    asyncio.TimeoutError,
    ConnectionResetError,
    OSError,
)


class LRUCache:
    """
    簡易 LRU 快取實作
    
    使用 OrderedDict 維護插入順序，
    存取時會將項目移到最後（最近使用）。
    """
    
    def __init__(self, max_size: int = 100000):
        self.max_size = max_size
        self._cache: OrderedDict[str, bool] = OrderedDict()
    
    def __contains__(self, key: str) -> bool:
        """檢查 key 是否存在，存在則移到最後（標記為最近使用）"""
        if key in self._cache:
            # 移到最後（最近使用）
            self._cache.move_to_end(key)
            return True
        return False
    
    def add(self, key: str):
        """新增 key 到快取"""
        if key in self._cache:
            # 已存在，移到最後
            self._cache.move_to_end(key)
        else:
            # 新增
            self._cache[key] = True
            # 檢查是否超過上限
            self._evict_if_needed()
    
    def _evict_if_needed(self):
        """如果超過上限，移除最舊的項目"""
        while len(self._cache) > self.max_size:
            # popitem(last=False) 移除最舊的（最前面的）
            self._cache.popitem(last=False)
    
    def __len__(self) -> int:
        return len(self._cache)
    
    def clear(self):
        """清空快取"""
        self._cache.clear()


class DuplicateChecker:
    """
    重複性檢查器
    
    支援兩種重複性方式:
    1. KeyName 檢查 (快速,基於檔名)
    2. MD5 檢查 (精確,基於檔案內容)
    
    Attributes:
        db_url: 資料庫連線字串
        db_pool: 資料庫連線池
        md5_cache: MD5 快取 (Set)
        keyname_cache: KeyName 快取 (Set)
        stats: 統計資訊
    """
    
    def __init__(self, db_url: Optional[str] = None):
        """
        初始化重複性檢查器
        
        Args:
            db_url: PostgreSQL 連線字串 (預設從環境變數讀取)
        """
        self.db_url = Settings.DATABASE_URL
        self.db_pool = None
        self.max_cache_size = Settings.DEDUP_MAX_CACHE_SIZE
        # 快取
        self.md5_cache = LRUCache(max_size=self.max_cache_size) 
        self.keyname_cache = LRUCache(max_size=self.max_cache_size)
        
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
        """
        初始化資料庫連線池並載入快取
        
        Raises:
            Exception: 資料庫連線失敗
        """
        if not self.db_url:
            logger.warning("重複性檢查 - 未提供資料庫連線,功能將被停用")
            return
        
        try:
            # 建立連線池
            self.db_pool = await asyncpg.create_pool(
                self.db_url,
                min_size=3,
                max_size=10,
                timeout=30
            )
            logger.info("重複性檢查 - 資料庫連線池建立成功")
            
            # 載入現有的 KeyName 快取
            await self._load_keyname_cache()
            
        except Exception as e:
            logger.error("重複性檢查 - 資料庫連線失敗: %s", str(e))
            logger.warning("重複性檢查 - 功能將被停用")
            self.db_pool = None
    
    async def close(self):
        """關閉資料庫連線池"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("重複性檢查 - 資料庫連線池已關閉")
    
    async def _load_keyname_cache(self, limit: int = 50000):
        """
        載入現有的 KeyName 到快取
        
        Args:
            limit: 載入的最大數量
        """
        if not self.db_pool:
            return
        
        try:
            async with self.db_pool.acquire() as conn:
                # 查詢最近的 originalFileName (使用子查詢處理 DISTINCT + ORDER BY)
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
                    Settings.DEDUP_PRELOAD_LIMIT
                )
                
                # 儲存到快取 (逐筆加入既有 LRUCache,保留淘汰機制)
                for r in records:
                    if r['filename']:
                        self.keyname_cache.add(r['filename'])

                logger.info("重複性檢查 - 快取載入完成,檔名數量: %d", len(self.keyname_cache))
                
        except Exception as e:
            logger.error("重複性檢查 - 快取載入失敗: %s", str(e))

    async def preload_keynames(self, keynames: list) -> None:
        """
        批次預載一批 KeyName 的存在狀態到快取

        取代逐筆呼叫 check_keyname_exists 造成的 N+1 查詢：
        一個批次只送 1 次 IN 查詢，命中的直接寫入快取，
        後續同批次內每張影像各自呼叫 check_keyname_exists 時就會直接命中快取。

        Args:
            keynames: 這個批次要上傳的 KeyName 清單 (不含副檔名)
        """
        if not self.db_pool or not keynames:
            return

        filenames = [f"{k}.jpg" for k in keynames if k]
        # 已在快取中的不必再查
        to_check = [f for f in filenames if f not in self.keyname_cache]
        if not to_check:
            return

        try:
            async with self.db_pool.acquire() as conn:
                records = await conn.fetch(
                    """
                    SELECT metadata->>'originalFileName' AS filename
                    FROM pictures
                    WHERE metadata->>'originalFileName' = ANY($1::text[])
                    """,
                    to_check
                )

            for r in records:
                if r['filename']:
                    self.keyname_cache.add(r['filename'])

            logger.debug(
                "重複性檢查 - 批次預載完成: 查詢 %d 筆, 命中 %d 筆",
                len(to_check), len(records)
            )

        except Exception as e:
            logger.error("重複性檢查 - 批次預載 KeyName 失敗: %s", str(e))

    @staticmethod
    def calculate_md5_from_bytes(data: bytes) -> str:
        """
        從 bytes 計算 MD5
        
        Args:
            data: 檔案內容
            
        Returns:
            MD5 字串 (32 字元 hex)
        """
        return hashlib.md5(data).hexdigest()
    
    @staticmethod
    def calculate_md5_from_file(file_path: str) -> str:
        """
        從本地檔案計算 MD5
        
        Args:
            file_path: 檔案路徑
            
        Returns:
            MD5 字串 (32 字元 hex)
            
        Raises:
            FileNotFoundError: 檔案不存在
            IOError: 檔案讀取失敗
        """
        md5_hash = hashlib.md5()
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)
        
        return md5_hash.hexdigest()
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(MD5_DOWNLOAD_RETRYABLE_EXCEPTIONS),
    )
    async def _download_and_hash(self, url: str, session: aiohttp.ClientSession) -> Optional[str]:
        """下載影像並計算 MD5 (內部方法，網路錯誤會被 tenacity 重試最多 3 次)"""
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 200:
                data = await resp.read()
                md5 = self.calculate_md5_from_bytes(data)
                logger.debug("MD5 計算 - 來源: URL, MD5: %s..., 大小: %d bytes",
                           md5[:8], len(data))
                return md5
            else:
                logger.error("MD5 計算 - URL 下載失敗,狀態碼: %d, URL: %s",
                           resp.status, url)
                return None

    async def calculate_md5_from_url(
        self,
        url: str,
        session: Optional[aiohttp.ClientSession] = None
    ) -> Optional[str]:
        """
        從 URL 下載並計算 MD5

        Args:
            url: 影像 URL
            session: 可選的 aiohttp session (重用連線)

        Returns:
            MD5 字串,失敗時返回 None
        """
        close_session = False

        try:
            if session is None:
                session = aiohttp.ClientSession()
                close_session = True

            return await self._download_and_hash(url, session)

        except Exception as e:
            logger.error("MD5 計算 - 從 URL 計算失敗 (已重試): %s", str(e))
            return None
        
        finally:
            if close_session and session:
                await session.close()

    async def check_md5_exists(self, md5: str) -> bool:
        """檢查 MD5 是否已存在"""
        if not md5:
            return False
        
        # 1. 快取檢查（LRU：存取時自動移到最後）
        if md5 in self.md5_cache:
            self.stats['cache_hits'] += 1
            logger.debug("重複性檢查 - MD5 快取命中: %s...", md5[:8])
            return True
        
        # 2. 資料庫檢查
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
                    # ✅ 使用 LRU 快取的 add 方法
                    self.md5_cache.add(md5)
                    logger.debug("重複性檢查 - MD5 資料庫命中: %s...", md5[:8])
                    return True
                
                return False
                
        except Exception as e:
            logger.error("重複性檢查 - MD5 查詢失敗: %s", str(e))
            return False
    
    async def check_keyname_exists(self, keyname: str) -> bool:
        """檢查 KeyName 是否已存在"""
        if not keyname:
            return False
        
        filename = f"{keyname}.jpg"
        
        # 1. 快取檢查
        if filename in self.keyname_cache:
            self.stats['cache_hits'] += 1
            logger.debug("重複性檢查 - KeyName 快取命中: %s", filename)
            return True
        
        # 2. 資料庫檢查
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
                    self.keyname_cache.add(filename)
                    logger.debug("重複性檢查 - KeyName 資料庫命中: %s", filename)
                    return True
                
                return False
                
        except Exception as e:
            logger.error("重複性檢查 - KeyName 查詢失敗: %s", str(e))
            return False

    async def check_keyname_exists_in_db(self, keyname: str) -> bool:
        """
        檢查 KeyName 是否已存在於資料庫中（不含快取）
        
        用於續傳檢查：確認該 KeyName 是否已經上傳過。
        
        Args:
            keyname: 影像 KeyName（不含副檔名）
            
        Returns:
            是否存在
        """
        if not keyname:
            return False
        
        filename = f"{keyname}.jpg"
        
        if not self.db_pool:
            logger.warning("重複性檢查 - 資料庫未連線")
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
                return exists
                
        except Exception as e:
            logger.error(
                "重複性檢查 - 查詢 KeyName 失敗: KeyName=%s, 錯誤=%s",
                keyname, str(e)
            )
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
        
        檢查流程:
        1. 檢查 KeyName (最快)
        2. 檢查 MD5 (可選,較慢但更準確)
        
        Args:
            keyname: 檔案名稱 (不含副檔名)
            img_url: 影像 URL (用於下載計算 MD5)
            check_md5: 是否檢查 MD5
            session: 可選的 aiohttp session
            
        Returns:
            (should_skip, reason): 是否跳過, 跳過原因
        """
        self.stats['checked'] += 1
        
        # ========================================
        # 1. KeyName 檢查 (優先,最快)
        # ========================================
        if await self.check_keyname_exists(keyname):
            self.stats['duplicates_keyname'] += 1
            reason = f"檔名重複: {keyname}.jpg"
            logger.info("重複性檢查 - 跳過上傳: %s", reason)
            return (True, reason)
        
        # ========================================
        # 2. MD5 檢查 (可選)
        # ========================================
        if check_md5:
            md5 = None
            
            # 2.1 嘗試從本地檔案計算
            if IMAGE_BASE_PATH:
                image_path = os.path.join(IMAGE_BASE_PATH, f"{keyname}.jpg")
                
                if os.path.exists(image_path):
                    try:
                        md5 = self.calculate_md5_from_file(image_path)
                        self.stats['md5_calculated'] += 1
                        logger.debug("MD5 計算 - 來源: 本地檔案, KeyName: %s", keyname)
                    except Exception as e:
                        logger.error("MD5 計算 - 本地檔案失敗,KeyName: %s, 錯誤: %s", 
                                   keyname, str(e))
            
            # 2.2 嘗試從 URL 下載計算
            if md5 is None and img_url:
                logger.debug("MD5 計算 - 嘗試從 URL,KeyName: %s", keyname)
                md5 = await self.calculate_md5_from_url(img_url, session)
                
                if md5:
                    self.stats['md5_calculated'] += 1
            
            # 2.3 檢查 MD5 是否存在
            if md5:
                if await self.check_md5_exists(md5):
                    self.stats['duplicates_md5'] += 1
                    reason = f"MD5 重複: {md5[:8]}..."
                    logger.info("重複性檢查 - 跳過上傳: %s", reason)
                    return (True, reason)
            else:
                # MD5 計算失敗,記錄但不阻止上傳
                self.stats['md5_skipped'] += 1
                logger.warning("重複性檢查 - MD5 計算失敗,KeyName: %s (仍會繼續上傳)", keyname)
        
        # ========================================
        # 3. 不重複,可以上傳
        # ========================================
        logger.debug("重複性檢查 - 可上傳: %s", keyname)
        return (False, "可上傳")
    
    def get_stats(self) -> dict:
        """
        取得統計資訊
        
        Returns:
            統計資訊字典
        """
        return {
            **self.stats,
            'cache_size_md5': len(self.md5_cache),
            'cache_size_keyname': len(self.keyname_cache)
        }
    
    def print_stats(self):
        """列印統計報告 (格式化表格)"""
        stats = self.get_stats()
        
        logger.info("=" * 80)
        logger.info("重複性檢查統計報告")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "檢查總數", stats['checked'])
        logger.info("%-30s: %10d", "KeyName 重複", stats['duplicates_keyname'])
        logger.info("%-30s: %10d", "MD5 重複", stats['duplicates_md5'])
        logger.info("%-30s: %10d", "快取命中", stats['cache_hits'])
        logger.info("%-30s: %10d", "MD5 已計算", stats['md5_calculated'])
        logger.info("%-30s: %10d", "MD5 跳過", stats['md5_skipped'])
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "MD5 快取大小", stats['cache_size_md5'])
        logger.info("%-30s: %10d", "KeyName 快取大小", stats['cache_size_keyname'])
        logger.info("=" * 80)
    
    def reset_stats(self):
        """重置統計資訊"""
        self.stats = {
            'checked': 0,
            'duplicates_md5': 0,
            'duplicates_keyname': 0,
            'cache_hits': 0,
            'md5_calculated': 0,
            'md5_skipped': 0
        }
        logger.info("重複性檢查 - 統計資訊已重置")


# ========================================
# 全域實例 (單例模式)
# ========================================
_duplicate_checker_instance = None


def get_duplicate_checker() -> DuplicateChecker:
    """
    取得全域重複性檢查器實例
    
    Returns:
        DuplicateChecker 實例
    """
    global _duplicate_checker_instance
    if _duplicate_checker_instance is None:
        _duplicate_checker_instance = DuplicateChecker()
    return _duplicate_checker_instance


# ========================================
# 測試程式
# ========================================
if __name__ == "__main__":
    import asyncio
    from src.config.logging_config import setup_logging
    
    async def test():
        """測試程式"""
        # 設定日誌
        setup_logging()
        
        # 建立檢查器
        checker = DuplicateChecker()
        await checker.initialize()
        
        # 測試 1: 檢查 KeyName
        keyname = "20250618093828079_S9D3DPLAR"
        url = "https://roadapp.nat.gov.tw/CCImage/TTU11402/S9CR0PKTG/20250618093828079_S9D3DPLAR.jpg"
        
        logger.info("測試 KeyName: %s", keyname)
        should_skip, reason = await checker.should_skip_upload(
            keyname, 
            img_url=url,
            check_md5=True
        )
        
        logger.info("結果 - 是否跳過: %s, 原因: %s", should_skip, reason)
        
        # 測試 2: 再次檢查 (測試快取)
        logger.info("再次測試 (應該使用快取)")
        should_skip, reason = await checker.should_skip_upload(keyname)
        logger.info("結果 - 是否跳過: %s, 原因: %s", should_skip, reason)
        
        # 顯示統計
        checker.print_stats()
        
        await checker.close()
    
    asyncio.run(test())