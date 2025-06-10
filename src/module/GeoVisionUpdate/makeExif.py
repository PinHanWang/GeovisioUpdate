from datetime import datetime, timedelta
import re
import os
from pathlib import Path

import pandas as pd
from pyproj import Transformer

def _getExifStartTime(p: Path) -> tuple[int, str]:
    """
        取得檔案的EXIF資訊並計算出影像的第一秒GPS時間
        影像開始時間(startDate) = 檔案創建時間(createDate) - 影像持續時間(duration)
        檔案創建時間為整個錄影完成後
    """
    fps, startDate = -1, ""
    cmd = f"exiftool -s {str(p)} -VideoFrameRate -CreateDate -Duration"
    with os.popen(cmd) as t:
        context = t.read()[:-1]
        l = [x.split(": ")[1] for x in context.split("\n") if ": " in x]
        fps = float(l[0])
        createDate = datetime.strptime(l[1], "%Y:%m:%d %H:%M:%S")
        duration = datetime.strptime(l[2], "%H:%M:%S")
        startDate = createDate - timedelta(minutes = duration.minute, seconds = duration.second)
    return fps, startDate.strftime("%Y:%m:%d %H:%M:%S")

# def _getExifStartTime(p: Path) -> tuple[int, str]:
#     """
#         取得檔案的EXIF資訊並計算出影像的第一秒GPS時間
#         影像開始時間(startDate) = 檔案創建時間(createDate) - 影像持續時間(duration)
#         檔案創建時間為整個錄影完成後
#     """
#     fps, startDate = -1, ""
#     cmd = f"exiftool -s {str(p)} -VideoFrameRate -FileCreateDate"
#     with os.popen(cmd) as t:
#         context = t.read()[:-1]
#         l = [x.split(": ")[1] for x in context.split("\n")]
#         fps = float(l[0])
#         startDate = datetime.strptime(l[1], "%Y:%m:%d %H:%M:%S%z")
#     return fps, startDate.strftime("%Y:%m:%d %H:%M:%S") 

def _getExifExtractEmbeddedData(p: Path) -> dict:
    """
        取得檔案的EXIF中的GPS詳細資訊(ExtractEmbeddedData) 處理後傳回字典
    """
    def _calculateGps(s: str) -> float:
        """
            將EXIF的GPS資訊從 度分秒格式 轉換為 浮點數
            ex: 23 deg 59' 7.82" N ---> 23.985505555555555
        """
        direction = {"N": 1, "S": -1, "E": 1, "W": -1}
        d = direction[s[-1]]

        role = re.compile(r"[\d.]+")
        result = role.findall(s)
        a, b, c = (float(x) for x in result)
        return d * (a + b/60 + c/3600)
    
    data = {}
    cmd = f"exiftool -ee -T -GPS* {str(p)}"
    with os.popen(cmd) as t:
        context = t.read()[:-1]
        cells = context.split("\t")[:-1]
        data["GPSDateTime"] = [cells[i][:-1] for i in range(0, len(cells), 5)]
        data["GPSLatitude"] = [_calculateGps(cells[i]) for i in range(1, len(cells), 5)]
        data["GPSLongitude"] = [_calculateGps(cells[i]) for i in range(2, len(cells), 5)]
        data["GPSSpeed"] = [float(cells[i]) for i in range(3, len(cells), 5)]
        data["GPSTrack"] = [float(cells[i]) for i in range(4, len(cells), 5)]
    return data

def _getDfSecondsDifference(startTime: str, dateTime: str) -> int:
    """
        進一步處理EXIF的DataFrame ( 計算 sec )
    """
    startTime = datetime.strptime(startTime, "%Y:%m:%d %H:%M:%S")
    dateTime = datetime.strptime(dateTime, "%Y:%m:%d %H:%M:%S")
    return (dateTime - startTime).total_seconds()

def _getDfTransGps(lon: float, lat: float) -> tuple[float, float]:
    """
        進一步處理EXIF的DataFrame ( 計算 lat3857, lon3857 )
    """
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy = True)
    return transformer.transform(lon, lat)

def makeExifDf(p: Path, columns: list = []) -> pd.DataFrame:
    """
        給定影像路徑及columns 傳回影像內GPS紀錄的DataFrame
        若不給定columns則輸出所有column:
            ["filename", "datetime", "lat", "lon", "speed", "azimuth", "starttime", "fps", "sec", "frame", "lat3857", "lon3857"]
    """

    data = _getExifExtractEmbeddedData(p)
    df = pd.DataFrame(data)
    df = df.rename(
        columns = {
            "GPSDateTime": "datetime",
            "GPSLatitude": "lat",
            "GPSLongitude": "lon",
            "GPSSpeed": "speed",
            "GPSTrack": "azimuth"
        }
    )
    fps, startDate = _getExifStartTime(p)
    df.drop_duplicates(inplace=True)  # 去除重複資料
    if df.empty:
        return df

    df["filename"] = p.stem
    df["starttime"] = startDate
    df["fps"] = fps
    df["sec"] = df["datetime"].map(lambda x: int(_getDfSecondsDifference(startDate, x)))
    df["frame"] = df["sec"].map(lambda x: int(x * fps))
    firstFrame = df.loc[df.index[0], "frame"]
    if firstFrame < 0:
        df["frame"] = df["frame"] - firstFrame
    df[["lon3857", "lat3857"]] = df.apply(lambda x: _getDfTransGps(x["lon"], x["lat"]), axis=1, result_type="expand")
    return df[columns] if columns else df

def saveExifCsv(df: pd.DataFrame, out: Path) -> None:
    df.to_csv(out, index = False)


if __name__ == '__main__':
    # folder = Path(r"E:\DCIM\Movie")
    # name = "20250319092321_000001A.MP4"
    # file = (folder / name)

    # print(file)
    
    # columns = ["filename", "datetime", "lat", "lon", "speed", "azimuth"]
    # df = makeExifDf(file, columns)
    # if len(df):
    #     out = (folder / f"{file.stem}.csv")
    #     saveExifCsv(df, out)


    videoPath = Path(r"H:\DCIM\Movie\20250319102434_000014A.MP4")
    # fps, startDate = _getExifStartTime(videoPath)
    # print(fps, startDate)
    exifDf = makeExifDf(videoPath)
    saveExifCsv(exifDf, videoPath.with_suffix(".csv"))
    # print(exifDf)
    # data = _getExifExtractEmbeddedData(videoPath)
    # print(data)