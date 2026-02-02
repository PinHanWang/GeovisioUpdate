import requests
import json
import os
from dotenv import load_dotenv
import pandas as pd
import io
from pathlib import Path
import aiohttp
import aiofiles
from aiohttp import ClientTimeout
import asyncio
from failures import upload_failures, collection_failures
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, RetryError
import logging.config
from logger import LOGGING_CONFIG
from deduplication import dedup_checker
from resource_monitor import simple_resource_monitor
from large_sequence_handler import large_seq_handler

# 設定日誌配置
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger(__name__)

# 載入環境變量
load_dotenv()
TMS_GEOVISIO_URL = os.getenv("TMS_GEOVISIO_URL")
IMAGE_BASE_PATH = os.getenv("IMAGE_BASE_PATH")
MAX_CONCURRENT_UPLOADS = int(os.getenv("MAX_CONCURRENT_UPLOADS", "5"))
UPLOAD_TIMEOUT = int(os.getenv("UPLOAD_TIMEOUT", "60"))
ENABLE_DEDUPLICATION = os.getenv("ENABLE_DEDUPLICATION", "true").lower() == "true"
ENABLE_MD5_CHECK = os.getenv("ENABLE_MD5_CHECK", "true").lower() == "true"
ENABLE_RESOURCE_MONITOR = os.getenv("ENABLE_RESOURCE_MONITOR", "true").lower() == "true"

logger.info(f"TMS_GEOVISIO_URL: {TMS_GEOVISIO_URL}")
logger.info(f"IMAGE_BASE_PATH: {IMAGE_BASE_PATH}")


class ImageAlreadyExistsError(Exception):
    """圖片已存在的異常，不應重試"""
    pass

class RetryableUploadError(Exception):
    """可重試的上傳異常"""
    pass

# 設定重試策略
def log_retry_error(retry_state):
    """
    當重試嘗試永久失敗時記錄錯誤。

    此函數使用日誌記錄器記錄錯誤，將錯誤附加到 upload_failures 列表中，
    並將 collection_id 添加到 collection_failures 集合中。

    參數
    ----
    retry_state : tenacity.RetryCallState
        重試嘗試的狀態物件。

    注意事項
    --------
    此函數假設 retry_state 物件具有以下屬性：
    - args: 包含 collection_id 和 keyname 的元組
    - kwargs: 包含 collection_id 和 keyname 的字典
    - outcome: 重試嘗試的結果
    - attempt_number: 重試嘗試的次數
    """
    if hasattr(retry_state, 'args') and len(retry_state.args) >= 3:
        collection_id = retry_state.args[1]
        keyname = retry_state.args[2]
    else:
        collection_id = retry_state.kwargs.get('collection_id', 'Unknown')
        keyname = retry_state.kwargs.get('keyname', 'Unknown')

    error_msg = str(retry_state.outcome.exception(
    )) if retry_state.outcome and retry_state.outcome.exception() else "Unknown error"

    if "409" in error_msg or "already exist" in error_msg.lower() or isinstance(retry_state.outcome.exception(), ImageAlreadyExistsError):
        logger.info(f"Image {keyname} already exists in collection {collection_id}, treating as success")
        return
    
    logger.error(
        f"Upload permanently failed after retries: {keyname} in collection {collection_id}, Error: {error_msg}")

    upload_failures.append({
        'KeyName': keyname,
        'CollectionID': collection_id,
        "Error": error_msg,
        "RetryCount": retry_state.attempt_number
    })
    collection_failures.add(collection_id)


# 取得所有collection
async def get_all_collections():
    """
        從 GeoVisio 獲取所有集合。

        返回值
        ------
        dict
            包含所有 GeoVisio 集合的字典。

        異常
        ----
        Exception
            獲取集合時發生錯誤。
    """
    url = f"{TMS_GEOVISIO_URL}/api/collections"
    async with aiohttp.ClientSession() as session:

        try:
            logger.info(f"Fetching all collections.")

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    output_dir = r'output\geovisio'
                    os.makedirs(output_dir, exist_ok=True)

                    output_file = os.path.join(
                        output_dir, 'all_collections.json')

                    async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(data, ensure_ascii=False, indent=4))

                    logger.info(f"All collections saved to {output_file}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to fetch collections. Status code: {response.status}, Error: {error_text}")
                    return None
        except Exception as e:
            logger.error(
                f"An error occurred while fetching collections: {e}")
            return None


