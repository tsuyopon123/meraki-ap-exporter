# meraki-ap-exporter

Cisco Meraki APIを利用して、AP監視に特化したPrometheus Exporterです。

## 前提

- Docker / Docker Compose
- Meraki Dashboard APIキー
- Meraki Organization ID

## Docker Composeで実行

```bash
cp .env.example .env
# .envにMERAKI_API_KEY/MERAKI_ORG_IDを設定
docker compose up -d --build
```

状態確認:

```bash
docker compose ps
docker compose logs -f meraki-exporter
curl -s http://localhost:9780/metrics | head
```

停止:

```bash
docker compose down
```

Prometheusは `http://<host>:9780/metrics` をスクレイプしてください。

## 収集メトリクス

### メトリクス一覧

- APオンライン状態
  - `meraki_ap_up`
- APごとのクライアント数
  - `meraki_ap_clients_total`
- APごとの周波数別クライアント数
  - `meraki_ap_clients_by_band{band="2.4|5|6"}`
- APごとのSSID別クライアント数
  - `meraki_ap_clients_by_ssid{ssid="<number>"}`
- APチャネル利用率
  - `meraki_ap_channel_utilization_ratio{utilization_type="total|wifi|non_wifi"}`
- AP接続失敗数
  - `meraki_ap_connection_failures_total{failure_step="assoc|auth|dhcp|dns"}`
- AP遅延/パケットロス
  - `meraki_ap_latency_ms`
  - `meraki_ap_packet_loss_percent`

### 各メトリクスの説明

- `meraki_ap_up`
  - 意味: APのオンライン状態（`online=1`, それ以外=0）
  - 単位: なし
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`
- `meraki_ap_clients_total`
  - 意味: APに接続中のクライアント総数
  - 単位: 台
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`
- `meraki_ap_clients_by_band`
  - 意味: APの周波数帯ごとのクライアント数
  - 単位: 台
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`, `band`
- `meraki_ap_clients_by_ssid`
  - 意味: APのSSIDごとのクライアント数
  - 単位: 台
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`, `ssid`
- `meraki_ap_channel_utilization_ratio`
  - 意味: チャネル利用率（`total`/`wifi`/`non_wifi`）
  - 単位: 比率（0〜1）
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`, `utilization_type`
- `meraki_ap_connection_failures_total`
  - 意味: 接続失敗数（`assoc`/`auth`/`dhcp`/`dns`）
  - 単位: 件
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`, `failure_step`
- `meraki_ap_latency_ms`
  - 意味: APの平均遅延
  - 単位: ms
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`
- `meraki_ap_packet_loss_percent`
  - 意味: APのパケットロス率（上り/下りの平均）
  - 単位: %
  - 主なラベル: `network_id`, `network_name`, `ap_serial`, `ap_name`

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

`.env` を編集します:

```dotenv
MERAKI_API_KEY=your_meraki_api_key
MERAKI_ORG_ID=123456

EXPORTER_PORT=9780
SCRAPE_INTERVAL_SECONDS=60
REQUEST_TIMEOUT_SECONDS=20
ENABLE_BETA_METRICS=false

ENABLE_CHANNEL_UTILIZATION_METRICS=false
ENABLE_CONNECTION_FAILURE_METRICS=false
ENABLE_LATENCY_METRICS=false
ENABLE_PACKET_LOSS_METRICS=false

ADVANCED_METRICS_TIMESPAN_SECONDS=21600
ORG_METRICS_INTERVAL_SECONDS=3600
CLIENTS_LOOKBACK_SECONDS=900
```

## 実行

```bash
python src/main.py
```

## 注意事項

- Meraki APIレート制限（429）に対し、`Retry-After` を使った再試行を実装しています。
- SSID別収集は有効SSIDのみを対象にして、API呼び出し数を抑えています。
- `ENABLE_BETA_METRICS` は将来の拡張用フラグです（現時点は互換維持用）。
- API負荷を調整したい場合は、`ENABLE_*_METRICS` でメトリクス群を個別に無効化できます。
- `ADVANCED_METRICS_TIMESPAN_SECONDS` は接続失敗/遅延などの取得窓です。短すぎると空データになりやすいため、6時間（21600秒）以上を推奨します。
- `ORG_METRICS_INTERVAL_SECONDS` は組織スコープ集計API（チャネル利用率/パケットロス）に使われます。
- `CLIENTS_LOOKBACK_SECONDS` はクライアント数集計の参照窓です。環境により300秒だと0件になる場合があるため、900秒以上を推奨します。
