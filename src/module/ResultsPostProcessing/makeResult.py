from datetime import datetime
import math
from pathlib import Path
import json
import os
import sys
import numpy as np
import pandas as pd
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from src.module.utlis import makeExif # import同目錄下的exif.py

III_SIGN_NAME_JSON_PATH = r"configs\iiiSignName.json"
CAR_ANGLE_TABLE_CSV_PATH = r"configs\carAngleTable.csv"

def _addCarData(df: pd.DataFrame, frame: int) -> tuple[float]:
    """
        依據exif資訊取得該frame車子資料
    """
    def _getPointsData(df: pd.DataFrame, frame: int) -> tuple[list[float]]:
        df["frameDifference"] = df["frame"].map(lambda x: abs(x - frame))
        filter_ = (df["frameDifference"] <= 300)
        if len(df[filter_]) < 2:
            return None, None
        df.sort_values(by = "frameDifference", inplace = True)

        index1, index2 = sorted(df.index.to_list()[:2])
        columns = ["frame", "lon3857", "lat3857", "azimuth"]
        p1 = df.loc[index1, columns].to_list()
        p2 = df.loc[index2, columns].to_list()
        return p1, p2

    def _getLonLat(t: float, l1: float, l2: float) -> float:
        return l1 + (l2 - l1) * t
    
    def _getAzimuth(t: float, a1: float, a2: float) -> float:
        m = a2 - a1
        if m <= -180:
            m += 360
        elif m >= 180:
            m -= 360
        
        a = a1 + m * t
        if a < 0:
            a += 360
        elif a >= 360:
            a -= 360
        return a
    
    p1, p2 = _getPointsData(df, frame)
    if not p1:
        return np.nan, np.nan, np.nan
    t = (frame - p1[0]) / (p2[0] - p1[0])
    lon = _getLonLat(t, p1[1], p2[1])
    lat = _getLonLat(t, p1[2], p2[2])
    azimuth = _getAzimuth(t, p1[3], p2[3])
    return lon, lat, azimuth

def _addObjectAngleByCar(df: pd.DataFrame, xc: float, yc: float, videoWidth: int=2560, videoHigth: int=1440) -> float:
    """
        用查表法計算物體與車子夾角
    """
    xc, yc = xc * videoWidth, yc * videoHigth
    df["distanceSquare"] = df.apply(lambda x: ((xc-x["frame_u"])**2)+((yc-x["frame_v"])**2), axis = 1)

    index = df["distanceSquare"].idxmin()
    return df.loc[index, "frame_angle"]

def _addObjectGps(p1: list[float], p2: list[float], d: int) -> tuple[float]:
    """
        用角度angle及車子car座標與前方交會法計算物體object GPS
        d = p1 點在畫面右邊: -1, p1 點在畫面左邊: +1
        p = [angle, azimuth, lon, lat]
    """
    azimuthMove = (p1[1] - p2[1]) * d
    alpha = 90 - p1[0] - azimuthMove
    beta = 90 + p2[0]
    alpha, beta = math.radians(alpha), math.radians(beta)  # 角度轉換成弧度
    try:
        cotalpha, cotbeta = 1 / math.tan(alpha), 1 / math.tan(beta)  # 求出 cotangent
    except:
        return
    lon = (p1[2]*cotbeta + p2[2]*cotalpha + (p1[3] - p2[3])*d) / (cotalpha + cotbeta)
    lat = (p1[3]*cotbeta + p2[3]*cotalpha + (p2[2] - p1[2])*d) / (cotalpha + cotbeta)
    return lon, lat  # 3857

def _addObjectDistanceByCar(objectLon: float, objectLat: float, carLon: float, carLat: float) -> float:
    """
        用car及object座標計算物體object與車子car間距離
    """
    x = objectLon - carLon
    y = objectLat - carLat
    return (x*x + y*y)**0.5

