"""
CSV 編碼統一轉換工具

功能:
1. 自動偵測 CSV 檔案編碼
2. 統一轉換為 UTF-8 (無 BOM)
3. 支援批次處理
4. 備份原始檔案
"""

import os
import threading
import chardet
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class CSVEncodingConverter:
    """
    CSV 編碼轉換器
    
    提供 CSV 檔案編碼的偵測和轉換功能,
    支援自動偵測來源編碼,統一轉換為 UTF-8。
    
    Attributes:
        backup: 是否備份原始檔案
        converted_count: 轉換成功數量
        failed_count: 轉換失敗數量
        skipped_count: 跳過數量
    """
    
    def __init__(self, backup: bool = True):
        """
        初始化轉換器
        
        Args:
            backup: 是否備份原始檔案 (預設: True)
        """
        self.backup = backup
        self.converted_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        # convert_directory 平行處理多檔時，多個執行緒會同時更新上面三個計數器
        self._counter_lock = threading.Lock()
    
    def detect_encoding(self, file_path: Path) -> Optional[str]:
        """
        偵測檔案編碼
        
        Args:
            file_path: 檔案路徑
            
        Returns:
            偵測到的編碼,失敗返回 None
        """
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                confidence = result['confidence']
                
                logger.debug(
                    "編碼轉換 - 偵測編碼類型: 檔案=%s, 編碼=%s, 信心度=%.2f%%",
                    file_path.name, encoding, confidence * 100
                )
                
                return encoding
                
        except Exception as e:
            logger.error("編碼轉換 - 偵測失敗: 檔案=%s, 錯誤=%s", file_path.name, str(e))
            return None
    
    def convert_to_utf8(
        self, 
        file_path: Path, 
        source_encoding: Optional[str] = None,
        target_encoding: str = 'utf-8'
    ) -> bool:
        """
        轉換檔案編碼為 UTF-8
        
        Args:
            file_path: 檔案路徑
            source_encoding: 來源編碼,如果為 None 則自動偵測
            target_encoding: 目標編碼 (預設: utf-8,不含 BOM)
            
        Returns:
            轉換成功返回 True,失敗返回 False
        """
        try:
            # 偵測或使用指定的來源編碼
            if source_encoding is None:
                source_encoding = self.detect_encoding(file_path)
                
                if source_encoding is None:
                    logger.error("編碼轉換 - 無法偵測編碼類型: %s", file_path.name)
                    with self._counter_lock:
                        self.failed_count += 1
                    return False
            
            # 如果已經是目標編碼,檢查是否有 BOM
            source_normalized = source_encoding.lower().replace('-', '')
            target_normalized = target_encoding.lower().replace('-', '')
            
            if source_normalized == target_normalized:
                # 檢查是否有 BOM
                with open(file_path, 'rb') as f:
                    header = f.read(3)
                    
                if header == b'\xef\xbb\xbf':
                    # 有 BOM,需要移除
                    logger.info("編碼轉換 - 移除 BOM: %s", file_path.name)
                else:
                    # 已經是 UTF-8 且無 BOM,跳過
                    logger.debug("編碼轉換 - 跳過 (已是 UTF-8): %s", file_path.name)
                    with self._counter_lock:
                        self.skipped_count += 1
                    return True
            
            # 備份原始檔案
            if self.backup:
                backup_path = file_path.with_suffix(file_path.suffix + '.bak')
                
                # 如果備份檔已存在,加上數字
                counter = 1
                while backup_path.exists():
                    backup_path = file_path.with_suffix(f'{file_path.suffix}.bak{counter}')
                    counter += 1
                
                import shutil
                shutil.copy2(file_path, backup_path)
                logger.debug("編碼轉換 - 建立備份檔案: %s", backup_path.name)
            
            # 讀取原始內容
            with open(file_path, 'r', encoding=source_encoding, errors='replace') as f:
                content = f.read()
            
            # 寫入 UTF-8 (無 BOM)
            with open(file_path, 'w', encoding=target_encoding, newline='') as f:
                f.write(content)
            
            logger.info(
                "編碼轉換 - 轉換成功: 檔案=%s, 從 %s 轉為 %s",
                file_path.name, source_encoding, target_encoding
            )
            with self._counter_lock:
                self.converted_count += 1
            return True

        except Exception as e:
            logger.error("編碼轉換 - 轉換失敗: 檔案=%s, 錯誤=%s", file_path.name, str(e))
            with self._counter_lock:
                self.failed_count += 1
            return False
    
    def convert_directory(
        self,
        directory: Path,
        pattern: str = '*.csv',
        recursive: bool = False,
        max_workers: int = 4
    ) -> Tuple[int, int, int]:
        """
        批次轉換目錄下的所有 CSV 檔案 (I/O bound，用執行緒池平行處理)

        Args:
            directory: 目錄路徑
            pattern: 檔案匹配模式 (預設: *.csv)
            recursive: 是否遞迴處理子目錄 (預設: False)
            max_workers: 平行處理的執行緒數量 (預設: 4)

        Returns:
            (轉換成功數, 跳過數, 失敗數)
        """
        # 重置計數器
        self.converted_count = 0
        self.skipped_count = 0
        self.failed_count = 0

        # 查找所有 CSV 檔案
        if recursive:
            csv_files = list(directory.rglob(pattern))
        else:
            csv_files = list(directory.glob(pattern))

        if not csv_files:
            logger.warning("編碼轉換 - 未找到檔案: 目錄=%s, 模式=%s", directory, pattern)
            return (0, 0, 0)

        logger.info(
            "編碼轉換 - 找到 %d 個 CSV 檔案,開始平行批次處理 (執行緒數=%d)",
            len(csv_files), max_workers
        )

        # 平行轉換 (各檔案獨立，計數器由 _counter_lock 保護)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.convert_to_utf8, csv_file): csv_file
                for csv_file in csv_files
            }
            for future in as_completed(futures):
                csv_file = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(
                        "編碼轉換 - 處理檔案發生未預期錯誤: 檔案=%s, 錯誤=%s",
                        csv_file.name, str(e)
                    )
                    with self._counter_lock:
                        self.failed_count += 1

        # 顯示統計
        logger.info("=" * 80)
        logger.info("編碼轉換統計摘要")
        logger.info("=" * 80)
        logger.info("%-30s: %10d", "轉換成功", self.converted_count)
        logger.info("%-30s: %10d", "跳過 (已是 UTF-8)", self.skipped_count)
        logger.info("%-30s: %10d", "轉換失敗", self.failed_count)
        logger.info("%-30s: %10d", "總計", len(csv_files))
        logger.info("=" * 80)
        
        return (self.converted_count, self.skipped_count, self.failed_count)
    
    def restore_backup(self, file_path: Path) -> bool:
        """
        從備份還原檔案
        
        Args:
            file_path: 要還原的檔案路徑
            
        Returns:
            還原成功返回 True,失敗返回 False
        """
        backup_path = file_path.with_suffix(file_path.suffix + '.bak')
        
        if not backup_path.exists():
            logger.error("編碼轉換 - 備份檔不存在: %s", backup_path)
            return False
        
        try:
            import shutil
            shutil.copy2(backup_path, file_path)
            logger.info("編碼轉換 - 還原成功: %s", file_path.name)
            return True
        except Exception as e:
            logger.error("編碼轉換 - 還原失敗: %s", str(e))
            return False
    
    def clean_backups(self, directory: Path, pattern: str = '*.csv.bak*') -> int:
        """
        清除所有備份檔案
        
        Args:
            directory: 目錄路徑
            pattern: 備份檔案匹配模式
            
        Returns:
            刪除的備份檔案數量
        """
        backup_files = list(directory.glob(pattern))
        
        if not backup_files:
            logger.info("編碼轉換 - 沒有找到備份檔案")
            return 0
        
        count = 0
        for backup_file in backup_files:
            try:
                backup_file.unlink()
                logger.debug("編碼轉換 - 刪除備份: %s", backup_file.name)
                count += 1
            except Exception as e:
                logger.error("編碼轉換 - 刪除備份失敗: 檔案=%s, 錯誤=%s", 
                           backup_file.name, str(e))
        
        logger.info("編碼轉換 - 清除完成,刪除 %d 個備份檔案", count)
        return count
    
    def get_stats(self) -> dict:
        """
        取得統計資訊
        
        Returns:
            統計資訊字典
        """
        return {
            'converted': self.converted_count,
            'skipped': self.skipped_count,
            'failed': self.failed_count,
            'total': self.converted_count + self.skipped_count + self.failed_count
        }


def convert_csv_encoding(
    csv_path: Path,
    backup: bool = False
) -> bool:
    """
    便捷函數: 轉換單一 CSV 檔案編碼為 UTF-8
    
    Args:
        csv_path: CSV 檔案路徑
        backup: 是否備份原始檔案
        
    Returns:
        轉換成功返回 True
    """
    converter = CSVEncodingConverter(backup=backup)
    return converter.convert_to_utf8(csv_path)


if __name__ == "__main__":
    # 測試程式
    import sys
    
    if len(sys.argv) < 2:
        print("使用方式: python csv_encoding_converter.py <csv_file_or_directory>")
        sys.exit(1)
    
    path = Path(sys.argv[1])
    converter = CSVEncodingConverter(backup=True)
    
    if path.is_file():
        # 轉換單一檔案
        success = converter.convert_to_utf8(path)
        print(f"轉換結果: {'成功' if success else '失敗'}")
    
    elif path.is_dir():
        # 批次轉換
        result = converter.convert_directory(path, recursive=False)
        print(f"轉換統計: 成功={result[0]}, 跳過={result[1]}, 失敗={result[2]}")
    
    else:
        print(f"錯誤: 路徑不存在 - {path}")
        sys.exit(1)