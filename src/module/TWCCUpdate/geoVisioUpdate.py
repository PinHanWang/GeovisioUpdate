from pathlib import Path
from datetime import date

import pandas as pd

import makeExif as makeExif
import makeScreenshot as makeScreenshot
import useGeoVisioApi as useGeoVisioApi

def getExifDf(videoPath: Path, columns: list[str], startSec: int = None, endSec: int = None) -> pd.DataFrame:
    """
        獲取video的exif資訊，篩選出要上傳至GeoVisio的秒數後，回傳篩選後的DataFrame

        filter_: 篩選規則
            1. 速度在0-50 km/hr範圍內，每3秒截一張圖
            2. 速度在50-80 km/hr範圍內，每2秒截一張圖
            3. 速度在80 km/hr以上，每1秒截一張圖
    """
    df = makeExif.makeExifDf(videoPath, columns)
    filter_ = (
        ((df["speed"] > 0) & (df["speed"] <= 50) & (df["sec"] % 3 == 0))
        | ((df["speed"] > 50) & (df["speed"] <= 80) & (df["sec"] % 2 == 0))
        | (df["speed"] > 80)
    )
    df = df[filter_]
    if startSec != None:
        df = df[(df["sec"] >= startSec)]
    if endSec != None:
        df = df[(df["sec"] <= endSec)]
    return df


# def getExifDf(df_path:Path, columns: list[str], startSec: int = None, endSec: int = None) -> pd.DataFrame:
#     """
#         獲取video的exif資訊，篩選出要上傳至GeoVisio的秒數後，回傳篩選後的DataFrame

#         filter_: 篩選規則
#             1. 速度在0-50 km/hr範圍內，每3秒截一張圖
#             2. 速度在50-80 km/hr範圍內，每2秒截一張圖
#             3. 速度在80 km/hr以上，每1秒截一張圖
#     """
#     df = pd.read_csv(str(df_path))
#     df = df[columns]
#     filter_ = (
#         ((df["speed"] > 0) & (df["speed"] <= 50) & (df["sec"] % 3 == 0))
#         | ((df["speed"] > 50) & (df["speed"] <= 80) & (df["sec"] % 2 == 0))
#         | (df["speed"] > 80)
#     )
#     df = df[filter_]
#     if startSec != None:
#         df = df[(df["sec"] >= startSec)]
#     if endSec != None:
#         df = df[(df["sec"] <= endSec)]
#     return df

def prepareImages(folder: Path, title: str, videos: list[str], startSec: int = None, endSec: int = None, saveCsv: bool = True) -> pd.DataFrame:
    columns = ["filename", "datetime", "lat", "lon", "speed", "sec", "frame"]
    allDf = pd.DataFrame(columns = columns)
    for i, video in enumerate(videos):
        print(f"\n{video}")

        # 取得單一影片exif資訊
        videoPath = (folder / f"{video}.MP4")
        if i == 0:
            df = getExifDf(videoPath, columns, startSec = startSec)
        elif i == len(videos)-1:
            df = getExifDf(videoPath, columns, endSec = endSec)
        else:
            df = getExifDf(videoPath, columns)
        
        if not df.empty:
            # 合併df
            allDf = df if allDf.empty else pd.concat([allDf, df]).reset_index(drop=True)
            # 取得截圖用frames
            frames = df["frame"].tolist()
            print(frames)
            # 依據frames進行截圖(imagesSaveFolder: 與影片同目錄下之同名資料夾)
            imagesSaveFolder = (folder / video)
            makeScreenshot.screenshot(videoPath, imagesSaveFolder, frames)
    
    if not allDf.empty and saveCsv:
        # 取得並儲存exif DataFrame(exifOutPath: 與影片同目錄下之title.csv檔)
        exifSavePath = (folder / f"{title}.csv")
        makeExif.saveExifCsv(allDf, exifSavePath)
    return allDf

# def prepareImages(folder: Path, title: str, videos: list[str], startSec: int = None, endSec: int = None, saveCsv: bool = True) -> pd.DataFrame:
#     columns = ["filename", "datetime", "lat", "lon", "speed", "sec", "frame"]
#     allDf = pd.DataFrame(columns = columns)
#     for i, video in enumerate(videos):
#         print(f"\n{video}")

#         # 取得單一影片exif資訊
#         videoPath = (folder / f"{video}.MP4")
#         df_path = (folder / f"{video}.csv")
#         if i == 0:
#             df = getExifDf(df_path, columns, startSec = startSec)
#         elif i == len(videos)-1:
#             df = getExifDf(df_path, columns, endSec = endSec)
#         else:
#             df = getExifDf(df_path, columns)
        
#         if not df.empty:
#             # 合併df
#             allDf = df if allDf.empty else pd.concat([allDf, df]).reset_index(drop=True)
#             # 取得截圖用frames
#             frames = df["frame"].tolist()
#             print(frames)
#             # 依據frames進行截圖(imagesSaveFolder: 與影片同目錄下之同名資料夾)
#             imagesSaveFolder = (folder / video)
#             makeScreenshot.screenshot(videoPath, imagesSaveFolder, frames)
    
#     if not allDf.empty and saveCsv:
#         # 取得並儲存exif DataFrame(exifOutPath: 與影片同目錄下之title.csv檔)
#         exifSavePath = (folder / f"{title}.csv")
#         makeExif.saveExifCsv(allDf, exifSavePath)
#     return allDf

def uploadImages(folder: Path, id_: str, df: pd.DataFrame, title: str, videos: list[str]) -> dict:
    seq = useGeoVisioApi.uploadRoute(folder, id_, df)  # seq: 該路徑上傳總張數
    result = {
        "title": title,
        "id": id_,
        "n": seq,
        "files": videos,
        "update": date.today().strftime("%Y-%m-%d")  # 上傳日期
    }
    return result

if __name__ == '__main__':
    """
        (範例)
        新生南路
        20250319112934_000027A(這部從01:30開始)
        20250319113434_000028A
        20250319113934_000029A
        20250319114434_000030A(這部到01:15)
    """
    
    SOURCE = Path(r"H:\DCIM\Movie\AIROAD\Nangang")

    # Step1: 手動定義上傳路線(相關資訊妤玲會給)
    startSec = None  # 01:30 = 90秒(如果沒寫開始時間可以不用給)
    endSec = None  # 01:15 = 75秒(如果沒寫結束時間可以不用給)
    videos = [
        "20251015105509_000016A",
        "20251015110009_000017A",
        "20251015110509_000018A",
    ]  # 影片要照順序


    # Step2: 準備上傳GeoVisio用材料(saveCsv=True 會將df內容儲存成 SOURCE/title.csv 檔案)
    title = videos[0]  # title為第一部影片的名稱
    df = prepareImages(SOURCE, title, videos, startSec, endSec, saveCsv = True)
    # df = pd.read_csv(str((SOURCE / f"{title}.csv")))
    # print(df)
    
    
    # Step3: 使用API上傳GeoVisio
    id_ = useGeoVisioApi.getApiId(title)
    if id_:
        print(f"獲取 ID {id_}")
        result = uploadImages(SOURCE, id_, df, title, videos)
        print(result)
    else:
        print("獲取 ID 失敗")