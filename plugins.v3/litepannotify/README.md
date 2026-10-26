# LitePan 联动

MoviePilot 媒体整理完成后，通过 Webhook 触发 LitePan 自动联动任务（STRM 生成、刮削、Emby 刷库等）。

## 配置说明

| 配置项 | 说明 |
|---|---|
| LitePan 地址 | 例如 `http://192.168.1.100:5211`，不要带 `/api` 路径 |
| API 密钥 | LitePan「系统设置 → API 秘钥」中创建的**任务执行型**密钥（`lpk_api_` 开头） |
| 通知名称 | 必须与 LitePan 自动联动任务中的「通知名称」完全一致 |
| 来源名称 | 可选。LitePan 端设置了「通知来源」时需保持一致 |
| 超时 | HTTP 请求超时秒数，默认 10 |

## 触发机制

监听 MoviePilot 的 `TransferComplete`（`transfer.complete`）事件，在文件整理完成后向 LitePan 发送 Webhook。
