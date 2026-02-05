"""
GeoVisio API 功能測試（修正 Brotli 編碼問題）
"""

import asyncio
import aiohttp
import json
from pathlib import Path

# 載入設定
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.module.TMSUpdate.config.settings import Settings


async def test_geovisio_api():
    """測試 GeoVisio API 功能"""
    
    base_url = Settings.TMS_GEOVISIO_URL.rstrip('/')
    print(f"測試 API: {base_url}")
    print("=" * 60)
    
    # ✅ 關鍵修正：禁用 Brotli，只接受 gzip 或不壓縮
    headers = {
        "Accept-Encoding": "gzip, deflate, identity"
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        
        # ========================================
        # 測試 1: 取得所有 Collections
        # ========================================
        print("\n[測試 1] 取得所有 Collections")
        print("-" * 40)
        
        collections = []
        
        try:
            async with session.get(f"{base_url}/api/collections") as resp:
                print(f"Status: {resp.status}")
                print(f"Content-Encoding: {resp.headers.get('Content-Encoding', 'none')}")
                
                if resp.status == 200:
                    data = await resp.json()
                    
                    print(f"回傳類型: {type(data)}")
                    
                    if isinstance(data, dict):
                        print(f"回傳欄位: {list(data.keys())}")
                        collections = data.get('collections', data.get('features', []))
                    elif isinstance(data, list):
                        collections = data
                    
                    print(f"Collection 數量: {len(collections)}")
                    
                    # 顯示前 3 個 Collection 的結構
                    if collections:
                        print("\n前 3 個 Collection:")
                        for i, col in enumerate(collections[:3]):
                            print(f"\n  [{i+1}] ID: {col.get('id', 'N/A')}")
                            print(f"      Title: {col.get('title', 'N/A')[:50]}...")
                            print(f"      Keywords: {col.get('keywords', [])}")
                            print(f"      欄位: {list(col.keys())}")
                else:
                    error_text = await resp.text()
                    print(f"錯誤: {error_text[:200]}")
                    
        except Exception as e:
            print(f"例外: {type(e).__name__}: {e}")
        
        # ========================================
        # 測試 2: 檢查搜尋參數是否有效
        # ========================================
        print("\n[測試 2] 測試搜尋參數")
        print("-" * 40)
        
        if collections:
            # 用第一個 collection 的 keyword 來測試
            test_keyword = None
            for col in collections[:5]:
                keywords = col.get('keywords', [])
                if keywords:
                    test_keyword = keywords[0]
                    break
            
            if test_keyword:
                print(f"使用測試 keyword: {test_keyword}")
                
                # 先取得無篩選的數量
                try:
                    async with session.get(f"{base_url}/api/collections") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            total = len(data.get('collections', data.get('features', data if isinstance(data, list) else [])))
                            print(f"無篩選: {total} 筆")
                except:
                    pass
                
                # 測試各種搜尋參數
                search_params = [
                    {"keyword": test_keyword},
                    {"q": test_keyword},
                    {"search": test_keyword},
                ]
                
                for params in search_params:
                    try:
                        async with session.get(f"{base_url}/api/collections", params=params) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                if isinstance(data, dict):
                                    count = len(data.get('collections', data.get('features', [])))
                                else:
                                    count = len(data) if isinstance(data, list) else 0
                                print(f"參數 {params}: {count} 筆")
                                
                                # 如果數量不同，表示篩選有效
                                if count != total:
                                    print(f"  → ✅ 篩選有效！")
                            else:
                                print(f"參數 {params}: Status={resp.status}")
                    except Exception as e:
                        print(f"參數 {params}: 例外={e}")
        
        # ========================================
        # 測試 3: 取得單一 Collection 詳細資訊
        # ========================================
        print("\n[測試 3] 取得單一 Collection 詳細資訊")
        print("-" * 40)
        
        collection_id = None
        if collections:
            collection_id = collections[0].get('id')
        
        if collection_id:
            print(f"使用 Collection ID: {collection_id}")
            
            try:
                async with session.get(f"{base_url}/api/collections/{collection_id}") as resp:
                    print(f"Status: {resp.status}")
                    if resp.status == 200:
                        data = await resp.json()
                        print(f"回傳欄位: {list(data.keys())}")
                        print(f"Title: {data.get('title', 'N/A')[:50]}")
                        print(f"Keywords: {data.get('keywords', [])}")
                    else:
                        print(f"錯誤: {await resp.text()[:200]}")
            except Exception as e:
                print(f"例外: {e}")
        else:
            print("無可用的 Collection ID")
        
        # ========================================
        # 測試 4: 取得 Collection 內的 Items
        # ========================================
        print("\n[測試 4] 取得 Collection 內的 Items")
        print("-" * 40)
        
        items = []
        working_endpoint = None
        
        if collection_id:
            # 測試不同的 endpoint 格式
            endpoints = [
                f"/api/collections/{collection_id}/items",
                f"/api/collections/{collection_id}/features",
                f"/api/collections/{collection_id}/images",
                f"/api/items?collection={collection_id}",
            ]
            
            for endpoint in endpoints:
                try:
                    async with session.get(f"{base_url}{endpoint}") as resp:
                        print(f"\n嘗試: {endpoint}")
                        print(f"  Status: {resp.status}")
                        
                        if resp.status == 200:
                            data = await resp.json()
                            print(f"  回傳類型: {type(data)}")
                            
                            if isinstance(data, dict):
                                print(f"  回傳欄位: {list(data.keys())}")
                                items = data.get('items', data.get('features', data.get('images', [])))
                            elif isinstance(data, list):
                                items = data
                            else:
                                items = []
                            
                            print(f"  Item 數量: {len(items)}")
                            
                            if items:
                                working_endpoint = endpoint
                                print(f"  → ✅ 此 endpoint 可用！")
                                break
                                
                        elif resp.status == 404:
                            print(f"  → 此 endpoint 不存在")
                        else:
                            error = await resp.text()
                            print(f"  → 錯誤: {error[:100]}")
                            
                except Exception as e:
                    print(f"  例外: {e}")
        
        # ========================================
        # 測試 5: 檢查 Items 結構
        # ========================================
        print("\n[測試 5] 檢查 Items 結構")
        print("-" * 40)
        
        if items:
            print(f"分析第一個 Item...")
            first_item = items[0]
            
            # 顯示完整結構
            print(f"\n第一個 Item 完整結構:")
            print(json.dumps(first_item, indent=2, ensure_ascii=False, default=str)[:1500])
            
            # 找出可能的識別欄位
            def find_fields(obj, prefix="", results=None):
                if results is None:
                    results = []
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        full_key = f"{prefix}.{k}" if prefix else k
                        if isinstance(v, (str, int, float)) and v:
                            results.append((full_key, str(v)[:50]))
                        elif isinstance(v, dict):
                            find_fields(v, full_key, results)
                return results
            
            print(f"\n所有欄位值:")
            fields = find_fields(first_item)
            for field, value in fields:
                print(f"  {field}: {value}")
        else:
            print("無 items 可分析")
            
            # 嘗試找一個有 items 的 collection
            print("\n嘗試找一個有 items 的 Collection...")
            for col in collections[:10]:
                col_id = col.get('id')
                try:
                    async with session.get(f"{base_url}/api/collections/{col_id}/items") as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, dict):
                                test_items = data.get('items', data.get('features', []))
                            else:
                                test_items = data if isinstance(data, list) else []
                            
                            if test_items:
                                print(f"\n找到有資料的 Collection: {col_id}")
                                print(f"Items 數量: {len(test_items)}")
                                print(f"\n第一個 Item:")
                                print(json.dumps(test_items[0], indent=2, ensure_ascii=False, default=str)[:1500])
                                break
                except:
                    pass
    
    print("\n" + "=" * 60)
    print("測試完成")


if __name__ == "__main__":
    asyncio.run(test_geovisio_api())