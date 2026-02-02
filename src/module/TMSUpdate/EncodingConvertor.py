"""
CSV 編碼統一轉換工具

功能:
1. 自動偵測 CSV 檔案編碼
2. 統一轉換為 UTF-8 (無 BOM)
3. 支援批次處理
4. 備份原始檔案
"""

import os
import chardet
from pathlib import Path
from typing import List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


class CSVEncodingConverter:
    """CSV 編碼轉換器"""
    
    def __init__(self, backup: bool = True):
        """
        初始化轉換器
        
        Parameters
        ----------
        backup : bool
            是否備份原始檔案 (預設: True)
        """
        self.backup = backup
        self.converted_count = 0
        self.failed_count = 0
        self.skipped_count = 0
    
    def detect_encoding(self, file_path: Path) -> Optional[str]:
        """
        偵測檔案編碼
        
        Parameters
        ----------
        file_path : Path
            檔案路徑
            
        Returns
        -------
        str or None
            偵測到的編碼,失敗返回 None
        """
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                confidence = result['confidence']
                
                logger.debug(
                    f"檔案: {file_path.name} | "
                    f"偵測編碼: {encoding} | "
                    f"信心度: {confidence:.2%}"
                )
                
                return encoding
                
        except Exception as e:
            logger.error(f"偵測編碼失敗 ({file_path.name}): {e}")
            return None
    
    def convert_to_utf8(
        self, 
        file_path: Path, 
        source_encoding: Optional[str] = None,
        target_encoding: str = 'utf-8'
    ) -> bool:
        """
        轉換檔案編碼為 UTF-8
        
        Parameters
        ----------
        file_path : Path
            檔案路徑
        source_encoding : str, optional
            來源編碼,如果為 None 則自動偵測
        target_encoding : str
            目標編碼 (預設: utf-8,不含 BOM)
            
        Returns
        -------
        bool
            轉換成功返回 True,失敗返回 False
        """
        try:
            # 偵測或使用指定的來源編碼
            if source_encoding is None:
                source_encoding = self.detect_encoding(file_path)
                
                if source_encoding is None:
                    logger.error(f"無法偵測編碼: {file_path.name}")
                    return False
            
            # 如果已經是目標編碼,跳過
            if source_encoding.lower().replace('-', '') == target_encoding.lower().replace('-', ''):
                # 但要檢查是否有 BOM
                with open(file_path, 'rb') as f:
                    header = f.read(3)
                    
                if header == b'\xef\xbb\xbf':
                    # 有 BOM,需要移除
                    logger.info(f"移除 BOM: {file_path.name}")
                else:
                    # 已經是 UTF-8 且無 BOM,跳過
                    logger.debug(f"跳過 (已是 UTF-8): {file_path.name}")
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
                logger.debug(f"備份: {backup_path.name}")
            
            # 讀取原始內容
            with open(file_path, 'r', encoding=source_encoding, errors='replace') as f:
                content = f.read()
            
            # 寫入 UTF-8 (無 BOM)
            with open(file_path, 'w', encoding=target_encoding, newline='') as f:
                f.write(content)
            
            logger.info(
                f"✅ 轉換成功: {file_path.name} "
                f"({source_encoding} → {target_encoding})"
            )
            self.converted_count += 1
            return True
            
        except Exception as e:
            logger.error(f"❌ 轉換失敗 ({file_path.name}): {e}")
            self.failed_count += 1
            return False
    
    def convert_directory(
        self, 
        directory: Path,
        pattern: str = '*.csv',
        recursive: bool = False
    ) -> Tuple[int, int, int]:
        """
        批次轉換目錄下的所有 CSV 檔案
        
        Parameters
        ----------
        directory : Path
            目錄路徑
        pattern : str
            檔案匹配模式 (預設: *.csv)
        recursive : bool
            是否遞迴處理子目錄 (預設: False)
            
        Returns
        -------
        tuple
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
            logger.warning(f"未找到 CSV 檔案: {directory}")
            return (0, 0, 0)
        
        logger.info(f"找到 {len(csv_files)} 個 CSV 檔案")
        logger.info(f"開始批次轉換...")
        
        # 逐個轉換
        for csv_file in csv_files:
            logger.info(f"處理: {csv_file.name}")
            self.convert_to_utf8(csv_file)
        
        # 顯示統計
        logger.info("=" * 60)
        logger.info(f"📊 轉換統計:")
        logger.info(f"  ✅ 成功轉換: {self.converted_count} 個")
        logger.info(f"  ⏭️  跳過 (已是 UTF-8): {self.skipped_count} 個")
        logger.info(f"  ❌ 失敗: {self.failed_count} 個")
        logger.info(f"  📁 總計: {len(csv_files)} 個")
        logger.info("=" * 60)
        
        return (self.converted_count, self.skipped_count, self.failed_count)
    
    def restore_backup(self, file_path: Path) -> bool:
        """
        從備份還原檔案
        
        Parameters
        ----------
        file_path : Path
            要還原的檔案路徑
            
        Returns
        -------
        bool
            還原成功返回 True,失敗返回 False
        """
        backup_path = file_path.with_suffix(file_path.suffix + '.bak')
        
        if not backup_path.exists():
            logger.error(f"備份檔不存在: {backup_path}")
            return False
        
        try:
            import shutil
            shutil.copy2(backup_path, file_path)
            logger.info(f"✅ 還原成功: {file_path.name}")
            return True
        except Exception as e:
            logger.error(f"❌ 還原失敗: {e}")
            return False
    
    def clean_backups(self, directory: Path, pattern: str = '*.csv.bak*') -> int:
        """
        清除所有備份檔案
        
        Parameters
        ----------
        directory : Path
            目錄路徑
        pattern : str
            備份檔案匹配模式
            
        Returns
        -------
        int
            刪除的備份檔案數量
        """
        backup_files = list(directory.glob(pattern))
        
        if not backup_files:
            logger.info("沒有找到備份檔案")
            return 0
        
        count = 0
        for backup_file in backup_files:
            try:
                backup_file.unlink()
                logger.debug(f"刪除備份: {backup_file.name}")
                count += 1
            except Exception as e:
                logger.error(f"刪除失敗 ({backup_file.name}): {e}")
        
        logger.info(f"✅ 清除 {count} 個備份檔案")
        return count


def convert_csv_encoding(
    csv_path: Path,
    backup: bool = False
) -> bool:
    """
    便捷函數: 轉換單一 CSV 檔案編碼為 UTF-8
    
    Parameters
    ----------
    csv_path : Path
        CSV 檔案路徑
    backup : bool
        是否備份原始檔案
        
    Returns
    -------
    bool
        轉換成功返回 True
    """
    converter = CSVEncodingConverter(backup=backup)
<<<<<<< HEAD
    return converter.convert_to_utf8(csv_path)
=======
    return converter.convert_to_utf8(csv_path)
>>>>>>> a809647091b7b0a0f46fbbf971c62d19cc5c9b27
