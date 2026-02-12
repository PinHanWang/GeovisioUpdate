"""
GeoVisio 資料庫重複影像檢查工具

功能:
1. 檢查 KeyName (originalFileName) 重複
2. 檢查 MD5 (original_content_md5) 重複
3. 輸出每張重複影像對應的 collection_id (即 sequences.id)
4. 產生詳細報告

使用方式:
    python check_duplicates.py
    python check_duplicates.py -o ./reports
    python check_duplicates.py -f "20250601094837222_S99S9PJ5S.jpg"
"""

import asyncio
import asyncpg
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict
import argparse
import sys
import os
from dotenv import load_dotenv

# 找到專案根目錄的 .env 檔案
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent
env_path = project_root / '.env'

print(f"📂 專案根目錄: {project_root}")
print(f"📄 .env 路徑: {env_path}")
print(f"   .env 存在: {env_path.exists()}")

# 載入環境變數
load_dotenv(env_path)
DATABASE_URL = os.getenv('DATABASE_URL')

print(f"🔗 DATABASE_URL: {DATABASE_URL[:50] if DATABASE_URL else 'None'}...")


class DuplicateChecker:
    """資料庫重複影像檢查器"""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.conn: Optional[asyncpg.Connection] = None
        
    async def connect(self):
        """建立資料庫連線"""
        print(f"\n連線至資料庫...")
        self.conn = await asyncpg.connect(self.db_url)
        print("✅ 資料庫連線成功")
        
    async def close(self):
        """關閉資料庫連線"""
        if self.conn:
            await self.conn.close()
            print("資料庫連線已關閉")
    
    async def get_total_count(self) -> int:
        """取得影像總數"""
        count = await self.conn.fetchval("SELECT COUNT(*) FROM pictures")
        return count
    
    async def check_keyname_duplicates(self) -> List[Dict]:
        """
        檢查 KeyName (originalFileName) 重複，包含 collection_id (sequences.id)
        """
        print("\n" + "=" * 60)
        print("🔍 檢查 KeyName (originalFileName) 重複...")
        print("=" * 60)
        
        # collection_id 就是 sequences.id
        query = """
            SELECT 
                p.metadata->>'originalFileName' as filename,
                COUNT(DISTINCT p.id) as count,
                array_agg(DISTINCT p.id::text) as picture_ids,
                array_agg(p.inserted_at::text) as inserted_times,
                array_agg(DISTINCT sp.seq_id::text) as collection_ids
            FROM pictures p
            LEFT JOIN sequences_pictures sp ON p.id = sp.pic_id
            WHERE p.metadata->>'originalFileName' IS NOT NULL
            GROUP BY p.metadata->>'originalFileName'
            HAVING COUNT(DISTINCT p.id) > 1
            ORDER BY COUNT(DISTINCT p.id) DESC
            LIMIT 1000
        """
        
        records = await self.conn.fetch(query)
        
        duplicates = []
        for r in records:
            # 處理 NULL 值
            col_ids = [c if c else 'N/A' for c in (r['collection_ids'] or [])]
            
            duplicates.append({
                'filename': r['filename'],
                'count': r['count'],
                'picture_ids': r['picture_ids'] or [],
                'inserted_times': r['inserted_times'] or [],
                'collection_ids': col_ids
            })
        
        total_duplicates = len(duplicates)
        total_duplicate_images = sum(d['count'] for d in duplicates)
        
        print(f"\n📊 KeyName 重複統計:")
        print(f"   - 重複的檔名數量: {total_duplicates}")
        print(f"   - 涉及的影像總數: {total_duplicate_images}")
        print(f"   - 可節省的空間 (移除重複後): {total_duplicate_images - total_duplicates} 張")
        
        if duplicates:
            print(f"\n📋 前 10 個重複最多的檔名:")
            for i, d in enumerate(duplicates[:10], 1):
                print(f"   {i}. {d['filename']} (重複 {d['count']} 次)")
                # 顯示 collection_ids
                unique_cols = list(set(d['collection_ids']))
                for col in unique_cols[:3]:
                    if col != 'N/A':
                        print(f"      → Collection: {col[:16]}...")
        
        return duplicates
    
    async def check_md5_duplicates(self) -> List[Dict]:
        """
        檢查 MD5 (original_content_md5) 重複，包含 collection_id
        """
        print("\n" + "=" * 60)
        print("🔍 檢查 MD5 (original_content_md5) 重複...")
        print("=" * 60)
        
        query = """
            SELECT 
                p.original_content_md5::text as md5,
                COUNT(DISTINCT p.id) as count,
                array_agg(DISTINCT p.id::text) as picture_ids,
                array_agg(p.metadata->>'originalFileName') as filenames,
                array_agg(p.inserted_at::text) as inserted_times,
                array_agg(DISTINCT sp.seq_id::text) as collection_ids
            FROM pictures p
            LEFT JOIN sequences_pictures sp ON p.id = sp.pic_id
            WHERE p.original_content_md5 IS NOT NULL
            GROUP BY p.original_content_md5
            HAVING COUNT(DISTINCT p.id) > 1
            ORDER BY COUNT(DISTINCT p.id) DESC
            LIMIT 1000
        """
        
        records = await self.conn.fetch(query)
        
        duplicates = []
        for r in records:
            col_ids = [c if c else 'N/A' for c in (r['collection_ids'] or [])]
            
            duplicates.append({
                'md5': r['md5'],
                'count': r['count'],
                'picture_ids': r['picture_ids'] or [],
                'filenames': r['filenames'] or [],
                'inserted_times': r['inserted_times'] or [],
                'collection_ids': col_ids
            })
        
        total_duplicates = len(duplicates)
        total_duplicate_images = sum(d['count'] for d in duplicates)
        
        print(f"\n📊 MD5 重複統計:")
        print(f"   - 重複的 MD5 數量: {total_duplicates}")
        print(f"   - 涉及的影像總數: {total_duplicate_images}")
        print(f"   - 可節省的空間 (移除重複後): {total_duplicate_images - total_duplicates} 張")
        
        if duplicates:
            print(f"\n📋 前 10 個重複最多的 MD5:")
            for i, d in enumerate(duplicates[:10], 1):
                sample_files = [f for f in d['filenames'][:3] if f]
                files_str = ', '.join(sample_files)
                if len(d['filenames']) > 3:
                    files_str += f" ... 等 {len(d['filenames'])} 個檔案"
                print(f"   {i}. {d['md5'][:16]}... (重複 {d['count']} 次)")
                print(f"      檔名: {files_str}")
                # 顯示 collection_ids
                unique_cols = list(set(d['collection_ids']))
                cols_str = ', '.join(c[:8] + '...' if c != 'N/A' else 'N/A' for c in unique_cols[:3])
                print(f"      Collections: {cols_str}")
        
        return duplicates
    
    async def check_keyname_md5_mismatch(self) -> List[Dict]:
        """
        檢查相同 KeyName 但不同 MD5 的情況
        """
        print("\n" + "=" * 60)
        print("🔍 檢查相同 KeyName 但不同 MD5...")
        print("=" * 60)
        
        query = """
            SELECT 
                metadata->>'originalFileName' as filename,
                COUNT(DISTINCT original_content_md5) as unique_md5_count,
                array_agg(DISTINCT original_content_md5::text) as md5_list,
                COUNT(*) as total_count
            FROM pictures 
            WHERE metadata->>'originalFileName' IS NOT NULL
              AND original_content_md5 IS NOT NULL
            GROUP BY metadata->>'originalFileName'
            HAVING COUNT(DISTINCT original_content_md5) > 1
            ORDER BY COUNT(DISTINCT original_content_md5) DESC
            LIMIT 100
        """
        
        records = await self.conn.fetch(query)
        
        mismatches = []
        for r in records:
            mismatches.append({
                'filename': r['filename'],
                'unique_md5_count': r['unique_md5_count'],
                'md5_list': r['md5_list'],
                'total_count': r['total_count']
            })
        
        print(f"\n📊 KeyName-MD5 不一致統計:")
        print(f"   - 檔名相同但內容不同的數量: {len(mismatches)}")
        
        if mismatches:
            print(f"\n⚠️  這些檔案可能被修改過:")
            for i, m in enumerate(mismatches[:10], 1):
                print(f"   {i}. {m['filename']}")
                print(f"      有 {m['unique_md5_count']} 個不同的 MD5，共 {m['total_count']} 筆記錄")
        
        return mismatches
    
    async def get_duplicate_details(self, filename: str) -> List[Dict]:
        """取得特定檔名的重複詳情，包含 collection_id"""
        query = """
            SELECT 
                p.id::text,
                p.metadata->>'originalFileName' as filename,
                p.original_content_md5::text as md5,
                p.inserted_at,
                p.status::text,
                sp.seq_id::text as collection_id
            FROM pictures p
            LEFT JOIN sequences_pictures sp ON p.id = sp.pic_id
            WHERE p.metadata->>'originalFileName' = $1
            ORDER BY p.inserted_at
        """
        
        records = await self.conn.fetch(query, filename)
        return [dict(r) for r in records]
    
    async def get_collection_summary(self, duplicates: List[Dict]) -> Dict[str, int]:
        """
        統計重複影像涉及的 Collection 數量
        """
        collection_counts = {}
        
        for dup in duplicates:
            for col_id in dup.get('collection_ids', []):
                if col_id and col_id != 'N/A':
                    collection_counts[col_id] = collection_counts.get(col_id, 0) + 1
        
        return collection_counts
    
    async def generate_report(self, output_dir: str = "output/duplicate_reports"):
        """產生完整報告並儲存為 CSV"""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 1. 總覽
        total = await self.get_total_count()
        print("\n" + "=" * 60)
        print("📊 資料庫影像總覽")
        print("=" * 60)
        print(f"   影像總數: {total:,}")
        
        # 2. KeyName 重複
        keyname_dups = await self.check_keyname_duplicates()
        if keyname_dups:
            df_keyname = pd.DataFrame(keyname_dups)
            keyname_file = output_path / f"{timestamp}_keyname_duplicates.csv"
            df_keyname.to_csv(keyname_file, index=False, encoding='utf-8-sig')
            print(f"\n💾 KeyName 重複報告已儲存: {keyname_file}")
            
            # Collection 統計
            col_summary = await self.get_collection_summary(keyname_dups)
            if col_summary:
                print(f"\n📊 涉及的 Collection 統計 (前 10 個):")
                sorted_cols = sorted(col_summary.items(), key=lambda x: x[1], reverse=True)
                for col_id, count in sorted_cols[:10]:
                    print(f"   - {col_id[:24]}... : {count} 張重複")
        
        # 3. MD5 重複
        md5_dups = await self.check_md5_duplicates()
        if md5_dups:
            df_md5 = pd.DataFrame(md5_dups)
            md5_file = output_path / f"{timestamp}_md5_duplicates.csv"
            df_md5.to_csv(md5_file, index=False, encoding='utf-8-sig')
            print(f"\n💾 MD5 重複報告已儲存: {md5_file}")
        
        # 4. KeyName-MD5 不一致
        mismatches = await self.check_keyname_md5_mismatch()
        if mismatches:
            df_mismatch = pd.DataFrame(mismatches)
            mismatch_file = output_path / f"{timestamp}_keyname_md5_mismatch.csv"
            df_mismatch.to_csv(mismatch_file, index=False, encoding='utf-8-sig')
            print(f"\n💾 KeyName-MD5 不一致報告已儲存: {mismatch_file}")
        
        # 5. 摘要
        print("\n" + "=" * 60)
        print("📋 檢查摘要")
        print("=" * 60)
        print(f"   影像總數: {total:,}")
        print(f"   KeyName 重複組數: {len(keyname_dups)}")
        print(f"   KeyName 重複影像數: {sum(d['count'] for d in keyname_dups) if keyname_dups else 0}")
        print(f"   MD5 重複組數: {len(md5_dups)}")
        print(f"   MD5 重複影像數: {sum(d['count'] for d in md5_dups) if md5_dups else 0}")
        print(f"   KeyName-MD5 不一致: {len(mismatches)}")
        
        # Collection 統計摘要
        if keyname_dups:
            col_summary = await self.get_collection_summary(keyname_dups)
            print(f"   涉及的 Collection 數量: {len(col_summary)}")
        
        print("=" * 60)