# 取得collection by id
async def get_collection_by_items_id(collection_id):
    """
        取得 GeoVisio 集合的詳細資訊。

        參數
        ----
        collection_id : str
            要取得的集合 ID。

        返回值
        ------
        dict
            集合的詳細資訊。

        異常
        ----
        Exception
            取得集合時發生錯誤。
    """
    url = f"{TMS_GEOVISIO_URL}/api/collections/{collection_id}"

    async with aiohttp.ClientSession() as session:
        try:
            logger.info(f"Fetching collection with ID: {collection_id}")

            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()

                    output_dir = r'output\geovisio'
                    os.makedirs(output_dir, exist_ok=True)

                    output_file = os.path.join(
                        output_dir, f'collection_{collection_id}.json')

                    async with aiofiles.open(output_file, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(data, ensure_ascii=False, indent=4))

                    logger.info(
                        f"Collection {collection_id} saved to {output_file}")
                    return data
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to fetch collection {collection_id}. Status code: {response.status}, Error: {error_text}")
                    return None
        except Exception as e:
            logger.error(
                f"An error occurred while fetching collection {collection_id}: {e}")
            return None


# 新增collection
async def create_collection(title, description, keywords, bbox=None, start_time=None):
    """
    創建 GeoVisio 集合

    參數
    ----
    title : str
        集合的標題
    description : str
        集合的描述
    keywords : list[str]
        集合的關鍵字
    bbox : list[float], optional
        集合的 bounding box，預設為 None
    start_time : datetime, optional
        集合的開始時間，預設為 None

    返回值
    ------
    str
        創建的集合 ID

    異常
    ----
    Exception
        創建集合時發生錯誤
    """
    url = f"{TMS_GEOVISIO_URL}/api/collections"

    if keywords is None:
        keywords = ['upload', 'api']

    extent = {}
    if bbox:
        extent["spatial"] = {"bbox": [bbox]}
    if start_time is not None:
        extent["temporal"] = {"interval": [[start_time, None]]}
    else:
        extent["temporal"] = {"interval": [[None, None]]}

    payload = {
        "title": title,
        "description": description,
        "license": "proprietary",
        "keywords": keywords,
        "extent": extent
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload) as response:
                if response.status in [200, 201]:
                    data = await response.json()
                    logger.info(f"Collection created: {data['id']}")
                    return data["id"]
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Failed to create collection. Status code: {response.status}, Error: {error_text}"
                    )
                    return None

        except Exception as e:
            logger.error(f"An error occurred while creating collection: {e}")
    return None


