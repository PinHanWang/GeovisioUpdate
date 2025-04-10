from pathlib import Path

import cv2

import makeExif  # import同目錄下的exif.py

def screenshot(videoPath: Path, imagesPath: Path, frames: list[int] = []) -> None:
    """
        把單一影片截圖，截圖名稱為 imagesPath/videoName_frameNumber.png
        videoPath: 影片位置
        imagesPath: 截圖存放位置
        frames: 要截的幀組成的list，若未給參數則每一幀都截
    """
    if not imagesPath.exists():
        imagesPath.mkdir()
    
    cap = cv2.VideoCapture(str(videoPath))
    i = 0
    while cap.isOpened():
        if i < len(frames):
            sep = frames[i]
            cap.set(cv2.CAP_PROP_POS_FRAMES, sep)
            i += 1
        else:
            sep = cap.get(1)

        ret, frame = cap.read()
        if not ret:
            break
        imagePath = (imagesPath / f"{videoPath.stem}_{sep}.png")
        cv2.imwrite(str(imagePath), frame)
        print(f"\rsave image to {imagePath}", end="")

        if frames and i == len(frames):
            break
    cap.release()
    cv2.destroyAllWindows()

def readme() -> None:
    """
        一些使用範例說明
    """
    # case1: 給影片裡的每一幀都截圖
    videoPath = Path(r"folder/myvideo.mp4")
    imgSaveFolder = Path(r"folder/myvideo")
    screenshot(videoPath, imgSaveFolder)

    # case2: 每10幀截一張圖
    videoPath = Path(r"folder/myvideo.mp4")
    imgSaveFolder = Path(r"folder/myvideo")
    sep = 10  # 每10幀截一張圖
    totalFrame = 5*60*60  # 總幀數，假設影片長5分鐘*60秒*每秒60幀
    frames = [i for i in range(0, totalFrame, sep)]
    screenshot(videoPath, imgSaveFolder, frames)

    # case3: 依據exif篩選出有移動位置的秒數截圖
    videoPath = Path(r"folder/myvideo.mp4")
    imgSaveFolder = Path(r"folder/myvideo")
    fps = 60  # 影像fps
    df = makeExif.makeExifDf(videoPath)  # 讀取影像的exif資訊並整理成pd.DataFrame
    filter_ = (df["speed"] != 0)  # 篩選df內容(速度0等紅燈的不要)找出要截圖的秒數
    frames = [x * fps for x in df[filter_]["sec"].tolist()]  # 將篩選後秒數轉成幀數
    screenshot(videoPath, imgSaveFolder, frames)

    # case4: 影片的1:30(90秒)至3:30(210秒)間每一秒截圖
    videoPath = Path(r"folder/myvideo.mp4")
    imgSaveFolder = Path(r"folder/myvideo")
    fps = 60  # 影像fps
    startFrame, endFrame = 90*fps, 210*fps
    frames = [i for i in range(0, endFrame+1, fps) if i >= startFrame]
    print(frames)
    screenshot(videoPath, imgSaveFolder, frames)

if __name__==  "__main__":
    # 用法參見readme()函數
    pass