async def main():
    """主程式"""
    parser = argparse.ArgumentParser(description='GeoVisio 資料庫重複影像檢查工具')
    parser.add_argument('-o', '--output', default='output/duplicate_reports', help='報告輸出目錄')
    parser.add_argument('-f', '--filename', help='查詢特定檔名的重複詳情')
    parser.add_argument('--db-url', default=DATABASE_URL, help='資料庫連線字串')
    
    args = parser.parse_args()
    
    if not args.db_url:
        print("❌ 錯誤: 未設定資料庫連線字串")
        print("   請設定 DATABASE_URL 環境變數或使用 --db-url 參數")
        sys.exit(1)
    
    checker = DuplicateChecker(args.db_url)
    
    try:
        await checker.connect()
        
        if args.filename:
            print(f"\n🔍 查詢檔名: {args.filename}")
            details = await checker.get_duplicate_details(args.filename)
            
            if details:
                print(f"\n找到 {len(details)} 筆記錄:")
                for i, d in enumerate(details, 1):
                    print(f"\n   [{i}] ID: {d['id']}")
                    print(f"       MD5: {d['md5']}")
                    print(f"       狀態: {d['status']}")
                    print(f"       建立時間: {d['inserted_at']}")
                    print(f"       Collection ID: {d['collection_id'] or 'N/A'}")
            else:
                print(f"   找不到檔名: {args.filename}")
        else:
            await checker.generate_report(args.output)
            
    except Exception as e:
        print(f"\n❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await checker.close()


if __name__ == "__main__":
    asyncio.run(main())