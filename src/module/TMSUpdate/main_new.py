import os
import sys
import time
import asyncio
import datetime
import logging.config
from pathlib import Path
from typing import Dict, Any, Optional
import pandas as pd
from EncodingConvertor import convert_csv_encoding
from dotenv import load_dotenv

# 導入自定義模組
from DataPreprocessing import data_preprocessing
from GeovisioApi_new import create_collection, upload_images_to_geovisio, get_all_collections
from failures import upload_failures, collection_failures
from logger import LOGGING_CONFIG

# ========================================
# 導入新的功能模組
# ========================================
from deduplication import dedup_checker
from resource_monitor import simple_resource_monitor
from large_sequence_handler import large_seq_handler

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)
load_dotenv()

# 環境變數
TMS_GEOVISIO_URL = os.getenv("TMS_GEOVISIO_URL")
CSV_FILE_PATH = os.getenv("CSV_FILE_PATH")
SEQUENCE_DELAY = int(os.getenv("SEQUENCE_DELAY", "3"))
BATCH_DELAY = int(os.getenv("BATCH_DELAY", "300"))
VEHICLE_TYPE = os.getenv("VEHICLE_TYPE", "CAR")

# 功能開關
ENABLE_DEDUPLICATION = os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true"
ENABLE_RESOURCE_MONITOR = os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"


def validate_env() -> None:
    """
    檢查環境變數是否有效。
    
    異常
    ------
    ValueError
        如果 TMS_GEOVISIO_URL 或 CSV_PATH 未在環境變數中設定。
    TypeError
        如果 TMS_GEOVISIO_URL 或 CSV_PATH 不是字串型別。
    OSError
        如果建立日誌目錄失敗。
    """
    if TMS_GEOVISIO_URL is None:
        raise ValueError(
            "TMS_GEOVISIO_URL is not set in the environment variables.")
    
    if not isinstance(TMS_GEOVISIO_URL, str):
        raise TypeError(
            "TMS_GEOVISIO_URL must be a string.")
    
    if CSV_FILE_PATH is None:
        raise ValueError(
            "CSV_PATH is not set in the environment variables.")
    
    if not isinstance(CSV_FILE_PATH, str):
        raise TypeError(
            "CSV_PATH must be a string.")
    
    logs_dir = Path("logs")
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error(f"Failed to create logs directory: {e}")
        raise OSError(
            f"Failed to create logs directory: {e}") from e


