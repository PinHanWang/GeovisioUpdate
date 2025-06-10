import pandas as pd
from pathlib import Path
import numpy as np
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pytz
from pyproj import Transformer


def parse_keyname_to_gpstime(keyname: str) -> datetime:
    """
    Parse the KeyName to extract GPS time.
    """
    try:
        # Extract the timestamp from KeyName
        timestamp_str = keyname.split('_')[0]
        # Convert to datetime object
        dt = datetime.strptime(
            timestamp_str[:-3] + timestamp_str[-3:] + '000', "%Y%m%d%H%M%S%f")
        dt_taipei = dt.replace(tzinfo=timezone.utc)
        gps_time = dt_taipei.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        return gps_time
    except Exception as e:
        print(f"Error parsing KeyName '{keyname}': {e}")
        return None


def get_time_difference(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate the time difference between consecutive rows in the DataFrame.
    """
    df = df.sort_values(by='GPSTime')

    df['GPSTime'] = pd.to_datetime(
        df['GPSTime'], format="%Y-%m-%dT%H:%M:%S.%fZ", errors='coerce')
    df['GPSTime_diff'] = (
        df['GPSTime'] - df['GPSTime'].shift()).dt.total_seconds()
    df.loc[0, 'GPSTime_diff'] = 0.0  # Fill NaN with 0 for the first row
    return df


def get_distance_difference(df: pd.DataFrame) -> pd.DataFrame:
    transformer = Transformer.from_crs(
        "epsg:4326", "epsg:3826", always_xy=True)

    def convert_to_twd97(lon, lat):
        """
        Convert GPS coordinates from WGS84 to TWD97.
        """
        try:
            x, y = transformer.transform(lon, lat)
            return x, y
        except Exception as e:
            print(f"Error converting coordinates ({lon}, {lat}): {e}")
            return None, None

    df = df.sort_values(by='GPSTime')

    df[['X_TWD97', 'Y_TWD97']] = df.apply(lambda row: pd.Series(
        convert_to_twd97(row['GPS_X'], row['GPS_Y'])), axis=1)

    df['X_prev'] = df['X_TWD97'].shift()
    df['Y_prev'] = df['Y_TWD97'].shift()

    # Calculate the distance to the previous point
    df['distance_to_prev'] = df.apply(
        lambda row: np.round(np.sqrt((row['X_TWD97'] - row['X_prev'])
                            ** 2 + (row['Y_TWD97'] - row['Y_prev']) ** 2), 3)
        if pd.notnull(row['X_prev']) else 0.0,
        axis=1
    )

    # 不需要 X_prev / Y_prev 可刪掉
    df = df.drop(columns=['X_prev', 'Y_prev'])

    return df


def group_by_date(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group the data by the date portion of the GPSTime.
    """
    df['Date'] = df['GPSTime'].dt.date  # Extract the date part from GPSTime
    grouped = df.groupby('Date')

    # Create a list to store each group
    grouped_data = {}
    for date, group in grouped:
        grouped_data[date] = group
        print(f"Data for {date}:")
        print(group)
        print()

    return grouped_data



def split_groups_by_time_and_distance(df: pd.DataFrame, time_threshold: int = 300, distance_threshold: float = 20.0) -> pd.DataFrame:
    df = df.copy()
    df = df.sort_values(by='GPSTime')
    group_id = 0
    group_ids = []

    for idx, row in df.iterrows():
        if idx == 0:
            group_ids.append(group_id)
            continue
        
        if (row['GPSTime_diff'] > time_threshold) or (row['distance_to_prev'] > distance_threshold):
            group_id += 1
        
        group_ids.append(group_id)
    
    df['group_id'] = group_ids
    return df
def data_preprocessing(csv_path: Path) -> pd.DataFrame:
    """
    Data preprocessing for GeoVision data.
    """
    # Read the CSV file
    if not csv_path.exists():
        raise FileNotFoundError(f"The file {csv_path} does not exist.")
    df = pd.read_csv(csv_path)

    # Drop duplicate rows based on 'KeyName'
    df_unique = df.drop_duplicates(subset=['KeyName'], keep='first')
    print(f"Number of unique rows based on 'KeyName': {len(df_unique)}")

    # Convert 'KeyName' to string type and calculate GPS time difference
    df_unique['GPSTime'] = df_unique['KeyName'].apply(parse_keyname_to_gpstime)
    if df_unique['GPSTime'].isnull().any():
        print("Warning: Some GPSTime values could not be parsed.")
    # df_unique.to_csv(csv_path.parent / "parsed_data.csv", index=False)
    df_unique = get_time_difference(df_unique)
    # Calculate distance differences
    df_unique = get_distance_difference(df_unique)
    
    df_unique = split_groups_by_time_and_distance(df_unique)

    subset_cols = ['KeyName', 'GPSTime', 'GPSTime_diff',
                   'GPS_X', 'GPS_Y', 'distance_to_prev','group_id','speed', 'url']
    
    if (df_unique['GPSTime_diff'] > 60.0).any():
        print("Warning: Some GPSTime_diff values are greater than 60 seconds.")
        warning_df = df_unique[df_unique['GPSTime_diff'] > 60.0]
        warning_df.to_csv(csv_path.parent / "warning_data.csv", index=False)

    return df_unique[subset_cols]


if __name__ == "__main__":
    # Replace with your actual CSV file path
    csv_path = Path(
        r"D:\MyProject\AIROADUpdate\data\raw\Subproject_1_sidewalk_markline.csv")

    df = data_preprocessing(csv_path)
    print(df.head())
    df.to_csv(csv_path.parent / "processed_data.csv", index=False)
