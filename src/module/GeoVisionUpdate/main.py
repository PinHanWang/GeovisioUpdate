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


def main():
    csv_path = Path(r"D:\MyProject\AIROADUpdate\data\raw\Subproject_1_sidewalk_markline.csv")  # Replace with your actual CSV file path

    prcocessed_data = data_preprocessing(csv_path)
    grouped_data = group_by_date(prcocessed_data)

    for date, group in tqdm(grouped_data, desc="Processing data ..."): # for date, group in grouped_data:
        # print(f"Start processing data for {date}...")
        seq_data = group.groupby('group_id')
        for seq_id, seq in seq_data:
            seq = seq.sort_values(by='GPSTime')
            collection_id = create_collection(
                title="交工案第一分案資料蒐集(標人)",
                description=f"Data collection for {date}; Sequence ID: {seq_id}",
                )
            
            print(f"Created collection with ID: {collection_id}")
            upload_images_to_geovisio(seq, collection_id)
            from time import sleep
            sleep(180)


    


if __name__ == "__main__":
    main()
    # Uncomment the following lines to run the other functions
    # create_collection()
    # upload_images_to_geovisio()
    # get_all_collections()