def _addSignName(d: dict, class_: int) -> tuple[str]:
    """
        加入資策會的號誌代碼及名稱
    """
    signNum, signName = d["signNum"], d["signName"]
    return signNum[class_], signName[signNum[class_]]

def makeResultDf(p: Path, exifDf: pd.DataFrame) -> pd.DataFrame:
    """
        讀取*.csv並處理 返回DataFrame
    """
    df = pd.read_csv(str(p))
    print(f"0. Start: {datetime.now()}")

    df[["car_lon3857", "car_lat3857", "car_azimuth"]] = df.apply(
        lambda x: _addCarData(exifDf, x["frame"]), axis=1, result_type="expand"
    )
    print(f"1. Car Data: {datetime.now()}")

    carAngleDf = pd.read_csv(CAR_ANGLE_TABLE_CSV_PATH)
    df["angle"] = df.apply(lambda x: _addObjectAngleByCar(carAngleDf, x["xc"], x["yc"]), axis=1)
    print(f"2. Object Angle: {datetime.now()}")

    # 用前方交會法計算物體 GPS (object_lon3857, object_lat3857)
    df["object_lon3857"], df["object_lat3857"] = pd.Series(dtype = float), pd.Series(dtype = float)
    columns = ["angle", "car_azimuth", "car_lon3857", "car_lat3857"]
    groups = df.groupby("id")
    for g in groups:
        indexes = g[1].sort_values(by = "frame").index.to_list()
        if len(indexes) < 2: continue
        
        d = 1 if g[1].loc[indexes[-1], "xc"] <= 0.5 else -1
        p2 = g[1].loc[indexes[-1], columns].to_list()
        for i in range(len(indexes)-1):
            if g[1].loc[indexes[i], "angle"] - p2[0] < 5:
                break
            p1 = g[1].loc[indexes[i], columns].to_list()
            df.loc[indexes[i], ["object_lon3857", "object_lat3857"]] = _addObjectGps(p1, p2, d)
    print(f"3. Object Gps: {datetime.now()}")

    df["distance"] = df.apply(
        lambda x: _addObjectDistanceByCar(
            x["object_lon3857"], x["object_lat3857"], x["car_lon3857"], x["car_lat3857"]
        ), axis=1, result_type="expand"
    )
    print(f"4. Object Distance: {datetime.now()}")

    signNameDict = json.load(open(III_SIGN_NAME_JSON_PATH, "r", encoding="utf-8-sig"))
    df[["signNum", "signName"]] = df.apply(lambda x: _addSignName(signNameDict, x["class"]), axis=1, result_type="expand")
    print(f"5. III Sign Name: {datetime.now()}")

    return df

def saveResultCsv(p: Path, df: pd.DataFrame) -> None:
    columns=[
        "filename", "frame", "id", "class",
        "xc", "yc", "w", "h",
        "car_lon3857", "car_lat3857", "car_azimuth",
        "angle", "object_lon3857", "object_lat3857", "distance",
        "signNum", "signName"
    ]
    df.to_csv(
        str(p.parent / f"result_{p.stem}.csv"),
        columns=columns,
        index = False,
        encoding = "utf_8_sig"
    )


if __name__ == '__main__':
    labelsFolder = Path(r"D:\MyProject\AIROADUpdate\output\prediction\0408")
    videosFolder = Path(r"H:\DCIM\Movie")

    labelsPath = labelsFolder.glob("2025*A.csv")  # 儲存 labels 的檔案
    print(f"labelsPath: {labelsPath}")
    for labelPath in labelsPath:
        print(labelPath)
        # get exif imformation
        videoPath = (videosFolder / f"{labelPath.stem}.MP4")
        exifDf = makeExif.makeExifDf(videoPath)
        if len(exifDf):
            print(f"{labelPath.stem} do")
            # make result_*.csv
            df = makeResultDf(labelPath, exifDf)
            saveResultCsv(labelPath, df)
        else:
            print(f"{labelPath.stem} skip")