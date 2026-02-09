"""
失敗記錄追蹤模組

功能:
1. 記錄上傳失敗的影像
2. 記錄失敗的 Collection
3. 生成失敗報告
4. 儲存失敗統計
"""

import time
import logging
from pathlib import Path
from typing import List, Set, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class FailureTracker:
    """
    失敗記錄追蹤器
    
    負責追蹤和記錄上傳過程中的各種失敗情況,
    並生成詳細的失敗報告供後續分析。
    
    Attributes:
        upload_failures: 上傳失敗記錄列表
        collection_failures: 失敗的 Collection ID 集合
    """
    
    def __init__(self):
        """初始化失敗追蹤器"""
        self.upload_failures: List[Dict] = []
        self.collection_failures: Set[str] = set()
    
    def record_upload_failure(
        self, 
        keyname: str, 
        collection_id: str, 
        error: str, 
        retry_count: int
    ):
        """
        記錄上傳失敗
        
        Args:
            keyname: 失敗的影像 KeyName
            collection_id: Collection ID
            error: 錯誤訊息
            retry_count: 重試次數
        """
        failure_record = {
            'KeyName': keyname,
            'CollectionID': collection_id,
            'Error': error,
            'RetryCount': retry_count,
            'Timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        self.upload_failures.append(failure_record)
        
        logger.debug(
            "失敗追蹤 - 記錄上傳失敗: KeyName=%s, Collection=%s, 重試=%d",
            keyname, collection_id, retry_count
        )
    
    def record_collection_failure(self, collection_id: str):
        """
        記錄 Collection 失敗
        
        Args:
            collection_id: 失敗的 Collection ID
        """
        self.collection_failures.add(collection_id)
        
        logger.debug(
            "失敗追蹤 - 記錄 Collection 失敗: %s",
            collection_id
        )
    
    def get_upload_failure_count(self) -> int:
        """
        取得上傳失敗總數
        
        Returns:
            失敗數量
        """
        return len(self.upload_failures)
    
    def get_collection_failure_count(self) -> int:
        """
        取得失敗的 Collection 數量
        
        Returns:
            失敗數量
        """
        return len(self.collection_failures)
    
    def get_failure_summary(self) -> Dict:
        """
        取得失敗摘要
        
        Returns:
            包含失敗統計的字典
        """
        return {
            'upload_failures': self.get_upload_failure_count(),
            'collection_failures': self.get_collection_failure_count(),
            'total_failures': self.get_upload_failure_count(),
            'failed_collections': list(self.collection_failures)
        }
    
    def print_summary(self):
        """列印失敗摘要"""
        summary = self.get_failure_summary()
        
        logger.info("=" * 80)
        logger.info("失敗記錄摘要")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "上傳失敗", summary['upload_failures'])
        logger.info("%-30s: %10d", "Collection 失敗", summary['collection_failures'])
        logger.info("=" * 80)
        
        if summary['collection_failures'] > 0:
            logger.info("失敗的 Collection ID:")
            for cid in summary['failed_collections']:
                logger.info("  - %s", cid)
            logger.info("=" * 80)
    
    async def save_reports(self, output_dir: Optional[Path] = None):
        """
        儲存失敗報告
        
        Args:
            output_dir: 輸出目錄 (預設: logs/)
        """
        if output_dir is None:
            output_dir = Path("logs")
        
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        
        # ========================================
        # 1. 儲存上傳失敗報告
        # ========================================
        if self.upload_failures:
            failure_df = pd.DataFrame(self.upload_failures)
            failure_csv_path = output_dir / f"{timestamp}_upload_failures.csv"
            
            try:
                failure_df.to_csv(failure_csv_path, index=False, encoding='utf-8-sig')
                logger.info(
                    "失敗報告 - 上傳失敗已儲存: %s (共 %d 筆)",
                    failure_csv_path, len(self.upload_failures)
                )
                
                # 列出前 10 個失敗案例
                for i, failure in enumerate(self.upload_failures[:10], 1):
                    logger.error(
                        "上傳失敗 %d: KeyName=%s, Collection=%s, 錯誤=%s",
                        i, failure['KeyName'], failure['CollectionID'], 
                        failure['Error']
                    )
                
                if len(self.upload_failures) > 10:
                    logger.error(
                        "... 還有 %d 筆上傳失敗記錄",
                        len(self.upload_failures) - 10
                    )
            
            except Exception as e:
                logger.error("失敗報告 - 儲存上傳失敗失敗: %s", str(e))
        
        else:
            logger.info("失敗報告 - 無上傳失敗記錄")
        
        # ========================================
        # 2. 儲存 Collection 失敗報告
        # ========================================
        if self.collection_failures:
            collections_df = pd.DataFrame({
                "collection_id": list(self.collection_failures)
            })
            collections_csv_path = output_dir / f"{timestamp}_failed_collections.csv"
            
            try:
                collections_df.to_csv(
                    collections_csv_path, 
                    index=False, 
                    encoding='utf-8-sig'
                )
                logger.info(
                    "失敗報告 - Collection 失敗已儲存: %s (共 %d 個)",
                    collections_csv_path, len(self.collection_failures)
                )
                
                # 列出所有失敗的 Collection
                for cid in self.collection_failures:
                    logger.error("Collection 失敗: %s", cid)
            
            except Exception as e:
                logger.error("失敗報告 - 儲存 Collection 失敗失敗: %s", str(e))
        
        else:
            logger.info("失敗報告 - 無 Collection 失敗記錄")
        
        # ========================================
        # 3. 如果完全成功
        # ========================================
        if not self.upload_failures and not self.collection_failures:
            logger.info("失敗報告 - 所有操作成功完成,無失敗記錄")
    
    def clear(self):
        """清空所有記錄"""
        self.upload_failures.clear()
        self.collection_failures.clear()
        logger.info("失敗追蹤 - 已清空所有記錄")
    
    def has_failures(self) -> bool:
        """
        檢查是否有失敗記錄
        
        Returns:
            是否有失敗
        """
        return bool(self.upload_failures or self.collection_failures)


# ========================================
# 全域實例 (單例模式,向後相容)
# ========================================
_failure_tracker_instance = None


def get_failure_tracker() -> FailureTracker:
    """
    取得全域失敗追蹤器實例
    
    Returns:
        FailureTracker 實例
    """
    global _failure_tracker_instance
    if _failure_tracker_instance is None:
        _failure_tracker_instance = FailureTracker()
    return _failure_tracker_instance


# ========================================
# 向後相容 - 全域變數
# (保留以相容舊程式碼,但建議使用 FailureTracker class)
# ========================================
failure_tracker = get_failure_tracker()
upload_failures = failure_tracker.upload_failures
collection_failures = failure_tracker.collection_failures


if __name__ == "__main__":
    import asyncio
    
    async def test():
        """測試程式"""
        tracker = FailureTracker()
        
        # 測試記錄失敗
        tracker.record_upload_failure(
            keyname="test_001",
            collection_id="col_123",
            error="Network timeout",
            retry_count=3
        )
        
        tracker.record_upload_failure(
            keyname="test_002",
            collection_id="col_123",
            error="File not found",
            retry_count=0
        )
        
        tracker.record_collection_failure("col_123")
        tracker.record_collection_failure("col_456")
        
        # 顯示摘要
        tracker.print_summary()
        
        # 儲存報告
        await tracker.save_reports(Path("test_logs"))
        
        print(f"\n測試完成 - 失敗數: {tracker.get_upload_failure_count()}")
    
    asyncio.run(test())