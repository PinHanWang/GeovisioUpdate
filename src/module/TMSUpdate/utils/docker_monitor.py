import asyncio
import aiohttp
import logging
import os
from dotenv import load_dotenv
logger = logging.getLogger(__name__)

# 載入環境變數
load_dotenv()   
class HawserDockerMonitor:
    def __init__(self):
        """
        初始化監控器，從環境變數讀取配置。
        目標：監控 192.168.61.1:5001 的容器效能 (透過 Hawser 2376)
        """
        # 監控目標伺服器 IP (.61.1)
        self.target_ip = os.getenv('DOCKER_TARGET_IP')
        # Hawser API 地址 (2376 Port)
        self.hawser_url = f"http://{self.target_ip}:2376/v1/containers"
        
        # Discord 配置
        self.token = os.getenv('DISCORD_BOT_TOKEN')
        self.channel_id = os.getenv('DISCORD_CHANNEL_ID')
        
        # 容器資訊
        self.container_name = os.getenv('DOCKER_CONTAINER_NAME')
        self.service_port = "5001"
        
        # 告警閥值 (3GB = 3072 MB)
        self.mem_threshold_mb = 3072 
        
        self._stop_event = asyncio.Event()

    async def send_to_discord(self, message: str):
        """發送訊息至指定 Discord 頻道"""
        if not self.token or not self.channel_id:
            logger.warning("Discord Token 或 Channel ID 缺失，跳過發送。")
            return
            
        url = f"https://discord.com/api/v10/channels/{self.channel_id}/messages"
        headers = {
            "Authorization": f"Bot {self.token}",
            "Content-Type": "application/json"
        }
        payload = {"content": message}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"Discord API 錯誤: {resp.status}, {error_text}")
        except Exception as e:
            logger.error(f"無法連線至 Discord API: {e}")

    async def start(self, interval=300):
        """
        啟動監控循環。
        :param interval: 回傳頻率（秒），預設 300 秒 = 5 分鐘
        """
        logger.info(f"啟動監控任務：目標伺服器 {self.target_ip} (容器: {self.container_name})")
        
        # 啟動通知
        start_msg = (
            f"🚀 **GeoVisio 效能監控已部署**\n"
            f"監控目標：`{self.target_ip}:{self.service_port}`\n"
            f"回報頻率：每 {interval // 60} 分鐘\n"
            f"告警門檻：`> {self.mem_threshold_mb} MB`"
        )
        await self.send_to_discord(start_msg)

        try:
            async with aiohttp.ClientSession() as session:
                while not self._stop_event.is_set():
                    # 向 Hawser API 請求數據
                    stats_url = f"{self.hawser_url}/{self.container_name}/stats"
                    
                    try:
                        async with session.get(stats_url, timeout=10) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                
                                # 解析記憶體數字 (單位轉換為 MB)
                                # 注意：請根據您的 Hawser 版本回傳格式微調路徑
                                mem_usage_bytes = data.get('memory_stats', {}).get('usage', 0)
                                mem_usage_mb = mem_usage_bytes / (1024 ** 2)
                                
                                # 解析 CPU 使用率
                                cpu_perc = data.get('cpu_stats', {}).get('cpu_usage', {}).get('percent', 0.0)
                                
                                # 組合回報訊息
                                report = (
                                    f"📊 **定期效能快報**\n"
                                    f"服務：`GeoVisio (Port {self.service_port})`\n"
                                    f"記憶體：`{mem_usage_mb:.2f} MB`\n"
                                    f"CPU：`{cpu_perc:.1f}%`"
                                )
                                
                                # 🚨 3GB 告警邏輯
                                if mem_usage_mb > self.mem_threshold_mb:
                                    report = (
                                        f"🚨 **【緊急告警：記憶體溢出風險】**\n"
                                        f"目前的記憶體使用量 (`{mem_usage_mb:.2f} MB`) 已超過設定上限 `{self.mem_threshold_mb} MB`！\n"
                                        f"請檢查 .61.3 伺服器的上傳負載。"
                                    )
                                
                                await self.send_to_discord(report)
                                logger.info(f"已回傳效能數據至 Discord: {mem_usage_mb:.2f} MB")
                            else:
                                logger.warning(f"無法從 Hawser 讀取數據，HTTP 狀態碼: {resp.status}")
                                
                    except Exception as e:
                        logger.error(f"讀取 Hawser API 時發生錯誤: {e}")

                    # 等待下一個周期 (預設 5 分鐘)
                    await asyncio.sleep(interval)
                    
        except asyncio.CancelledError:
            logger.info("監控任務被取消。")
        finally:
            logger.info("監控循環結束。")

    def stop(self):
        """外部調用停止監控"""
        self._stop_event.set()
        logger.info("已接收停止訊號，準備關閉 Docker 監控...")