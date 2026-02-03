"""API 模組 (重構修正版)"""

from src.module.TMSUpdate.api.exceptions import (
    ImageAlreadyExistsError,
    RetryableUploadError
)
from src.module.TMSUpdate.api.geovisio_api_client import (
    GeoVisioAPIClient,
    # 保留尚存的兼容函數
    create_collection,
    get_all_collections,
    get_collection_by_items_id
)
from src.module.TMSUpdate.api.image_uploader import ImageUploader

# 注意：這裡移除了 upload_images_to_geovisio，
# 因為該邏輯現在已經封裝在 ImageUploader 與 Pipeline 中。

__all__ = [
    'GeoVisioAPIClient',
    'ImageUploader',
    'ImageAlreadyExistsError',
    'RetryableUploadError',
    'create_collection',
    'get_all_collections',
    'get_collection_by_items_id'
]