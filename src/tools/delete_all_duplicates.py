"""
GeoVisio Collection 刪除工具

功能: 讀取重複報告 CSV，刪除 CSV 中出現的所有 Collection（及其下所有影像）

使用方式:
    python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv --dry-run  # 預覽
    python -m src.tools.delete_all_duplicates -i keyname_duplicates.csv            # 執行刪除
"""

import asyncio
import asyncpg
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, Set, List, Dict
import argparse
import sys
import ast
import re

try:
    from src.config.settings import Settings
except ImportError:
    from ..config.settings import Settings


def parse_date_from_filename(filename: str) -> Optional[str]:
    """
    從檔案名稱解析日期
    
    格式: 20250829113426796_S9GLCPJ76.jpg
          YYYYMMDDHHMMSSMMM_XXXXXXXXX.jpg
    
    Returns:
        日期字串，如 "2025-08-29"，解析失敗則返回 None
    """
    if not filename:
        return None
    
    # 嘗試解析前 8 個字元為日期
    match = re.match(r'^(\d{4})(\d{2})(\d{2})', filename)
    if match:
        year, month, day = match.groups()
        try:
            # 驗證日期有效性
            datetime(int(year), int(month), int(day))
            return f"{year}-{month}-{day}"
        except ValueError:
            pass
    
    return None


def extract_dates_from_filenames(filenames: List[str]) -> Set[str]:
    """
    從檔案名稱列表中提取所有不重複的日期
    """
    dates = set()
    for fn in filenames:
        date = parse_date_from_filename(fn)
        if date:
            dates.add(date)
    return dates


