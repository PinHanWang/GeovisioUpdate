# src/module/TMSUpdate/optimization/sequence_batch_handler.py
"""
大型 Sequence 處理模組 (重構版)

針對大型 sequence 的特殊處理策略:
- 小型 (預設 < 500 張): 快速處理
- 中型 (預設 500-2000 張): 中等速度
- 大型 (預設 > 2000 張): 謹慎處理

所有閾值和配置現在從 settings 讀取，可透過環境變數調整
"""

import logging
from typing import List, Dict
import pandas as pd

# 導入設定
try:
    from src.module.TMSUpdate.config.settings import Settings
except ImportError:
    from ..config.settings import Settings

logger = logging.getLogger(__name__)


class SequenceBatchHandler:
    """
    大型 Sequence 處理器
    
    根據序列大小自動調整處理策略:
    - batch_size: 每批次影像數量
    - batch_delay: 批次間延遲時間
    - max_concurrent: 最大並發數
    
    所有配置從 Settings 讀取，可透過環境變數調整
    """
    
    def __init__(self):
        self.stats = {
            'small': 0,
            'medium': 0,
            'large': 0,
            'total_images': 0
        }
        
        # 從 Settings 讀取閾值
        self.small_threshold = Settings.SEQUENCE_SMALL_THRESHOLD
        self.medium_threshold = Settings.SEQUENCE_MEDIUM_THRESHOLD
        
        logger.info(
            "序列批次 - 初始化完成: 小型閾值=%d, 中型閾值=%d",
            self.small_threshold, self.medium_threshold
        )
    
    def classify_sequence(self, size: int) -> str:
        """
        分類 sequence 大小
        
        Args:
            size: Sequence 中的影像數量
            
        Returns:
            'small' | 'medium' | 'large'
        """
        if size < self.small_threshold:
            return 'small'
        elif size < self.medium_threshold:
            return 'medium'
        else:
            return 'large'
    
    def get_batch_config(self, size: int) -> Dict:
        """
        根據 sequence 大小取得批次配置
        
        使用 Settings.get_batch_config() 統一管理配置
        
        Args:
            size: Sequence 中的影像數量
            
        Returns:
            配置字典 {batch_size, batch_delay, max_concurrent, description}
        """
        config = Settings.get_batch_config(size)
        
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
        """取得統計資訊"""
        return self.stats.copy()
    
    def print_summary(self):
        """列印統計摘要"""
        logger.info("=" * 80)
        logger.info("序列處理統計摘要")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", f"小型序列 (< {self.small_threshold})", self.stats['small'])
        logger.info("%-30s: %10d", f"中型序列 ({self.small_threshold}-{self.medium_threshold})", self.stats['medium'])
        logger.info("%-30s: %10d", f"大型序列 (> {self.medium_threshold})", self.stats['large'])
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


# 全域實例 (單例模式)
large_seq_handler = SequenceBatchHandler()