# 正確的寫法
@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type((
        RetryableUploadError, 
        asyncio.TimeoutError, 
        FileNotFoundError
    )),  # 將多個異常類型放在元組中
    retry_error_callback=log_retry_error
)
# 上傳圖片集合
async def upload_image_to_collection(session, collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq):
    """
    上傳圖片集合到 GeoVision

    Parameters
    ----------
    session : aiohttp.ClientSession
        GeoVision API 連線 session
    collection_id : str
        上傳的集合 ID
    keyname : str
        上傳的圖片名稱
    gps_time : str
        上傳的圖片 GPS 時間
    gps_x : float
        上傳的圖片 GPS 緯度
    gps_y : float
        上傳的圖片 GPS 經度
    speed : float
        上傳的圖片 GPS 速度
    img_url : str
        上傳的圖片 URL
    seq : int
        上傳的圖片順序

    Returns
    -------
    bool
        上傳成功則返回 True，否則返回 False

    Raises
    ------
    aiohttp.ClientError
        上傳時發生錯誤
    asyncio.TimeoutError
        上傳時超時
    asyncio.CancelledError
        上傳被取消
    FileNotFoundError
        圖片檔案不存在
    Exception
        其他上傳錯誤
    """
    url = f"{TMS_GEOVISIO_URL}/api/collections/{collection_id}/items"

    data = {
        "position": seq,
        "isBlurred": "true",
        "override_capture_time": gps_time,
        "override_latitude": float(gps_y),
        "override_longitude": float(gps_x)
    }
    ###
    # try:
    #     logger.info(f"Starting upload of {keyname} (seq {seq}) to collection {collection_id}")

    #     async with session.get(img_url, timeout=timeout) as img_response:
    #         if img_response.status == 200:
    #             img_bytes = await img_response.read()
    #             image_data = io.BytesIO(img_bytes)

    #             form_data = aiohttp.FormData()
    #             for k, v in data.items():
    #                 form_data.add_field(k, str(v))
    #             form_data.add_field(
    #                 'picture',
    #                 image_data,
    #                 filename=Path(img_url).name,
    #                 content_type='image/jpeg'
    #             )

    #             async with session.post(url, data=form_data, timeout=timeout) as post_response:
    #                 if post_response.status in [200, 201, 202]:
    #                     logger.info(f"Successfully uploaded item: {keyname}")
    #                 else:
    #                     text = await post_response.text()
    #                     logger.warning(f"Failed to upload item {keyname}: {post_response.status} - {text}")
    #                     raise Exception(f"Upload failed with status {post_response.status}")

    #         else:
    #             logger.warning(f"Failed to fetch image from {img_url}. Status code: {img_response.status}")
    #             raise Exception(f"Image fetch failed with status {img_response.status}")

    # except (asyncio.TimeoutError, asyncio.CancelledError) as e:
    #     logger.error(f"Timeout when fetching image from {img_url}: {e}")
    #     raise e

    # except Exception as e:
    #     logger.error(f"Exception uploading item {keyname}: {e}")
    #     raise e

    # await asyncio.sleep(1)
    ###

    try:
        logger.info(
            f"Starting upload of {keyname} (seq {seq}) to collection {collection_id}")

        image_path = os.path.join(IMAGE_BASE_PATH, f'{keyname}.jpg')

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")

        try:
            async with aiofiles.open(image_path, "rb") as f:
                image_bytes = await f.read()
        except Exception as e:
            logger.error(f"Failed to read image file {image_path}: {e}")
            raise e

        image_data = io.BytesIO(image_bytes)

        form_data = aiohttp.FormData()
        for k, v in data.items():
            form_data.add_field(k, str(v))
        form_data.add_field(
            'picture',
            image_data,
            filename=Path(image_path).name,
            content_type='image/jpeg'
        )
        timeout = ClientTimeout(total=UPLOAD_TIMEOUT)

        async with session.post(url, data=form_data, timeout=timeout) as post_response:
            if post_response.status in [200, 201, 202]:
                logger.info(f"Successfully uploaded item: {keyname}")
                return True
            elif post_response.status == 409:
                # 409 表示圖片已存在，視為成功
                error_text = await post_response.text()
                logger.warning(f"Image {keyname} already exists at position {seq} (409), treating as success")
                # 拋出特殊異常，不會被重試
                raise ImageAlreadyExistsError(f"Image already exists: {error_text}")
            
            else:
                error_text = await post_response.text()
                error_msg = f"Failed to upload item {keyname}: {post_response.status} - {error_text}"
                logger.warning(error_msg)
                raise RetryableUploadError(error_msg)

    except ImageAlreadyExistsError:
        # 409 錯誤，不重試，直接返回成功
        return True
    
    except (asyncio.TimeoutError, asyncio.CancelledError) as e:
        logger.error(
            f"Timeout / Cancellation when fetching image from {image_path}: {e}")
        raise
    
    except FileNotFoundError:
        # 檔案不存在，不重試
        raise

    except Exception as e:
        logger.error(f"Exception uploading item {keyname}: {e}")
        raise RetryableUploadError(str(e))

    finally:
        if 'image_data' in locals() and image_data is not None: 
            image_data.close()

    # await asyncio.sleep(1)

# 上傳圖片


