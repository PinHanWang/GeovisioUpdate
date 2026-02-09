import asyncio
import os
from docker_monitor import HawserDockerMonitor
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent.parent / ".env")

async def test_discord_notification():
    # 1. 載入環境變數
    
    print("=== 開始 Discord 監控通知測試 ===")
    monitor = HawserDockerMonitor()
    
    # 2. 測試一般訊息發送
    print("測試 1: 發送啟動通知...")
    start_msg = "🧪 **這是一則測試訊息**：監控模組連線測試中..."
    await monitor.send_to_discord(start_msg)
    
    # 3. 測試告警邏輯
    print("測試 2: 模擬記憶體超過 3GB 的告警訊息...")
    fake_mem_mb = 3500.55  # 模擬 3.5 GB
    alert_report = (
        f"🚨 **【緊急告警：測試模擬】**\n"
        f"目前的記憶體使用量 (`{fake_mem_mb:.2f} MB`) 已超過設定上限 `3072 MB`！\n"
        f"這是一則手動觸發的測試告警。"
    )
    await monitor.send_to_discord(alert_report)
    
    print("=== 測試完成，請檢查你的 Discord 頻道 ===")

if __name__ == "__main__":
    # 確保環境變數有載入
    if not os.getenv("DISCORD_BOT_TOKEN") or not os.getenv("DISCORD_CHANNEL_ID"):
        print("❌ 錯誤：找不到 DISCORD_BOT_TOKEN 或 DISCORD_CHANNEL_ID")
        print("請確認 .env 檔案內容正確。")
    else:
        asyncio.run(test_discord_notification())