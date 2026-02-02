# src/module/TMSUpdate/sequence_batch_handler.py
"""
大型 Sequence 處理模組

針對大型 sequence 的特殊處理策略:
- 小型 (< 500 張): 快速處理
- 中型 (500-2000 張): 中等速度
- 大型 (> 2000 張): 謹慎處理
"""

import logging
from typing import List, Dict
import pandas as pd

logger = logging.getLogger(__name__)


class SequenceBatchHandler:
    """
    大型 Sequence 處理器
    
    根據序列大小自動調整處理策略:
    - batch_size: 每批次影像數量
    - batch_delay: 批次間延遲時間
    - max_concurrent: 最大並發數
    """
    
    # Sequence 大小分類閾值
    SMALL_THRESHOLD = 500      # 小型: < 500 張
    MEDIUM_THRESHOLD = 2000    # 中型: 500-2000 張
    # 大型: > 2000 張
    
    def __init__(self):
        self.stats = {
            'small': 0,
            'medium': 0,
            'large': 0,
            'total_images': 0
        }
    
    @classmethod
    def classify_sequence(cls, size: int) -> str:
        """
        分類 sequence 大小
        
        Args:
            size: Sequence 中的影像數量
            
        Returns:
            'small' | 'medium' | 'large'
        """
        if size < cls.SMALL_THRESHOLD:
            return 'small'
        elif size < cls.MEDIUM_THRESHOLD:
            return 'medium'
        else:
            return 'large'
    
    @classmethod
    def get_batch_config(cls, size: int) -> Dict:
        """
        根據 sequence 大小取得批次配置
        
        Args:
            size: Sequence 中的影像數量
            
        Returns:
            配置字典 {batch_size, batch_delay, max_concurrent, description}
        """
        seq_type = cls.classify_sequence(size)
        
        configs = {
            'small': {
                'batch_size': 50,
                'batch_delay': 10,
                'max_concurrent': 3,
                'description': '小型序列 (< 500 張)'
            },
            'medium': {
                'batch_size': 30,
                'batch_delay': 15,
                'max_concurrent': 2,
                'description': '中型序列 (500-2000 張)'
            },
            'large': {
                'batch_size': 20,
                'batch_delay': 20,
                'max_concurrent': 1,
                'description': '大型序列 (> 2000 張)'
            }
        }
        
        config = configs[seq_type]
        logger.info(
            "序列批次 - 分類: %s (%d 張), Batch: %d, Delay: %d 秒, 並發: %d",
            config['description'], size, config['batch_size'],
            config['batch_delay'], config['max_concurrent']
        )
        
        return config
    
    @staticmethod
    def split_into_batches(
        df: pd.DataFrame, 
        batch_size: int
    ) -> List[pd.DataFrame]:
        """
        將 DataFrame 分割成批次
        
        Args:
            df: 要分割的 DataFrame
            batch_size: 每批的大小
            
        Returns:
            批次列表
        """
        batches = []
        total_rows = len(df)
        
        for i in range(0, total_rows, batch_size):
            batch = df.iloc[i:i + batch_size]
            batches.append(batch)
        
        logger.info(
            "序列批次 - 分割完成: %d 張影像 → %d 批次 (每批約 %d 張)",
            total_rows, len(batches), batch_size
        )
        
        return batches
    
    def update_stats(self, seq_type: str, image_count: int):
        """
        更新統計資訊
        
        Args:
            seq_type: 序列類型 (small/medium/large)
            image_count: 影像數量
        """
        self.stats[seq_type] += 1
        self.stats['total_images'] += image_count
        
        logger.debug(
            "序列批次 - 統計更新: 類型=%s, 數量=%d",
            seq_type, image_count
        )
    
    def get_stats(self) -> Dict:
        """
        取得統計資訊
        
        Returns:
            統計資訊字典
        """
        return self.stats.copy()
    
    def print_summary(self):
        """列印統計摘要"""
        logger.info("=" * 80)
        logger.info("序列處理統計摘要")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "小型序列 (< 500)", self.stats['small'])
        logger.info("%-30s: %10d", "中型序列 (500-2000)", self.stats['medium'])
        logger.info("%-30s: %10d", "大型序列 (> 2000)", self.stats['large'])
        logger.info("%-30s: %10d", "影像總數", self.stats['total_images'])
        logger.info("=" * 80)
    
    def reset_stats(self):
        """重置統計資訊"""
        self.stats = {
            'small': 0,
            'medium': 0,
            'large': 0,
            'total_images': 0
        }
        logger.info("序列批次 - 統計資訊已重置")


# ========================================
# 全域實例 (單例模式)
# ========================================
large_seq_handler = SequenceBatchHandler()


if __name__ == "__main__":
    # 測試
    handler = SequenceBatchHandler()
    
    # 測試不同大小的 sequence
    test_sizes = [100, 800, 3000, 5000]
    
    logger.info("開始測試序列批次處理器")
    
    for size in test_sizes:
        config = handler.get_batch_config(size)
        seq_type = handler.classify_sequence(size)
        handler.update_stats(seq_type, size)
        logger.info("測試序列 - 大小: %d, 配置: %s", size, config)
    
    handler.print_summary()
    
    logger.info("測試完成")