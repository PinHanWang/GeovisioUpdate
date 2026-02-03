# src/module/TMSUpdate/resource_monitor.py
"""
簡化版資源監控 - 基於 Job Queue 積壓情況

監控邏輯:
- Job Queue 積壓 < 100 筆 → 安全,可以繼續上傳
- Job Queue 積壓 100-500 筆 → 警告,減慢上傳速度
- Job Queue 積壓 > 500 筆 → 危險,暫停上傳等待處理
"""

import asyncio
import logging
import asyncpg
import os
from typing import Optional, Dict, Tuple
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()


class ResourceMonitor:
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
                logger.info("資源監控 - 初始化成功")
            except Exception as e:
                logger.warning("資源監控 - 資料庫連線失敗: %s,功能將被停用", str(e))
                self.db_pool = None
        else:
            logger.warning("資源監控 - 未提供資料庫連線,功能將被停用")
    
    async def close(self):
        """關閉資料庫連線池"""
        if self.db_pool:
            await self.db_pool.close()
            logger.info("資源監控 - 資料庫連線池已關閉")
    
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
            logger.error("資源監控 - Job Queue 查詢失敗: %s", str(e))
            return 0
    
    async def check_resources(self) -> Tuple[bool, Dict]:
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
            logger.debug("資源監控 - Job Queue: %d 筆 (安全)", queue_count)
            
        elif queue_count < self.warning_threshold:
            # 警告範圍
            stats['status'] = 'warning'
            is_safe = True  # 仍可繼續,但會減速
            logger.warning(
                "資源監控 - Job Queue 積壓: %d 筆 (建議減慢上傳速度)",
                queue_count
            )
            
        else:
            # 危險範圍
            stats['status'] = 'critical'
            is_safe = False
            logger.error(
                "資源監控 - Job Queue 嚴重積壓: %d 筆 (需要等待處理)",
                queue_count
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
                    "資源監控 - Job Queue 已恢復到安全水平,剩餘 %d 筆",
                    queue_count
                )
                return True
            
            logger.warning(
                "資源監控 - 等待 Job Queue 處理,已等待 %d/%d 秒,剩餘 %d 筆",
                waited, max_wait, queue_count
            )
            
            await asyncio.sleep(30)
            waited += 30
        
        logger.error(
            "資源監控 - 等待超時 (%d 秒), Job Queue 仍有 %d 筆待處理",
            max_wait, queue_count
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
                "資源監控 - Job Queue 積壓 (%d 筆), batch size 調整: %d → %d",
                queue_count, default_size, adjusted_size
            )
            return adjusted_size
        
        else:  # critical
            # 危險,減半
            adjusted_size = max(5, default_size // 2)
            logger.error(
                "資源監控 - Job Queue 嚴重積壓 (%d 筆), batch size 調整: %d → %d",
                queue_count, default_size, adjusted_size
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
                "資源監控 - 增加批次延遲: %d 秒 → %d 秒",
                default_delay, adjusted_delay
            )
            return adjusted_delay
        
        else:  # critical
            # 危險,延遲加倍
            adjusted_delay = default_delay * 2
            logger.error(
                "資源監控 - 大幅增加批次延遲: %d 秒 → %d 秒",
                default_delay, adjusted_delay
            )
            return adjusted_delay


# ========================================
# 全域實例 (單例模式)
# ========================================
simple_resource_monitor = ResourceMonitor(
    safe_threshold=100,
    warning_threshold=500,
    check_interval=60
)


if __name__ == "__main__":
    # 測試
    async def test():
        monitor = ResourceMonitor()
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