async def delete_collections(csv_path: str, db_url: str, dry_run: bool = False):
    """
    刪除 CSV 中出現的所有 Collection
    """
    print(f"\n{'=' * 60}")
    print(f"🗑️  GeoVisio Collection 刪除工具")
    print(f"{'=' * 60}")
    print(f"📂 輸入檔案: {csv_path}")
    print(f"🔧 模式: {'DRY RUN (預覽)' if dry_run else '⚠️  實際刪除'}")
    print(f"{'=' * 60}\n")
    
    # 1. 讀取 CSV，收集所有 collection_ids 和 filenames
    df = pd.read_csv(csv_path)
    
    all_collection_ids: Set[str] = set()
    all_filenames: List[str] = []
    
    for _, row in df.iterrows():
        # 解析 collection_ids
        if 'collection_ids' in row and pd.notna(row['collection_ids']):
            try:
                col_ids = ast.literal_eval(row['collection_ids'])
                for cid in col_ids:
                    if cid and cid != 'N/A':
                        all_collection_ids.add(cid)
            except:
                pass
        
        # 收集 filenames
        if 'filename' in row and pd.notna(row['filename']):
            all_filenames.append(row['filename'])
    
    # 2. 解析日期
    affected_dates = extract_dates_from_filenames(all_filenames)
    
    print(f"📊 CSV 中的重複組數: {len(df)}")
    print(f"📊 涉及的 Collection 數量: {len(all_collection_ids)}")
    print(f"📊 涉及的日期: {len(affected_dates)} 天")
    
    if affected_dates:
        sorted_dates = sorted(affected_dates)
        print(f"\n📅 影響的拍攝日期:")
        for date in sorted_dates:
            print(f"   - {date}")
    
    if not all_collection_ids:
        print("\n⚠️  未找到任何 Collection ID，請確認 CSV 包含 collection_ids 欄位")
        return
    
    print(f"\n📋 要刪除的 Collection IDs:")
    for cid in sorted(all_collection_ids):
        print(f"   - {cid}")
    
    # 3. 連線資料庫查詢將被刪除的影像數量
    print(f"\n連線至資料庫...")
    conn = await asyncpg.connect(db_url)
    print("✅ 連線成功")
    
    try:
        # 查詢每個 Collection 的影像數量
        print(f"\n📊 各 Collection 影像統計:")
        
        collection_stats: Dict[str, Dict] = {}
        total_pictures = 0
        
        for cid in all_collection_ids:
            # 查詢該 Collection (sequences) 下的影像數量
            stats = await conn.fetchrow("""
                SELECT 
                    s.id::text as collection_id,
                    s.nb_pictures,
                    s.computed_capture_date,
                    COUNT(sp.pic_id) as actual_pic_count
                FROM sequences s
                LEFT JOIN sequences_pictures sp ON s.id = sp.seq_id
                WHERE s.id = $1::uuid
                GROUP BY s.id, s.nb_pictures, s.computed_capture_date
            """, cid)
            
            if stats:
                pic_count = stats['actual_pic_count'] or stats['nb_pictures'] or 0
                collection_stats[cid] = {
                    'pic_count': pic_count,
                    'capture_date': stats['computed_capture_date']
                }
                total_pictures += pic_count
                print(f"   - {cid[:24]}... : {pic_count} 張影像 (拍攝: {stats['computed_capture_date']})")
            else:
                print(f"   - {cid[:24]}... : 找不到 (可能已刪除)")
        
        print(f"\n📊 總計將刪除: {total_pictures} 張影像")
        
        if dry_run:
            print(f"\n{'=' * 60}")
            print(f"⚠️  DRY RUN 模式 - 不會實際刪除任何資料")
            print(f"{'=' * 60}")
            print(f"\n移除 --dry-run 參數來執行實際刪除")
            return affected_dates
        
        # 4. 確認刪除
        print(f"\n⚠️  警告: 即將刪除 {len(all_collection_ids)} 個 Collection，共 {total_pictures} 張影像！")
        print(f"⚠️  此操作無法復原！")
        confirm = input("確定要繼續嗎？輸入 'YES' 確認: ")
        
        if confirm != 'YES':
            print("❌ 已取消")
            return affected_dates
        
        # 5. 開始刪除
        print(f"\n🗑️  開始刪除...")
        
        col_list = list(all_collection_ids)
        
        # 5a. 取得所有要刪除的 picture_ids
        print("   查詢相關影像...")
        pic_ids = await conn.fetch("""
            SELECT DISTINCT pic_id::text 
            FROM sequences_pictures 
            WHERE seq_id = ANY($1::uuid[])
        """, col_list)
        pic_id_list = [r['pic_id'] for r in pic_ids]
        print(f"   找到 {len(pic_id_list)} 張影像")
        
        # 5b. 刪除 sequences_pictures 關聯
        print("   刪除 sequences_pictures 關聯...")
        seq_pic_result = await conn.execute("""
            DELETE FROM sequences_pictures 
            WHERE seq_id = ANY($1::uuid[])
        """, col_list)
        seq_pic_deleted = int(seq_pic_result.split()[-1]) if seq_pic_result else 0
        print(f"   ✅ 刪除 {seq_pic_deleted} 筆關聯")
        
        # 5c. 刪除 pictures 記錄
        if pic_id_list:
            print("   刪除 pictures 記錄...")
            pic_result = await conn.execute("""
                DELETE FROM pictures 
                WHERE id = ANY($1::uuid[])
            """, pic_id_list)
            pic_deleted = int(pic_result.split()[-1]) if pic_result else 0
            print(f"   ✅ 刪除 {pic_deleted} 筆影像")
        else:
            pic_deleted = 0
        
        # 5d. 刪除 sequences (collections) 記錄
        print("   刪除 sequences (collections) 記錄...")
        seq_result = await conn.execute("""
            DELETE FROM sequences 
            WHERE id = ANY($1::uuid[])
        """, col_list)
        seq_deleted = int(seq_result.split()[-1]) if seq_result else 0
        print(f"   ✅ 刪除 {seq_deleted} 筆 Collection")
        
        # 6. 完成報告
        print(f"\n{'=' * 60}")
        print(f"✅ 刪除完成！")
        print(f"{'=' * 60}")
        print(f"   Collections 刪除: {seq_deleted} 個")
        print(f"   Pictures 刪除: {pic_deleted} 張")
        print(f"   關聯記錄刪除: {seq_pic_deleted} 筆")
        print(f"\n📅 已刪除的影像日期:")
        for date in sorted(affected_dates):
            print(f"   - {date}")
        print(f"{'=' * 60}")
        
        return affected_dates
        
    finally:
        await conn.close()
        print("\n資料庫連線已關閉")


async def main():
    parser = argparse.ArgumentParser(description='刪除 CSV 中出現的所有 Collection')
    parser.add_argument('-i', '--input', required=True, help='重複報告 CSV 檔案')
    parser.add_argument('--dry-run', action='store_true', help='預覽模式')
    parser.add_argument('--db-url', default=Settings.DATABASE_URL, help='資料庫連線字串')
    
    args = parser.parse_args()
    
    if not args.db_url:
        print("❌ 錯誤: 未設定 DATABASE_URL")
        sys.exit(1)
    
    if not Path(args.input).exists():
        print(f"❌ 錯誤: 找不到檔案 {args.input}")
        sys.exit(1)
    
    affected_dates = await delete_collections(args.input, args.db_url, args.dry_run)
    
    if affected_dates:
        print(f"\n📋 返回值 - 刪除影像的日期列表:")
        for date in sorted(affected_dates):
            print(f"   {date}")


if __name__ == "__main__":
    asyncio.run(main())