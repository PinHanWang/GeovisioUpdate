import requests
import json
import os
from dotenv import load_dotenv
import pandas as pd
import io
from pathlib import Path

load_dotenv()
TMS_GEOVISIO_URL = os.getenv("TMS_GEOVISIO_URL")
print(f"TMS_GEOVISIO_URL: {TMS_GEOVISIO_URL}")
def get_all_collections():
    url = f"{TMS_GEOVISIO_URL}/api/collections"
    try:
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()

            output_dir = r'output\geovisio'
            os.makedirs(output_dir, exist_ok=True)

            output_file = os.path.join(output_dir, 'all_collections.json')

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

            print(f"All collections saved to {output_file}")
        else:
            print(f"Failed to fetch collections. Status code: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"An error occurred while fetching collections: {e}")



def get_collection_by_items_id(collection_id):
    url = f"{TMS_GEOVISIO_URL}/api/collections/{collection_id}"
    try:
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()

            output_dir = r'output\geovisio'
            os.makedirs(output_dir, exist_ok=True)

            output_file = os.path.join(output_dir, f'collection_{collection_id}.json')

            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)

            print(f"Collection {collection_id} saved to {output_file}")
        else:
            print(f"Failed to fetch collection {collection_id}. Status code: {response.status_code}")
            print(f"Response: {response.text}")
    except Exception as e:
        print(f"An error occurred while fetching collection {collection_id}: {e}")


def create_collection(title, description, bbox=None, start_time=None):
    url = f"{TMS_GEOVISIO_URL}/api/collections"

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
        "keywords": ["test", "upload"],
        "extent": extent
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code in [200, 201]:
            data = response.json()
            print("Collection created:", data["id"])
            return data["id"]
        else:
            print(f"Failed to create collection: {response.status_code}")
            print(response.text)
    except Exception as e:
        print("Error:", e)
    return None

def upload_images_to_geovisio(df, collection_id):

    # parse the DataFrame to extract necessary columns
    for index, row in df.iterrows():
        keyname = row['KeyName']
        gps_time = row['GPSTime']
        gps_x = row['GPS_X']
        gps_y = row['GPS_Y']
        speed = row['speed']
        img_url = row['url']
        seq = index + 1  # Assuming seq is just the index + 1 for ordering

        # Call the function to upload each image
        upload_image_to_collection(collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq)

# Upload an image to a specific collection in GeoVisio
def upload_image_to_collection(collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq):
    
    url = f"{TMS_GEOVISIO_URL}/api/collections/{collection_id}/items"

    # Prepare the data to be sent in the request
    data = {
        "position": seq,
        "isBlurred": "false",  # whether the image is blurred or not
        "override_capture_time": gps_time,  # override the capture time
        "override_latitude": float(gps_y),
        "override_longitude": float(gps_x)
    }

    try:
        # Fetch the image from the URL
        response = requests.get(img_url)
        if response.status_code == 200:
            # Prepare the image file for upload
            image_data = io.BytesIO(response.content)
            files_ = {"picture": (Path(img_url).name, image_data, "image/jpeg")}
        else:
            print(f"Failed to fetch image from {img_url}. Status code: {response.status_code}")
            return 404
    except Exception as e:
        print(f"Error fetching image from {img_url}: {e}")
        return 404

    # Send the POST request to upload the image
    try:
        response = requests.post(url, data=data, files=files_)
        if response.status_code in [200, 201, 202]:
            print(f"Uploaded item: {keyname}")
        else:
            print(f"Failed to upload item {keyname}: {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Error uploading item {keyname}: {e}")



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

