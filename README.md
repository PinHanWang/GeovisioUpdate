# GeoVisio數據上傳系統

## 專案概述

GeoVisio數據上傳系統是一個專為處理和上傳地理空間圖像數據到GeoVisio平台設計的Python應用程式。本系統能夠自動處理CSV格式的GPS軌跡數據，進行數據預處理，並批量上傳圖像到GeoVisio集合中，主要應用於交通基礎設施數據收集和道路資訊管理。

## 主要功能

- **數據預處理**：自動處理GPS軌跡數據，包含時間解析、座標轉換和軌跡分組
- **智能分組**：基於時間間隔和距離閾值自動將軌跡分組為不同序列
- **批量上傳**：異步上傳圖像到GeoVisio平台，支援並發處理
- **錯誤處理**：完整的重試機制和失敗記錄系統
- **API管理**：完整的GeoVisio API操作，包含集合創建、查詢和圖像上傳

## 專案架構

```
GeoVisioUpdate/
├── src/
│   └── module/
│       ├── ResultsPostProcessing/          # 結果後處理模組
│       ├── TMSUpdate/                      # 影像資料上傳(TMS local server)
│       │   ├── __init__.py
│       │   ├── main.py                    # 主要執行程式
│       │   ├── DataPreprocessing.py      # 數據預處理模組
│       │   ├── GeovisioApi.py            # GeoVisio API 操作
│       │   ├── failures.py              # 失敗記錄管理
│       │   └── logger.py                # 日誌配置
│       ├── TWCCUpdate/                     # 影像資料上傳(TWCC cloud server)用於AIROAD
│       │   ├── __init__.py
│       │   ├── geoVisioUpdate.py
│       │   ├── makeExif.py
│       │   ├── makeScreenshot.py
│       │   └── useGeoVisioApi.py
│       └── utils/                          # 工具模組
│           ├── __init__.py
│           └── [工具函數]
├── data/                                   # 數據存放目錄
├── docs/                                  # 文檔目錄
├── history/                               # 歷史記錄
├── logs/                                  # 日誌和報告輸出
├── notebooks/                             # Jupyter筆記本
├── output/                               # API響應和結果輸出
├── projects/                             # 專案配置
├── scripts/                              # 腳本文件
├── tests/                                # 測試文件
├── .env                                  # 環境變數配置
├── .env.example                          # 環境變數範例
├── requirements.txt                      # Python依賴套件
└── README.md                            # 專案說明文檔
```

## 核心模組介紹

### 📊 DataPreprocessing - 數據預處理模組

**核心功能：**
- GPS時間解析：從KeyName中提取並格式化GPS時間戳
- 座標系統轉換：WGS84到TWD97座標系統轉換
- 軌跡分析：計算時間差和距離差
- 智能分組：基於時間和距離閾值自動分組序列

**主要函數：**
```python
def parse_keyname_to_gpstime(keyname: str) -> datetime
def get_time_difference(df: pd.DataFrame) -> pd.DataFrame
def get_distance_difference(df: pd.DataFrame) -> pd.DataFrame  
def split_groups_by_time_and_distance(df: pd.DataFrame, time_threshold: int, distance_threshold: float) -> pd.DataFrame
```

### 🌐 GeovisioApi - API 操作模組

**核心功能：**
- 集合管理：創建、查詢和管理GeoVisio集合
- 異步上傳：支援並發圖像上傳
- 重試機制：使用tenacity庫實現智能重試
- 錯誤處理：完整的異常處理和失敗記錄

**主要函數：**
```python
async def create_collection(title, description, keywords, bbox=None, start_time=None)
async def upload_image_to_collection(session, collection_id, keyname, gps_time, gps_x, gps_y, speed, img_url, seq)
async def upload_images_to_geovisio(df, collection_id)
async def get_all_collections()
```

### 📝 Main - 主執行模組

**核心功能：**
- 完整的數據處理流程管理
- 按日期分組處理數據
- 並發序列上傳管理
- 處理進度監控和日誌記錄

## 環境需求

### 系統需求
- Python 3.9+（支援zoneinfo）
- 網路連接（用於API操作）

### Python套件依賴
```bash
pip install -r requirements.txt
```

## 安裝與設定

1. **克隆專案**
```bash
git clone <repository-url>
cd GeoVisioUpdate
```

2. **安裝依賴套件**
```bash
pip install -r requirements.txt
```

3. **環境變數設定**
創建 `.env` 文件並設定以下變數（可參考 `.env.example`）：
```env
## GeoVisio API configuration
# TMS local server
TMS_GEOVISIO_URL=http://192.168.61.1:5000
# TWCC cloud server  
TWCC_GEOVISIO_URL=http://202.5.253.237:5000

## Collection record path
CSV_FILE_PATH=E:\Path\To\Your\Data.csv

## Image storage path
# Base path for storing images
IMAGE_BASE_PATH=E:\Path\To\Your\Images

## Upload configuration
# Maximum number of concurrent uploads at once
MAX_CONCURRENT_UPLOADS=5
# Timeout for each upload request in seconds
UPLOAD_TIMEOUT=60
# Sequence Delay
SEQUENCE_DELAY=3
# Batch delay
BATCH_DELAY=300

## Data preprocessing configuration
VEHICLE_TYPE=CAR  # 'CAR' or 'MOTORCYCLE'
```

