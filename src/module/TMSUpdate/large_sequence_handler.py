# src/module/TMSUpdate/large_sequence_handler.py
"""
大型 Sequence 處理模組
針對大型 sequence 的特殊處理策略
"""

import logging
from typing import List, Dict
import pandas as pd

logger = logging.getLogger(__name__)


class LargeSequenceHandler:
    """大型 Sequence 處理器"""
    
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
            配置字典 {batch_size, batch_delay, max_concurrent}
        """
        seq_type = cls.classify_sequence(size)
        
        configs = {
            'small': {
                'batch_size': 50,
                'batch_delay': 10,
                'max_concurrent': 3,
                'description': '小型 sequence (< 500 張)'
            },
            'medium': {
                'batch_size': 30,
                'batch_delay': 15,
                'max_concurrent': 2,
                'description': '中型 sequence (500-2000 張)'
            },
            'large': {
                'batch_size': 20,
                'batch_delay': 20,
                'max_concurrent': 1,
                'description': '大型 sequence (> 2000 張)'
            }
        }
        
        config = configs[seq_type]
        logger.info(
            f"📊 Sequence 分類: {config['description']} "
            f"({size} 張) - "
            f"Batch: {config['batch_size']}, "
            f"Delay: {config['batch_delay']}s, "
            f"Concurrent: {config['max_concurrent']}"
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
            f"分割完成: {total_rows} 張影像 → "
            f"{len(batches)} 批次 (每批 ~{batch_size} 張)"
        )
        
        return batches
    
    def update_stats(self, seq_type: str, image_count: int):
        """更新統計資訊"""
        self.stats[seq_type] += 1
        self.stats['total_images'] += image_count
    
    def get_stats(self) -> Dict:
        """取得統計資訊"""
        return self.stats.copy()
    
    def print_summary(self):
        """列印統計摘要"""
        logger.info("=" * 60)
        logger.info("📊 Sequence 處理統計")
        logger.info("=" * 60)
        logger.info(f"小型 sequences (< 500):    {self.stats['small']}")
        logger.info(f"中型 sequences (500-2000): {self.stats['medium']}")
        logger.info(f"大型 sequences (> 2000):   {self.stats['large']}")
        logger.info(f"總影像數:                   {self.stats['total_images']}")
        logger.info("=" * 60)


# 全域實例
large_seq_handler = LargeSequenceHandler()


if __name__ == "__main__":
    # 測試
    handler = LargeSequenceHandler()
    
    # 測試不同大小的 sequence
    test_sizes = [100, 800, 3000, 5000]
    
    for size in test_sizes:
        config = handler.get_batch_config(size)
        seq_type = handler.classify_sequence(size)
        handler.update_stats(seq_type, size)
        print(f"\n大小: {size}, 配置: {config}")
    
    handler.print_summary()