async def safe_upload_image(session, semaphore, collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq):
    """
    安全上傳圖片到GeoVisio

    Parameters
    ----------
    session : aiohttp.ClientSession
        用於上傳圖片的ClientSession
    semaphore : asyncio.Semaphore
        用於限制上傳圖片的同時數量
    collection_id : str
        上傳圖片的CollectionID
    keyname : str
        上傳圖片的KeyName
    gps_time : str
        上傳圖片的GPS時間
    gps_x : float
        上傳圖片的GPS經度
    gps_y : float
        上傳圖片的GPS緯度
    speed : float
        上傳圖片的速度
    img_url : str
        上傳圖片的URL
    seq : int
        上傳圖片的Sequence

    Returns
    -------
    bool
        上傳成功則返回 True，否則返回 False
    """

    async with semaphore:
        try:
            result = await upload_image_to_collection(session, collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq)
            return True if result else False

        except Exception as e:
            logger.error(
                f"Failed to upload image {keyname} after all retries: {e}")
            return False


async def upload_images_to_geovisio(df, collection_id):
    """
    上傳圖片到 GeoVisio

    Parameters
    ----------
    df : pd.DataFrame
        上傳圖片的DataFrame
    collection_id : str
        上傳圖片的CollectionID

    Returns
    -------
    None
    """
    if df.empty:
        logger.warning("DataFrame is empty. No images to upload.")
        return

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_UPLOADS)

    timeout = ClientTimeout(total=UPLOAD_TIMEOUT * 2)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = []

        index = 0
        for _, row in df.iterrows():
            required_columns = ['KeyName', 'GPSTime',
                                'GPS_X', 'GPS_Y', 'speed', 'url']
            missing_columns = [
                col for col in required_columns if col not in row or pd.isna(row[col])]

            if missing_columns:
                logger.warning(
                    f"Skipping row {index + 1} due to missing columns: {', '.join(missing_columns)}")
                index += 1
                continue

            keyname = row['KeyName']
            gps_time = row['GPSTime']
            gps_x = row['GPS_X']
            gps_y = row['GPS_Y']
            speed = row['speed']
            img_url = row['url']
            seq = index + 1

            task = safe_upload_image(
                session, semaphore, collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq)
            tasks.append(task)
            index += 1

        if not tasks:
            logger.warning(
                "No valid rows found in the DataFrame. No images to upload.")
            return

        logger.info(
            f"Uploading {len(tasks)} images to collection {collection_id}")

        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            successful_uploads = sum(1 for r in results if r is True)
            failed = len(results) - successful_uploads

            logger.info(
                f"Successfully uploaded {successful_uploads} images, {failed} failed.")
            return{
                "successful": successful_uploads,
                "failed": failed,
                "total": len(results)
            }

        except Exception as e:
            logger.error(f"An error occurred while uploading images: {e}")
            return {"successful": 0, "failed": len(tasks), "total": len(tasks)}


if __name__ == "__main__":
    # title = "Test Collection"
    # collection_id = create_collection(title)
    # print(f"Created collection with ID: {collection_id}")
    # get_all_collections()
    # get_collection_by_items_id("214542d0-b307-42fa-99a9-0d0899e1bdfc")
    # collection_id="214542d0-b307-42fa-99a9-0d0899e1bdfc"
    # get_collection_by_items_id(collection_id)
    # collection_id = create_collection(
    #     title="AI Road Test 20250609",
    #     description="Dashcam test upload"
    # )
    # print(f"Created collection with ID: {collection_id}")

    # df = pd.read_csv(r'D:\MyProject\AIROADUpdate\data\raw\test_img.csv')
    # upload_images_to_geovisio(df, collection_id)
    get_all_collections()

    # import requests

    # # 手動下載圖片
    # img_url = df.loc[0, 'url']  # 假設第一行的圖片URL
    # response = requests.get(img_url)
    # if response.status_code == 200:
    #     with open(r'output\images\image.jpg', 'wb') as f:
    #         f.write(response.content)
    #     print("Image downloaded successfully.")
    # else:
    #     print("Failed to download image.")
