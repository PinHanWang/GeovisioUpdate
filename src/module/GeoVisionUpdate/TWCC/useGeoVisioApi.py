from pathlib import Path
from datetime import datetime, timezone
from time import sleep
from tqdm import trange

import pandas as pd
import requests

IP = "192.168.61.1"
PORT = 5000

def timeParser(sourceDatetime: str, oldFormat: str = None, newFormat: str = None) -> str:
    if oldFormat == None:
        oldFormat = "%Y:%m:%d %H:%M:%S"
    if newFormat == None:
        newFormat = "%Y-%m-%dT%H:%M:%SZ"
    
    t = datetime.strptime(sourceDatetime, oldFormat).replace(tzinfo=timezone.utc)
    return t.strftime(newFormat)

def getApiId(title: str) -> str:
    url = f"http://{IP}:{PORT}/api/collections"
    data = {"title": title}
    try:
        response = requests.post(url, data = data)
        return response.json()["id"]
    except:
        return ""

def uploadPicture(id_: str, imagePath: Path, seq: int, formatTime: str, lat: float, lon: float) -> int:
    url = f"http://{IP}:{PORT}/api/collections/{id_}/items"
    data = {
        "position": seq,
        "isBlurred": "true",
        "override_capture_time": formatTime,
        "override_latitude": float(lat),
        "override_longitude": float(lon)
    }
    files_ = {"picture": (imagePath.name, open(str(imagePath), "rb"), "image/jpg")}
    print(data)
    print(files_)
    try:
        response = requests.post(url, data = data, files = files_)
        # print(response.status_code)
        # print(response.text)
        return response.status_code  # 202
    except:
        return response.status_code

def uploadRoute(folder: Path, id_: str, df: pd.DataFrame) -> int:
    indexList = df.index.tolist()
    print(f"\nindexList: {indexList}")

    if len(indexList):
        i = 0
        while i < len(indexList):
            filename, datetime, lat, lon, _speed, _sec, frame = df.loc[indexList[i]]
            imagePath = (folder /filename / f"{filename}_{frame}.jpg")
            print(imagePath)
            # imagePath = (folder / f"{filename}_{frame}.png") # Check image folder path
            seq = i + 1
            formatTime = timeParser(datetime)
            status_code = uploadPicture(id_, imagePath, seq, formatTime, lat, lon)
            print(status_code)
            if status_code == 202:
                print(f"\r圖片 {imagePath.name} 上傳成功", end="")
                sleep(1)
                i += 1
            else:
                print(f"\n圖片 {imagePath.name} 上傳失敗，等待300秒")
                for _ in trange(300):
                    sleep(1)
    return seq

if __name__ == '__main__':
    """
        範例：
            給定圖片所在資料夾SOURCE、title及csv檔路徑(或直接給pd.DataFrame)
            SOURCE/
                ├ 20250319112934_000027A/
                │   └ 20250319112934_000027A_{fream}.png
                ├ 20250319113434_000028A/
                │   └ 20250319113434_000028A_{fream}.png
                ├ 20250319113934_000029A/
                │   └ 20250319113934_000029A_{fream}.png
                ├ 20250319114434_000030A/
                │   └ 20250319114434_000030A_{fream}.png
                └ 20250319112934_000027A.csv
    """
    SOURCE = Path(r"E:\DCIM\Movie")
    title = "20250319112934_000027A"
    exifPath = (SOURCE / f"{title}.csv")
    if exifPath.exists():
        # call api 獲取id(或你已經有id的話可以自己給 ex: "86f09568-bdfa-4da1-a78b-fd5be0130350")
        id_ = getApiId(title)
        if id_:
            df = pd.read_csv(str(exifPath))
            seq = uploadRoute(SOURCE, id_, df)  # seq: 該路徑上傳總張數
        else:
            print("ID 獲取失敗")