from DataPreprocessing import data_preprocessing
from GeovisioApi import create_collection, upload_images_to_geovisio, get_all_collections
import os
from pathlib import Path
import pandas as pd
from dotenv import load_dotenv
import pandas as pd
import io
from pathlib import Path
from tqdm import tqdm
from time import sleep
import time
from failures import upload_failures, collection_failures
import asyncio
import logging.config
import aiohttp
from logger import LOGGING_CONFIG
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)
load_dotenv()
TMS_GEOVISIO_URL = os.getenv("TMS_GEOVISIO_URL")
print(f"TMS_GEOVISIO_URL: {TMS_GEOVISIO_URL}")


def group_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group the data by the date portion of the GPSTime.
    """
    df['Date'] = df['GPSTime'].dt.date  # Extract the date part from GPSTime
    grouped_data = df.groupby('Date')
        
    return grouped_data


async def main():
    # csv_path = Path(r"E:\Peter\AIROADUpdate\data\標線型人行道\第一分案\Subproject_1_sidewalk_markline_part2.csv")  # Replace with your actual CSV file path
    csv_path = Path(r"E:\Peter\AIROADUpdate\data\10米以上道路\第二分案\景翊20250703_part2.csv")
    # Preprocess the data
    # If processing sidewalk markline data, set time threshold to 300 seconds and distance threshold to 20 meters
    # If processing 10 M width road data, set time threshold to 500 seconds and distance threshold to 200 meters
    prcocessed_data = data_preprocessing(csv_path, time_threshold=500, distance_threshold=200.0)
    # prcocessed_data.to_csv(csv_path.parent / f"{csv_path.stem}_processed_data.csv", index=False)
    grouped_data = group_by_date(prcocessed_data)
    num_dates = len(grouped_data)
    logger.info(f"Total number of unique dates in the dataset: {num_dates}")
    for date, group in grouped_data: # for date, group in grouped_data:
        logger.info(f"Processing data for date: {date}")
        if date.strftime('%Y-%m-%d') == "2025-06-18":
            logger.info(f"Skipping processing for {date}...")
            continue  # Skip processing for this date
        seq_data = group.groupby('group_id')
        logger.info(f"Number of sequences for {date}: {len(seq_data)}")
        count = 0
        for seq_id, seq in seq_data:
            logger.info(f"{count+1}/{len(seq_data)} Processing sequence ID: {seq_id} for date: {date}")
            # if date.strftime('%Y-%m-%d') == "2025-05-08" and seq_id == 0:
            #     logger.info(f"Skipping processing for {date} and sequence ID: {seq_id}...")
            #     continue
            seq = seq.sort_values(by='GPSTime')

            collection_id = await create_collection(
                title=f"交工案第一分案資料蒐集(10米以上道路) Date: {date}; Sequence ID: {seq_id}",
                description=f"Data collection for {date}; Sequence ID: {seq_id}",
                keywords=["交工案", "第一分案", "10米以上道路", "資料蒐集", f"Sequence ID:{seq_id}", f"日期:{date}"],
                )
        
            # collection_id = await create_collection(
            #     title=f"AIROAD台北案6月保固更新 Date: {date}; Sequence ID: {seq_id}",
            #     description=f"Data collection for {date}; Sequence ID: {seq_id}",
            #     keywords=["AIROAD", "台北案", "6月保固更新", "資料蒐集", f"Sequence ID:{seq_id}", f"日期:{date}"],
            #     )
            
            logger.debug(f"Created collection with ID: {collection_id}")
            logger.debug(f"title= 交工案第一分案資料蒐集(10米以上道路) Date: {date}; Sequence ID: {seq_id}")

            await upload_images_to_geovisio(seq, collection_id)
            
            await asyncio.sleep(3)
            count += 1
        await asyncio.sleep(600)
        

    if upload_failures:
        logger.error(f"Failed to upload {len(upload_failures)} images.")
        for failure in upload_failures:
            logger.error(f"Failed to upload image: {failure['image_name']} - Error: {failure['error']}")
        
        failure_df = pd.DataFrame(upload_failures)
        failure_csv_path = f"logs/{time.strftime('%Y-%m-%d_%H-%M-%S')}_failures.csv"
        failure_df.to_csv(failure_csv_path, index=False)

    if collection_failures:
        logger.error(f"Failures occurred in {len(collection_failures)} collections.")
        for collection_id in collection_failures:
            logger.error(f"Collection with failures: {collection_id}")

        collections_df = pd.DataFrame({"collection_id": list(collection_failures)})
        collections_csv_path = f"logs/{time.strftime('%Y-%m-%d_%H-%M-%S')}_failed_collections.csv"
        collections_df.to_csv(collections_csv_path, index=False)
        logger.error(f"Failed collections saved to {collections_csv_path}")

    else:
        logger.info("All images uploaded successfully.")


    


if __name__ == "__main__":
    asyncio.run(main())

    # Uncomment the following lines to run the other functions
    # create_collection()
    # upload_images_to_geovisio()
    # get_all_collections()