**重要設定說明：**
- 支援本地TMS服務器和TWCC雲端服務器兩種部署
- 根據實際文件路徑調整 `CSV_FILE_PATH` 和 `IMAGE_BASE_PATH`
- 車輛類型決定預處理參數：CAR適用於10米以上道路，MOTORCYCLE適用於人行道

4. **驗證設定**
```python
python -c "from dotenv import load_dotenv; load_dotenv(); print('Environment loaded successfully')"
```

## 使用指南

### 基本使用流程

#### 1. 數據預處理

```python
from DataPreprocessing import data_preprocessing
from pathlib import Path

# 處理CSV數據
csv_path = Path("data/your_data.csv")
processed_data = data_preprocessing(
    csv_path, 
    time_threshold=500,      # 汽車：500秒，機車：300秒
    distance_threshold=200.0  # 汽車：200米，機車：20米
)
```

#### 2. GeoVisio集合操作

```python
from GeovisioApi import create_collection, upload_images_to_geovisio
import asyncio

# 創建新集合
async def create_new_collection():
    collection_id = await create_collection(
        title="測試集合",
        description="測試數據上傳",
        keywords=["測試", "API", "上傳"]
    )
    return collection_id

# 上傳圖像到集合
async def upload_data(df, collection_id):
    result = await upload_images_to_geovisio(df, collection_id)
    return result
```

#### 3. 完整處理流程

```bash
# 運行主程式
python main.py
```

### 配置參數說明

**車輛類型設定：**
- `VEHICLE_TYPE=CAR`：適用於10米以上道路數據
  - 時間閾值：500秒
  - 距離閾值：200米
- `VEHICLE_TYPE=MOTORCYCLE`：適用於人行道標線數據
  - 時間閾值：300秒
  - 距離閾值：20米

**並發控制：**
- `MAX_CONCURRENT_UPLOADS`：同時上傳的最大數量
- `UPLOAD_TIMEOUT`：單次上傳超時時間（秒）
- `SEQUENCE_DELAY`：序列間延遲時間（秒）
- `BATCH_DELAY`：批次間延遲時間（秒）

### 數據格式要求

**輸入CSV文件必須包含以下欄位：**
```csv
KeyName,GPS_X,GPS_Y,speed,url
20250101120000123,121.5654,25.0330,30.5,http://example.com/image.jpg
```

**處理後的數據格式：**
```csv
KeyName,GPSTime,GPSTime_diff,GPS_X,GPS_Y,distance_to_prev,group_id,speed,url
```

## 錯誤處理和日誌

### 日誌系統
- 自動創建 `logs/` 目錄
- 按時間戳命名日誌文件
- 同時輸出到文件和控制台
- 支援不同日誌級別（DEBUG、INFO、WARNING、ERROR）

### 失敗處理
系統會自動記錄並保存失敗案例：
- `upload_failures.csv`：上傳失敗的圖像記錄
- `failed_collections.csv`：處理失敗的集合記錄
- `processing_results.csv`：整體處理結果統計

### 重試機制
使用tenacity庫實現智能重試：
- 最多重試3次
- 固定等待2秒間隔
- 針對網路錯誤和超時自動重試

## API 使用範例

### 查詢所有集合
```python
import asyncio
from GeovisioApi import get_all_collections

async def main():
    collections = await get_all_collections()
    print(f"找到 {len(collections)} 個集合")

asyncio.run(main())
```

### 創建自訂集合
```python
collection_id = await create_collection(
    title="交工案第一分案資料蒐集",
    description="10米以上道路數據收集",
    keywords=["交工案", "道路", "數據收集"],
    bbox=[121.0, 24.5, 122.0, 25.5],  # 台北市範圍
    start_time="2025-01-01T00:00:00Z"
)
```

## 監控和維護

### 處理進度監控
```python
# 系統會自動記錄處理進度
logger.info(f"Processing date {date_count}/{num_dates}: {collection_date}")
logger.info(f"Successfully uploaded {successful_uploads} images, {failed} failed")
```

### 性能優化建議
1. 根據網路狀況調整 `MAX_CONCURRENT_UPLOADS`
2. 監控記憶體使用，必要時分批處理大型數據集
3. 定期清理日誌文件以節省磁碟空間

## 故障排除

### 常見問題

1. **連接超時**
   - 檢查網路連接
   - 調整 `UPLOAD_TIMEOUT` 設定
   - 確認 GeoVisio 服務狀態

2. **圖像文件未找到**
   - 確認 `IMAGE_BASE_PATH` 設定正確
   - 檢查圖像文件存在性
   - 驗證文件權限

3. **CSV 解析錯誤**
   - 確認CSV格式符合要求
   - 檢查必要欄位是否存在
   - 驗證GPS座標格式

## 開發狀態

- ✅ **數據預處理**：GPS軌跡解析和分組
- ✅ **API集成**：完整的GeoVisio API操作
- ✅ **異步上傳**：並發圖像上傳功能
- ✅ **錯誤處理**：完善的重試機制和失敗記錄
- ✅ **日誌系統**：詳細的處理日誌和統計報告

## 貢獻指南

1. Fork 本專案
2. 創建功能分支 (`git checkout -b feature/NewFeature`)
3. 提交更改 (`git commit -m 'Add NewFeature'`)
4. 推送到分支 (`git push origin feature/NewFeature`)
5. 開啟 Pull Request

## 授權資訊

本專案為內部開發工具，請遵循公司相關使用規定。

---

**技術支援：**
如有技術問題或需要協助，請聯絡開發團隊或創建Issue。