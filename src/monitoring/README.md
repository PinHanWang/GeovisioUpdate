# src/monitoring/

背景監控 GeoVisio Docker 容器，非上傳主流程的一部分。

## 檔案

### `docker_monitor.py` — `HawserDockerMonitor`

透過 Hawser 代理（標準 Docker Remote API，`/containers/{id}/stats?stream=false`）監控 GeoVisio 容器的記憶體/CPU 使用率，超過閾值時發 Discord 告警。

- `target_ip` — 自動採用 `Settings.TMS_GEOVISIO_URL` 的主機位址（假設 GeoVisio API 與 Docker 監控主機同一台）
- `hawser_port` — 固定 2376（模組常數 `_HAWSER_PORT`，Hawser 標準監聽埠，不是設定項）
- `container_name` — `Settings.DOCKER_CONTAINER_NAME`
- `start(interval)` — 啟動背景輪詢迴圈（`asyncio.wait_for(stop_event.wait(), timeout=interval)`，不是單純 `sleep`，收到停止訊號可立即中斷）
- `send_to_discord(message)` — 需要 `Settings.DISCORD_BOT_TOKEN` + `Settings.DISCORD_CHANNEL_ID` 都設定才會實際發送

## 呼叫端

`src/main.py` 建立 `HawserDockerMonitor()` 並以獨立背景 task（`asyncio.create_task`）啟動，與 `GeoVisioUploadPipeline.run()` 並行執行，跟上傳主流程完全解耦。
