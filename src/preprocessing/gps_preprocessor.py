"""
GPS 資料預處理模組

功能:
1. 從 KeyName 解析 GPS 時間
2. 計算相鄰影像的時間差
3. 計算相鄰影像的距離差 (TWD97 座標系統)
4. 根據時間和距離閾值分割序列

優化重點:
- 統一中文日誌訊息
- 清楚的日誌等級分類
- 完善的錯誤處理
"""

import pandas as pd
from pathlib import Path
import numpy as np
from datetime import datetime, timezone
from pyproj import Transformer
import logging

logger = logging.getLogger(__name__)


class GPSDataPreprocessor:
    """
    GPS 資料預處理器
    
    處理原始 CSV 資料,提取 GPS 資訊並根據時間和距離
    閾值將資料分割成獨立的序列。
    
    Attributes:
        time_threshold: 時間閾值 (秒)
        distance_threshold: 距離閾值 (公尺)
    """
    
    def __init__(self, time_threshold: int = 300, distance_threshold: float = 20.0):
        """
        初始化預處理器
        
        Args:
            time_threshold: 時間閾值 (秒,預設: 300)
            distance_threshold: 距離閾值 (公尺,預設: 20.0)
        """
        self.time_threshold = time_threshold
        self.distance_threshold = distance_threshold
        
        logger.info(
            "資料預處理 - 初始化完成: 影像間隔時間閾值=%d 秒, 影像間隔距離距離閾值=%.1f 公尺",
            time_threshold, distance_threshold
        )
    
    def parse_keyname_to_gpstime(self, keyname: str) -> str:
        """
        從 KeyName 解析 GPS 時間
        
        KeyName 格式: YYYYMMDDHHMMSSMMM_XXXXXXXXX
        例如: 20250618093828079_S9D3DPLAR
        
        Args:
            keyname: 影像的 KeyName
            
        Returns:
            ISO 8601 格式的 GPS 時間字串,失敗返回 None
        """
        try:
            # 提取時間戳記
            timestamp_str = keyname.split('_')[0]
            
            # 轉換為 datetime 物件
            # 格式: YYYYMMDDHHMMSSMMM (17 位數字)
            dt = datetime.strptime(
                timestamp_str[:-3] + timestamp_str[-3:] + '000',
                "%Y%m%d%H%M%S%f"
            )
            
            # 設定時區為 UTC
            dt_utc = dt.replace(tzinfo=timezone.utc)
            
            # 轉換為 ISO 8601 格式
            gps_time = dt_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            
            return gps_time
            
        except Exception as e:
            logger.error(
                "資料預處理 - 時間格式解析失敗: KeyName=%s, 錯誤=%s",
                keyname, str(e)
            )
            return None
    
    def calculate_time_differences(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算相鄰影像的時間差
        
        Args:
            df: 包含 GPSTime 欄位的 DataFrame
            
        Returns:
            新增 GPSTime_diff 欄位的 DataFrame
        """
        logger.debug("資料預處理 - 開始計算影像間時間差")
        
        # 按時間排序
        df = df.sort_values(by='GPSTime')
        
        # 轉換為 datetime 型別
        df['GPSTime'] = pd.to_datetime(
            df['GPSTime'],
            format="%Y-%m-%dT%H:%M:%S.%fZ",
            errors='coerce'
        )
        
        # 計算時間差 (秒)
        df['GPSTime_diff'] = (
            df['GPSTime'] - df['GPSTime'].shift()
        ).dt.total_seconds()
        
        # 第一筆資料的時間差設為 0
        df.loc[df.index[0], 'GPSTime_diff'] = 0.0
        
        logger.info("資料預處理 - 時間差計算完成")
        return df
    
    def calculate_distance_differences(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        計算相鄰影像的距離差 (使用 TWD97 座標系統)
        
        將 WGS84 座標 (經緯度) 轉換為 TWD97 座標 (平面座標),
        然後計算歐式距離。
        
        Args:
            df: 包含 GPS_X (經度) 和 GPS_Y (緯度) 欄位的 DataFrame
            
        Returns:
            新增 distance_to_prev 欄位的 DataFrame
        """
        logger.debug("資料預處理 - 開始計算影像間距離差")

        # 建立座標轉換器 (WGS84 → TWD97)
        transformer = Transformer.from_crs(
            "epsg:4326",  # WGS84 (經緯度)
            "epsg:3826",  # TWD97 (平面座標)
            always_xy=True
        )

        # 按時間排序
        df = df.sort_values(by='GPSTime')

        # 向量化座標轉換 (一次轉換整欄，取代逐列 apply)
        x, y = transformer.transform(df['GPS_X'].to_numpy(), df['GPS_Y'].to_numpy())
        df['X_TWD97'] = x
        df['Y_TWD97'] = y

        invalid_mask = ~np.isfinite(df['X_TWD97']) | ~np.isfinite(df['Y_TWD97'])
        if invalid_mask.any():
            logger.error(
                "資料預處理 - 座標轉換失敗: %d 筆 (經緯度超出範圍或無效)",
                int(invalid_mask.sum())
            )

        # 取得前一筆資料的座標
        df['X_prev'] = df['X_TWD97'].shift()
        df['Y_prev'] = df['Y_TWD97'].shift()

        # 向量化計算到前一點的距離 (歐式距離)，第一筆 (無前一點) 設為 0
        distance = np.sqrt(
            (df['X_TWD97'] - df['X_prev']) ** 2 +
            (df['Y_TWD97'] - df['Y_prev']) ** 2
        ).round(3)
        df['distance_to_prev'] = distance.fillna(0.0)

        # 移除暫存欄位
        df = df.drop(columns=['X_prev', 'Y_prev'])

        logger.info("資料預處理 - 距離差計算完成")
        return df
    
    def split_into_sequences(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        根據時間和距離閾值分割序列
        
        當相鄰影像的時間差或距離差超過閾值時,
        視為新序列的開始。
        
        Args:
            df: 包含 GPSTime_diff 和 distance_to_prev 欄位的 DataFrame
            
        Returns:
            新增 group_id 欄位的 DataFrame
        """
        logger.debug("資料預處理 - 開始分割序列")

        df = df.copy()
        df = df.sort_values(by='GPSTime')

        # 向量化判斷每一列是否需要分割 (取代逐列 iterrows)
        time_exceeded = df['GPSTime_diff'] > self.time_threshold
        distance_exceeded = df['distance_to_prev'] > self.distance_threshold
        split_mask = time_exceeded | distance_exceeded

        if len(split_mask) > 0:
            split_mask.iloc[0] = False  # 第一筆一定是序列起點，不分割

        # 只對實際發生分割的列印 debug log，不逐列印
        for idx in df.index[split_mask]:
            if time_exceeded.loc[idx]:
                logger.debug(
                    "資料預處理 - 時間閾值超過,分割序列: 索引=%s, 時間差=%.1f 秒",
                    idx, df.loc[idx, 'GPSTime_diff']
                )
            if distance_exceeded.loc[idx]:
                logger.debug(
                    "資料預處理 - 距離閾值超過,分割序列: 索引=%s, 距離=%.1f 公尺",
                    idx, df.loc[idx, 'distance_to_prev']
                )

        df['group_id'] = split_mask.cumsum()

        num_groups = df['group_id'].nunique()
        logger.info(
            "資料預處理 - 序列分割完成: 共 %d 個序列",
            num_groups
        )
        
        return df
    
    def preprocess(self, csv_path: Path) -> pd.DataFrame:
        """
        主要預處理流程
        
        完整的預處理步驟:
        1. 讀取 CSV 檔案
        2. 移除重複的 KeyName
        3. 解析 GPS 時間
        4. 計算時間差
        5. 計算距離差
        6. 分割序列
        
        Args:
            csv_path: CSV 檔案路徑
            
        Returns:
            處理後的 DataFrame
            
        Raises:
            FileNotFoundError: 檔案不存在
        """
        logger.info("資料預處理 - 開始處理: %s", csv_path)
        
        # ========================================
        # 1. 讀取 CSV 檔案
        # ========================================
        if not csv_path.exists():
            logger.error("資料預處理 - 檔案不存在: %s", csv_path)
            raise FileNotFoundError(f"檔案不存在: {csv_path}")
        
        df = pd.read_csv(
            csv_path,
            encoding='cp950',
            encoding_errors='replace'
        )
        
        logger.info("資料預處理 - 讀取完成: 總筆數=%d", len(df))
        
        # ========================================
        # 2. 移除重複的 KeyName
        # ========================================
        original_count = len(df)
        # 使用 .copy() 建立獨立副本，避免 SettingWithCopyWarning
        df_unique = df.drop_duplicates(subset=['KeyName'], keep='first').copy()
        duplicate_count = original_count - len(df_unique)
        
        if duplicate_count > 0:
            logger.warning(
                "資料預處理 - 移除重複 KeyName: %d 筆 (剩餘 %d 筆)",
                duplicate_count, len(df_unique)
            )
        else:
            logger.info("資料預處理 - 無重複 KeyName")
        
        # ========================================
        # 3. 解析 GPS 時間
        # ========================================
        df_unique['GPSTime'] = df_unique['KeyName'].apply(
            self.parse_keyname_to_gpstime
        )
        
        null_count = df_unique['GPSTime'].isnull().sum()
        if null_count > 0:
            logger.warning(
                "資料預處理 - GPS 時間解析失敗: %d 筆",
                null_count
            )
        
        # ========================================
        # 4. 計算時間差
        # ========================================
        df_unique = self.calculate_time_differences(df_unique)
        
        # ========================================
        # 5. 計算距離差
        # ========================================
        df_unique = self.calculate_distance_differences(df_unique)
        
        # ========================================
        # 6. 分割序列
        # ========================================
        df_unique = self.split_into_sequences(df_unique)
        
        # ========================================
        # 7. 檢查異常值
        # ========================================
        abnormal_time = (df_unique['GPSTime_diff'] > self.time_threshold).sum()
        if abnormal_time > 0:
            logger.warning(
                "資料預處理 - 發現時間間隔異常: %d 筆 (超過 %d 秒)",
                abnormal_time, self.time_threshold
            )
        
        # ========================================
        # 8. 選擇輸出欄位
        # ========================================
        required_cols = ['KeyName', 'GPSTime', 'GPSTime_diff', 'GPS_X', 'GPS_Y', 
                 'distance_to_prev', 'group_id']
        optional_cols = ['speed', 'url', 'X_TWD97', 'Y_TWD97']

        # 只選取存在的欄位
        output_cols = required_cols + [col for col in optional_cols if col in df_unique.columns]

        df_result = df_unique[output_cols]
        
        logger.info(
            "資料預處理 - 處理完成: 輸出 %d 筆資料, %d 個序列",
            len(df_result), df_result['group_id'].nunique()
        )
        
        return df_result


def data_preprocessing(
    csv_path: Path,
    time_threshold: int = 300,
    distance_threshold: float = 20.0
) -> pd.DataFrame:
    """
    便捷函數: GPS 資料預處理
    
    Args:
        csv_path: CSV 檔案路徑
        time_threshold: 時間閾值 (秒)
        distance_threshold: 距離閾值 (公尺)
        
    Returns:
        處理後的 DataFrame
    """
    preprocessor = GPSDataPreprocessor(time_threshold, distance_threshold)
    return preprocessor.preprocess(csv_path)


if __name__ == "__main__":
    # 測試程式
    import sys
    
    if len(sys.argv) < 2:
        print("使用方式: python gps_preprocessor.py <csv_file>")
        sys.exit(1)
    
    csv_path = Path(sys.argv[1])
    
    # 執行預處理
    df = data_preprocessing(
        csv_path,
        time_threshold=300,
        distance_threshold=20.0
    )
    
    # 顯示結果
    print(f"\n處理結果:")
    print(f"總筆數: {len(df)}")
    print(f"序列數: {df['group_id'].nunique()}")
    print(f"\n前 5 筆資料:")
    print(df.head())
    
    # 儲存結果
    output_path = csv_path.parent / f"processed_{csv_path.name}"
    df.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"\n已儲存至: {output_path}")