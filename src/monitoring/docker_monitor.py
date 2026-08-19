"""
Docker 容器效能監控模組

透過 Hawser API 監控 GeoVisio 容器的記憶體與 CPU 使用率，
並在超過閾值時發送 Discord 告警。

Hawser 代理標準 Docker Remote API:
- 端點格式: /containers/{id}/stats?stream=false
- 文檔: https://docs.docker.com/engine/api/v1.41/#tag/Container/operation/ContainerStats
"""

import asyncio
import aiohttp
import logging

# 導入設定
try:
    from src.config.settings import Settings
except ImportError:
    from ..config.settings import Settings

logger = logging.getLogger(__name__)

# Hawser 代理固定監聽埠，各部署環境不會變動，不需要獨立設定
_HAWSER_PORT = 2376


class HawserDockerMonitor:
    def __init__(self):
        """
        初始化監控器，從 Settings 讀取配置。
        """
        # 從 Settings 讀取配置
        self.target_ip = Settings.DOCKER_TARGET_IP
        self.hawser_port = _HAWSER_PORT
        
        # Hawser 代理標準 Docker API，不需要 /v1 前綴
        # 正確格式: http://{ip}:{port}/containers/{name}/stats?stream=false
        self.base_url = f"http://{self.target_ip}:{self.hawser_port}"
        
        # Discord 配置
        self.token = Settings.DISCORD_BOT_TOKEN
        self.channel_id = Settings.DISCORD_CHANNEL_ID
        
        # 容器資訊
        self.container_name = Settings.DOCKER_CONTAINER_NAME
        self.service_port = "5001"
        
        # 告警閥值
        self.mem_threshold_mb = Settings.MONITOR_MEM_THRESHOLD_MB
        
        self._stop_event = asyncio.Event()
        
        logger.info(
            "Docker 監控器 - 初始化完成: 目標=%s:%d, 容器=%s, 告警閾值=%d MB",
            self.target_ip, self.hawser_port, self.container_name, self.mem_threshold_mb
        )

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
                        logger.error("Discord API 錯誤: %d, %s", resp.status, error_text)
        except Exception as e:
            logger.error("無法連線至 Discord API: %s", e)

    def _calculate_cpu_percent(self, stats: dict) -> float:
        """
        計算 CPU 使用率百分比
        
        Docker API 回傳的是累計值，需要計算差值
        簡化版：使用 precpu_stats 與 cpu_stats 的差值計算
        """
        try:
            cpu_stats = stats.get('cpu_stats', {})
            precpu_stats = stats.get('precpu_stats', {})
            
            # 取得 CPU 使用量
            cpu_usage = cpu_stats.get('cpu_usage', {}).get('total_usage', 0)
            precpu_usage = precpu_stats.get('cpu_usage', {}).get('total_usage', 0)
            
            # 取得系統 CPU 使用量
            system_cpu = cpu_stats.get('system_cpu_usage', 0)
            presystem_cpu = precpu_stats.get('system_cpu_usage', 0)
            
            # 計算差值
            cpu_delta = cpu_usage - precpu_usage
            system_delta = system_cpu - presystem_cpu
            
            if system_delta > 0 and cpu_delta > 0:
                # 取得 CPU 核心數
                online_cpus = cpu_stats.get('online_cpus', 1)
                if online_cpus == 0:
                    online_cpus = len(cpu_stats.get('cpu_usage', {}).get('percpu_usage', [1]))
                
                cpu_percent = (cpu_delta / system_delta) * online_cpus * 100.0
                return round(cpu_percent, 2)
            
            return 0.0
        except Exception as e:
            logger.warning("計算 CPU 使用率失敗: %s", e)
            return 0.0

    async def check_hawser_health(self, session: aiohttp.ClientSession) -> bool:
        """檢查 Hawser 服務健康狀態"""
        health_url = f"{self.base_url}/_hawser/health"
        try:
            async with session.get(health_url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.debug("Hawser 健康檢查: %s", data)
                    return data.get('status') == 'healthy'
        except Exception as e:
            logger.warning("Hawser 健康檢查失敗: %s", e)
        return False

    async def start(self, interval: int = 300):
        """
        啟動監控循環。
        
        Args:
            interval: 回報頻率（秒），預設 300 秒 = 5 分鐘
        """
        logger.info("啟動監控任務：目標伺服器 %s (容器: %s)", self.target_ip, self.container_name)
        
        # 啟動通知
        start_msg = (
            f"🚀 **GeoVisio 效能監控**\n"
            f"監控目標容器：`{self.target_ip}:{self.service_port}`\n"
            f"回報頻率：每 {interval // 60} 分鐘\n"
            f"告警門檻：`> {self.mem_threshold_mb} MB`"
        )
        await self.send_to_discord(start_msg)

        # Docker API stats 端點
        # 重要：必須加上 stream=false，否則會持續串流資料
        stats_url = f"{self.base_url}/containers/{self.container_name}/stats?stream=false"
        logger.info("Stats API 端點: %s", stats_url)

        try:
            async with aiohttp.ClientSession() as session:
                # 先檢查 Hawser 健康狀態
                if await self.check_hawser_health(session):
                    logger.info("Hawser 服務健康檢查通過")
                else:
                    logger.warning("Hawser 服務可能不健康，但仍嘗試繼續")
                
                while not self._stop_event.is_set():
                    try:
                        # 使用較長的 timeout，因為 stats 端點需要收集資料
                        async with session.get(stats_url, timeout=30) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                
                                # 解析記憶體使用量 (單位轉換為 MB)
                                mem_stats = data.get('memory_stats', {})
                                mem_usage_bytes = mem_stats.get('usage', 0)
                                # 減去快取以取得實際使用量（如果有的話）
                                cache_bytes = mem_stats.get('stats', {}).get('cache', 0)
                                actual_mem_bytes = mem_usage_bytes - cache_bytes
                                mem_usage_mb = actual_mem_bytes / (1024 ** 2)
                                
                                # 記憶體限制
                                mem_limit_bytes = mem_stats.get('limit', 0)
                                mem_limit_mb = mem_limit_bytes / (1024 ** 2) if mem_limit_bytes else 0
                                
                                # 計算 CPU 使用率
                                cpu_percent = self._calculate_cpu_percent(data)
                                
                                # 組合回報訊息
                                if mem_limit_mb > 0:
                                    mem_percent = (mem_usage_mb / mem_limit_mb) * 100
                                    mem_info = f"`{mem_usage_mb:.1f}` / `{mem_limit_mb:.0f}` MB ({mem_percent:.1f}%)"
                                else:
                                    mem_info = f"`{mem_usage_mb:.1f}` MB"
                                
                                report = (
                                    f"📊 **定期容器效能回報**\n"
                                    f"容器：`GeoVisio (Port {self.service_port})`\n"
                                    f"記憶體：{mem_info}\n"
                                    f"CPU：`{cpu_percent:.1f}%`"
                                )
                                
                                # 🚨 告警邏輯
                                if mem_usage_mb > self.mem_threshold_mb:
                                    report = (
                                        f"🚨 **【緊急：記憶體溢出風險】**\n"
                                        f"目前的記憶體使用量 (`{mem_usage_mb:.1f} MB`) "
                                        f"已超過設定上限 `{self.mem_threshold_mb} MB`！\n"
                                        f"請檢查 {self.target_ip} 伺服器的上傳負載。"
                                    )
                                
                                await self.send_to_discord(report)
                                logger.info(
                                    "容器效能回報: 記憶體=%.1f MB, CPU=%.1f%%",
                                    mem_usage_mb, cpu_percent
                                )
                                
                            elif resp.status == 404:
                                logger.error(
                                    "容器 '%s' 不存在或未運行，請檢查容器名稱",
                                    self.container_name
                                )
                                await self.send_to_discord(
                                    f"⚠️ **監控警告**\n"
                                    f"容器 `{self.container_name}` 未找到，可能已停止運行。"
                                )
                            else:
                                # 嘗試讀取錯誤訊息
                                try:
                                    error_body = await resp.text()
                                    logger.warning(
                                        "無法從 Hawser 讀取數據，HTTP %d: %s",
                                        resp.status, error_body[:200]
                                    )
                                except:
                                    logger.warning(
                                        "無法從 Hawser 讀取數據，HTTP 狀態碼: %d",
                                        resp.status
                                    )
                                
                    except asyncio.TimeoutError:
                        logger.warning("Hawser API 請求超時")
                    except aiohttp.ClientError as e:
                        logger.error("Hawser 連線錯誤: %s", e)
                    except Exception as e:
                        logger.error("讀取 Hawser API 時發生錯誤: %s", e, exc_info=True)

                    # 等待下一個周期
                    try:
                        await asyncio.wait_for(
                            self._stop_event.wait(),
                            timeout=interval
                        )
                    except asyncio.TimeoutError:
                        # 正常的等待超時，繼續下一次循環
                        pass
                    
        except asyncio.CancelledError:
            logger.info("監控任務被取消。")
        finally:
            logger.info("監控循環結束。")

    def stop(self):
        """外部調用停止監控"""
        self._stop_event.set()
        logger.info("已接收停止訊號，準備關閉 Docker 監控...")
