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
from failures import upload_failures
import asyncio
import logging.config
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
    csv_path = Path(r"D:\MyProject\AIROADUpdate\data\raw\Subproject_1_sidewalk_markline.csv")  # Replace with your actual CSV file path

    prcocessed_data = data_preprocessing(csv_path)
    grouped_data = group_by_date(prcocessed_data)

    for date, group in grouped_data: # for date, group in grouped_data:
        logger.info(f"Processing data for date: {date}")
        if date.strftime('%Y-%m-%d') == "2025-05-22" or date.strftime('%Y-%m-%d') == "2025-05-23" or date.strftime('%Y-%m-%d') == "2025-05-27":
            logger.info(f"Skipping processing for {date}...")
            continue  # Skip processing for this date
        seq_data = group.groupby('group_id')

        for seq_id, seq in seq_data:
            seq = seq.sort_values(by='GPSTime')

            collection_id = await create_collection(
                title=f"交工案第一分案資料蒐集(標人)",
                description=f"Data collection for {date}; Sequence ID: {seq_id}",
                keywords=["交工案", "第一分案", "標人", "資料蒐集", f"Sequence ID:{seq_id}", f"日期:{date}"],
                )
            
            logger.debug(f"Created collection with ID: {collection_id}")

            await upload_images_to_geovisio(seq, collection_id)
            
            await asyncio.sleep(10)
        await asyncio.sleep(10)
        

    if upload_failures:
        logger.error(f"Failed to upload {len(upload_failures)} images.")
        for failure in upload_failures:
            logger.error(f"Failed to upload image: {failure['image_name']} - Error: {failure['error']}")
        
        failure_df = pd.DataFrame(upload_failures)
        failure_csv_path = f"logs/{time.strftime('%Y-%m-%d_%H-%M-%S')}_failures.csv"
        failure_df.to_csv(failure_csv_path, index=False)

    else:
        logger.info("All images uploaded successfully.")


    


if __name__ == "__main__":
    asyncio.run(main())

    # Uncomment the following lines to run the other functions
    # create_collection()
    # upload_images_to_geovisio()
    # get_all_collections()