def group_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    按照 'GPSTime' 欄位的日期部分對 DataFrame 進行分組。

    參數
    ----------
    df : pd.DataFrame
        需要按日期分組的 DataFrame。

    返回值
    -------
    pd.DataFrame
        已分組的 DataFrame。

    異常
    ------
    KeyError
        如果在 DataFrame 中找不到 'GPSTime' 欄位。
    ValueError
        如果 'GPSTime' 欄位無法轉換為日期時間型別。
    TypeError
        如果 'GPSTime' 欄位不是日期時間型別。
    Exception
        如果處理 'GPSTime' 欄位時發生其他錯誤。
    """
    if 'GPSTime' not in df.columns:
        raise KeyError("Column 'GPSTime' not found in the DataFrame.")

    try:
        if not pd.api.types.is_datetime64_any_dtype(df['GPSTime']):
            df['GPSTime'] = pd.to_datetime(df['GPSTime'], errors='coerce')

        # Extract the date part from GPSTime
        df['Date'] = df['GPSTime'].dt.date
        grouped_data = df.groupby('Date')
        logger.info(f"Data grouped into {len(grouped_data)} unique dates")
        return grouped_data

    except KeyError as e:
        logger.error(f"Error: {e}")
        raise
    except ValueError as e:
        logger.error(f"Error: {e}")
        raise
    except TypeError as e:
        logger.error(f"Error: {e}")
        raise
    except Exception as e:
        logger.error(f"Error: {e}")
        raise ValueError(f"Failed to process GPSTime column: {e}") from e


def should_skip_date(collection_date: datetime.date, cut_off_date: datetime.date) -> bool:
    """
    根據截止日期檢查是否應該跳過指定的集合日期。

    參數
    ----------
    collection_date : datetime.date
        要檢查的集合日期。
    cut_off_date : datetime.date
        用於比較的截止日期。

    返回值
    -------
    bool
        如果應該跳過集合日期則返回 True,否則返回 False。

    異常
    ------
    TypeError
        如果 collection_date 或 cut_off_date 不是 datetime.date 物件。
    """

    if cut_off_date is None:
        cut_off_date = datetime.datetime.now().date()
    if not isinstance(collection_date, datetime.date):
        raise TypeError("collection_date must be a datetime.date object")
    if not isinstance(cut_off_date, datetime.date):
        raise TypeError("cut_off_date must be a datetime.date object")

    skip = collection_date < cut_off_date
    if skip:
        logger.info(
            f"Skipping processing for {collection_date} (before {cut_off_date})")
    return skip


async def upload_single_sequence(seq_data, seq_id, collection_date, seq_count, total_seq):
    """
    處理單個序列並將其上傳到 GeoVisio。

    參數
    ----------
    seq_data : pd.DataFrame
        要處理的序列資料。
    seq_id : str
        要處理的序列 ID。
    collection_date : datetime.date
        序列的集合日期。
    seq_count : int
        序列計數(從 1 開始)。
    total_seq : int
        總序列數。

    返回值
    -------
    str or None
        如果上傳成功則返回集合 ID,否則返回 None。

    異常
    ------
    TypeError
        如果 seq_data、seq_id、collection_date、seq_count 或 total_seq 型別不正確。
    Exception
        如果處理序列時發生其他錯誤。
    """
    try:
        logger.info(
            f"{seq_count}/{total_seq} Processing sequence ID: {seq_id} for date: {collection_date}")
        seq_sorted_data = seq_data.sort_values(by='GPSTime')

        if seq_sorted_data is None or seq_sorted_data.empty:
            logger.error(
                f"Skipping sequence ID: {seq_id} for date: {collection_date} due to empty data")
            return None

        title = f"交工案第一分案資料蒐集(10米以上道路) Date: {collection_date}; Sequence ID: {seq_id}"
        description = f"Data collection for {collection_date}; Sequence ID: {seq_id}"
        keywords = [
            "交工案", "第一分案", "10米以上道路", "資料蒐集",
            f"Sequence ID:{seq_id}", f"日期:{collection_date}"
        ]

        collection_id = await create_collection(
            title=title,
            description=description,
            keywords=keywords
        )

        if not collection_id:
            logger.error(
                f"Failed to create collection for sequence ID: {seq_id} for date: {collection_date}")
            return None

        logger.debug(
            f"Created collection with ID: {collection_id}")
        logger.debug(f"Title: {title}")

        # ========================================
        # 上傳影像 (已整合資源監控和大型序列處理)
        # ========================================
        uploaded_result = await upload_images_to_geovisio(seq_sorted_data, collection_id)

        if uploaded_result and uploaded_result.get("successful", 0) > 0:
            successful = uploaded_result["successful"]
            failed = uploaded_result["failed"]
            logger.info(f"Successfully uploaded sequence ID: {seq_id} for date: {collection_date}")
            logger.info(f"Upload result: {successful} successful, {failed} failed")
        else:
            logger.error(f"Failed to upload sequence ID: {seq_id} for date: {collection_date}")
            if uploaded_result:
                logger.error(f"Upload result: {uploaded_result}")

        return collection_id

    except TypeError as e:
        logger.error(
            f"Error processing sequence ID: {seq_id} for date: {collection_date}: {e}")
        raise TypeError(f"Error processing sequence ID: {seq_id} for date: {collection_date}: {e}") from e
    except Exception as e:
        logger.error(
            f"Error processing sequence ID: {seq_id} for date: {collection_date}: {e}")
        raise Exception(f"Error processing sequence ID: {seq_id} for date: {collection_date}: {e}") from e


async def upload_date_group(collection_date, group_data):
    """
    上傳單日的資料到 GeoVisio

    參數
    ----------
    collection_date : datetime.date
        上傳的日期
    group_data : pd.DataFrame
        上傳的資料(已經過分組)

    返回值
    -------
    dict
        上傳結果的字典

    異常
    ------
    TypeError
        group_data 不是 pandas.DataFrame
    ValueError
        group_data 中找不到 'group_id' 欄
    """
    logger.info(f"Processing data for date: {collection_date}")

    if should_skip_date(collection_date, datetime.date(2025, 6, 1)):
        logger.info(
            f"Skipping processing for {collection_date}")
        return

    if not isinstance(group_data, pd.DataFrame):
        raise TypeError("group_data must be a pandas DataFrame")

    if 'group_id' not in group_data.columns:
        raise ValueError("Column 'group_id' not found in the DataFrame")

    seq_data_groups = group_data.groupby('group_id')
    total_seq = len(seq_data_groups)

    if total_seq == 0:
        logger.warning(f"No sequences found for date: {collection_date}")
        return

    logger.info(
        f"Number of sequences for {collection_date}: {total_seq}")

    successful_seq = 0
    failed_seq = 0

    for count, (seq_id, seq_data) in enumerate(seq_data_groups, 1):
        try:
            collection_id = await upload_single_sequence(
                seq_data, seq_id, collection_date, count, total_seq
            )

            if collection_id:
                successful_seq += 1
            else:
                failed_seq += 1

            # Sequence 間延遲
            if count < total_seq:
                await asyncio.sleep(SEQUENCE_DELAY)

        except Exception as e:
            logger.error(
                f"Error processing sequence ID: {seq_id} for date: {collection_date}: {e}",
                exc_info=True
            )
            failed_seq += 1

    result = {
        "date": collection_date,
        "total_seq": total_seq,
        "successful_seq": successful_seq,
        "failed_seq": failed_seq
    }

    logger.info(
        f"Date {collection_date} completed: {successful_seq}/{total_seq} sequences successful")

    return result


async def save_failure_reports():
    """
    保存上傳過程的失敗報告。

    此函數保存兩種類型的失敗報告:上傳失敗和集合失敗。
    上傳失敗會保存在名為 `<時間戳>_upload_failures.csv` 的 CSV 檔案中。
    集合失敗會保存在名為 `<時間戳>_failed_collections.csv` 的 CSV 檔案中。
    此函數還會在日誌記錄器中記錄失敗情況。

    參數
    ----------
    無

    返回值
    -------
    無
    """

    timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')

    # 保存上傳失敗記錄
    if upload_failures is not None and len(upload_failures) > 0:
        logger.error(f"Failed to upload {len(upload_failures)} images.")

        failure_df = pd.DataFrame(upload_failures)
        failure_csv_path = os.path.join(
            "logs", f"{timestamp}_upload_failures.csv")
        try:
            failure_df.to_csv(failure_csv_path, index=False)
        except Exception as e:
            logger.error(
                f"Failed to save upload failures to {failure_csv_path}: {e}")

        # 詳細列出前10個失敗案例
        for i, failure in enumerate(upload_failures[:10], 1):
            logger.error(f"Upload failure {i}: {failure}")

        if len(upload_failures) > 10:
            logger.error(
                f"... and {len(upload_failures) - 10} more upload failures")

    # 保存集合失敗記錄
    if collection_failures is not None and len(collection_failures) > 0:
        logger.error(
            f"Failures occurred in {len(collection_failures)} collections.")

        try:
            collections_df = pd.DataFrame(
                {"collection_id": list(collection_failures)})
            collections_csv_path = Path(
                "logs") / f"{timestamp}_failed_collections.csv"
            collections_df.to_csv(collections_csv_path, index=False)
        except Exception as e:
            logger.error(
                f"Failed to save failed collections to {collections_csv_path}: {e}")

        # 列出所有失敗的集合
        for collection_id in collection_failures:
            logger.error(f"Collection with failures: {collection_id}")

    if (upload_failures is None or len(upload_failures) == 0) and (collection_failures is None or len(collection_failures) == 0):
        logger.info("All operations completed successfully with no failures.")


async def main():
    """
    腳本的主要入口點。

    此函數處理環境變數 CSV_PATH 中指定的 CSV 檔案,對資料進行前處理,
    並使用 API 將資料上傳到 GeoVision。

    此函數會記錄處理進度並將結果保存到 CSV 檔案中。

    參數
    ----------
    無

    返回值
    -------
    無
    """
    start_time = time.time()

    # ========================================
    # 初始化新功能模組
    # ========================================
    try:
        # 初始化去重檢查器
        if ENABLE_DEDUPLICATION:
            await dedup_checker.initialize()
            logger.info("✅ 去重檢查器初始化完成")
        
        # 初始化資源監控器
        if ENABLE_RESOURCE_MONITOR:
            await simple_resource_monitor.initialize()
            logger.info("✅ 資源監控器初始化完成")

    except Exception as e:
        logger.error(f"❌ 模組初始化失敗: {e}")
        logger.warning("⚠️  將繼續執行,但相關功能將被停用")

    try:
        validate_env()

        csv_path = Path(CSV_FILE_PATH)
        convert_csv_encoding(csv_path, backup=False)
        if not csv_path.exists():
            raise FileNotFoundError(f"The file {csv_path} does not exist.")

        logger.info(f"Processing CSV file: {csv_path}")

        logger.info("Starting data preprocessing...")
        
        # If processing sidewalk markline data, set time threshold to 300 seconds and distance threshold to 20 meters
        # If processing 10 M width road data, set time threshold to 500 seconds and distance threshold to 200 meters
        if VEHICLE_TYPE == "CAR":
            processed_data = data_preprocessing(csv_path, time_threshold=500, distance_threshold=200.0)
        elif VEHICLE_TYPE == 'MOTORCYCLE':
            processed_data = data_preprocessing(csv_path, time_threshold=300, distance_threshold=20.0)

        if processed_data.empty:
            logger.warning("No data to process.")
            return

        grouped_data = group_by_date(processed_data)
        num_dates = len(grouped_data)

        logger.info(
            f"Total number of unique dates in the dataset: {num_dates}")

        date_results = []
        for date_count, (collection_date, group) in enumerate(grouped_data, 1):
            logger.info(
                f"Processing date {date_count}/{num_dates}: {collection_date}")

            try:
                result = await upload_date_group(collection_date, group)
                if result is not None:
                    date_results.append(result)

                if date_count < num_dates:
                    logger.info(
                        f"Waiting {BATCH_DELAY} seconds before next date...")
                    await asyncio.sleep(BATCH_DELAY)

            except Exception as e:
                logger.error(f"Error processing date {collection_date}: {e}")
                date_results.append({
                    "date": collection_date,
                    "successful_seq": 0,
                    "total_seq": 0,
                    "failed_seq": 0,
                    "error": str(e)
                })

        # ========================================
        # 生成最終統計報告
        # ========================================
        total_sequences_processed = sum(r.get("successful_seq", 0) for r in date_results) 
        total_sequences = sum(r.get("total_seq", 0) for r in date_results)

        logger.info("=" * 60)
        logger.info("FINAL PROCESSING SUMMARY")
        logger.info("=" * 60)
        logger.info(
            f"Total dates processed: {len([r for r in date_results if not r.get('skipped', False)])}")
        logger.info(
            f"Total sequences processed: {total_sequences_processed}/{total_sequences}")
        logger.info(f"Upload failures: {len(upload_failures)}")
        logger.info(f"Collection failures: {len(collection_failures)}")

        # ========================================
        # 顯示去重統計
        # ========================================
        if ENABLE_DEDUPLICATION:
            dedup_checker.print_stats()

        # 保存失敗報告
        await save_failure_reports()

        # 保存處理結果統計
        results_df = pd.DataFrame(date_results)
        timestamp = time.strftime('%Y-%m-%d_%H-%M-%S')
        results_path = Path("logs") / f"{timestamp}_processing_results.csv"
        results_df.to_csv(results_path, index=False)
        logger.info(f"Processing results saved to {results_path}")

        elapsed_time = time.time() - start_time
        logger.info(f"Total processing time: {elapsed_time:.2f} seconds")

    except Exception as e:
        logger.error(f"Fatal error in main process: {e}")
        raise

    finally:
        # ========================================
        # 關閉所有模組
        # ========================================
        try:
            if ENABLE_DEDUPLICATION:
                await dedup_checker.close()
                logger.info("✅ 去重檢查器已關閉")
            
            if ENABLE_RESOURCE_MONITOR:
                await simple_resource_monitor.close()
                logger.info("✅ 資源監控器已關閉")
        
        except Exception as e:
            logger.error(f"❌ 模組關閉時發生錯誤: {e}")


if __name__ == "__main__":
    asyncio.run(main())