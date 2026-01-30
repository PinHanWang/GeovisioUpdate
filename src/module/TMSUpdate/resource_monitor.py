# src/module/TMSUpdate/resource_monitor_simple.py
"""
簡化版資源監控 - 基於 Job Queue 積壓情況
這是最簡單也最有效的方式!
"""

import asyncio
import logging
import asyncpg
import os
from typing import Optional, Dict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()


class SimpleResourceMonitor:
    """
    簡化版資源監控器
    
    監控邏輯:
    - Job Queue 積壓 < 100 筆 → 安全,可以繼續上傳
    - Job Queue 積壓 100-500 筆 → 警告,減慢上傳速度
    - Job Queue 積壓 > 500 筆 → 危險,暫停上傳等待處理
    """
    
    def __init__(
        self,
        db_url: Optional[str] = None,
        safe_threshold: int = 100,      # 安全閾值
        warning_threshold: int = 500,   # 警告閾值
        check_interval: int = 60,
    ):
        self.db_url = db_url or os.getenv("DATABASE_URL")
        self.safe_threshold = safe_threshold
        self.warning_threshold = warning_threshold
        self.check_interval = check_interval
        self.db_pool = None
    
    async def initialize(self):
        """初始化資料庫連線池"""
        if self.db_url:
            try:
                self.db_pool = await asyncpg.create_pool(
                    self.db_url,
                    min_size=1,
                    max_size=3,
                    timeout=30
                )
                logger.info("資源監控器初始化成功")
            except Exception as e:
                logger.warning(f"無法連線到資料庫,資源監控將被停用: {e}")
                self.db_pool = None
        else:
            logger.warning("未提供資料庫連線,資源監控將被停用")
    
    async def close(self):
        """關閉資料庫連線池"""
        if self.db_pool:
            await self.db_pool.close()
    
    async def get_job_queue_count(self) -> int:
        """
        取得 Job Queue 中待處理的任務數量
        
        Returns:
            待處理任務數量 (錯誤時返回 0)
        """
        if not self.db_pool:
            return 0
        
        try:
            async with self.db_pool.acquire() as conn:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM job_queue"
                )
                return count or 0
        except Exception as e:
            logger.error(f"查詢 job_queue 失敗: {e}")
            return 0
    
    async def check_resources(self) -> tuple[bool, dict]:
        """
        檢查資源狀態 (基於 Job Queue)
        
        Returns:
            (is_safe, stats): 是否安全繼續上傳, 統計資訊
        """
        queue_count = await self.get_job_queue_count()
        
        stats = {
            'job_queue_count': queue_count,
            'status': 'unknown'
        }
        
        if queue_count < self.safe_threshold:
            # 安全範圍
            stats['status'] = 'safe'
            is_safe = True
            logger.debug(f"📊 Job Queue: {queue_count} 筆 (安全)")
            
        elif queue_count < self.warning_threshold:
            # 警告範圍
            stats['status'] = 'warning'
            is_safe = True  # 仍可繼續,但會減速
            logger.warning(
                f"⚠️  Job Queue 積壓: {queue_count} 筆 "
                f"(建議減慢上傳速度)"
            )
            
        else:
            # 危險範圍
            stats['status'] = 'critical'
            is_safe = False
            logger.error(
                f"🔴 Job Queue 嚴重積壓: {queue_count} 筆 "
                f"(需要等待處理)"
            )
        
        return is_safe, stats
    
    async def wait_for_resources(self, max_wait: int = 300) -> bool:
        """
        等待 Job Queue 處理到安全水平
        
        Args:
            max_wait: 最大等待時間 (秒)
            
        Returns:
            是否成功恢復到安全水平
        """
        waited = 0
        
        while waited < max_wait:
            is_safe, stats = await self.check_resources()
            queue_count = stats['job_queue_count']
            
            if is_safe:
                logger.info(
                    f"✅ Job Queue 已恢復到安全水平 - "
                    f"剩餘 {queue_count} 筆"
                )
                return True
            
            logger.warning(
                f"等待 Job Queue 處理... ({waited}/{max_wait}s) - "
                f"剩餘 {queue_count} 筆"
            )
            
            await asyncio.sleep(30)
            waited += 30
        
        logger.error(
            f"❌ 等待超時 ({max_wait}s), "
            f"Job Queue 仍有 {queue_count} 筆待處理"
        )
        return False
    
    async def get_dynamic_batch_size(
        self,
        default_size: int,
        sequence_size: int
    ) -> int:
        """
        根據 Job Queue 狀況動態調整 batch size
        
        Args:
            default_size: 預設的 batch size
            sequence_size: sequence 總大小
            
        Returns:
            調整後的 batch size
        """
        is_safe, stats = await self.check_resources()
        queue_count = stats['job_queue_count']
        status = stats['status']
        
        if status == 'safe':
            # 安全,使用預設值
            return default_size
        
        elif status == 'warning':
            # 警告,減少 30%
            adjusted_size = max(10, int(default_size * 0.7))
            logger.warning(
                f"⚠️  Job Queue 積壓 ({queue_count} 筆), "
                f"batch size 調整: {default_size} → {adjusted_size}"
            )
            return adjusted_size
        
        else:  # critical
            # 危險,減半
            adjusted_size = max(5, default_size // 2)
            logger.error(
                f"🔴 Job Queue 嚴重積壓 ({queue_count} 筆), "
                f"batch size 調整: {default_size} → {adjusted_size}"
            )
            return adjusted_size
    
    async def get_dynamic_batch_delay(
        self,
        default_delay: int
    ) -> int:
        """
        根據 Job Queue 狀況動態調整批次延遲
        
        Args:
            default_delay: 預設的延遲 (秒)
            
        Returns:
            調整後的延遲 (秒)
        """
        is_safe, stats = await self.check_resources()
        queue_count = stats['job_queue_count']
        status = stats['status']
        
        if status == 'safe':
            return default_delay
        
        elif status == 'warning':
            # 警告,增加 50% 延遲
            adjusted_delay = int(default_delay * 1.5)
            logger.warning(
                f"⚠️  增加批次延遲: {default_delay}s → {adjusted_delay}s"
            )
            return adjusted_delay
        
        else:  # critical
            # 危險,延遲加倍
            adjusted_delay = default_delay * 2
            logger.error(
                f"🔴 大幅增加批次延遲: {default_delay}s → {adjusted_delay}s"
            )
            return adjusted_delay


# 全域實例
simple_resource_monitor = SimpleResourceMonitor(
    safe_threshold=100,
    warning_threshold=500,
    check_interval=60
)


if __name__ == "__main__":
    # 測試
    async def test():
        monitor = SimpleResourceMonitor()
        await monitor.initialize()
        
        # 測試檢查
        is_safe, stats = await monitor.check_resources()
        print(f"系統安全: {is_safe}")
        print(f"統計: {stats}")
        
        # 測試動態調整
        batch_size = await monitor.get_dynamic_batch_size(50, 1000)
        print(f"調整後的 batch size: {batch_size}")
        
        await monitor.close()
    
    asyncio.run(test())
