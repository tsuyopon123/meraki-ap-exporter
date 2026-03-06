from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    meraki_api_key: str
    meraki_org_id: str
    exporter_port: int = 9780
    scrape_interval_seconds: int = 60
    request_timeout_seconds: int = 20
    enable_beta_metrics: bool = False
    enable_channel_utilization_metrics: bool = False
    enable_connection_failure_metrics: bool = False
    enable_latency_metrics: bool = False
    enable_packet_loss_metrics: bool = False
    advanced_metrics_timespan_seconds: int = 21600
    org_metrics_interval_seconds: int = 3600
    clients_lookback_seconds: int = 900


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv()

    meraki_api_key = os.getenv("MERAKI_API_KEY", "").strip()
    meraki_org_id = os.getenv("MERAKI_ORG_ID", "").strip()

    if not meraki_api_key:
        raise ValueError("MERAKI_API_KEY is required")
    if not meraki_org_id:
        raise ValueError("MERAKI_ORG_ID is required")

    exporter_port = int(os.getenv("EXPORTER_PORT", "9780"))
    scrape_interval_seconds = int(os.getenv("SCRAPE_INTERVAL_SECONDS", "60"))
    request_timeout_seconds = int(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
    enable_beta_metrics = _to_bool(os.getenv("ENABLE_BETA_METRICS"), False)
    enable_channel_utilization_metrics = _to_bool(
        os.getenv("ENABLE_CHANNEL_UTILIZATION_METRICS"), False
    )
    enable_connection_failure_metrics = _to_bool(
        os.getenv("ENABLE_CONNECTION_FAILURE_METRICS"), False
    )
    enable_latency_metrics = _to_bool(os.getenv("ENABLE_LATENCY_METRICS"), False)
    enable_packet_loss_metrics = _to_bool(
        os.getenv("ENABLE_PACKET_LOSS_METRICS"), False
    )
    advanced_metrics_timespan_seconds = int(
        os.getenv("ADVANCED_METRICS_TIMESPAN_SECONDS", "21600")
    )
    org_metrics_interval_seconds = int(os.getenv("ORG_METRICS_INTERVAL_SECONDS", "3600"))
    clients_lookback_seconds = int(os.getenv("CLIENTS_LOOKBACK_SECONDS", "900"))

    if scrape_interval_seconds < 15:
        raise ValueError("SCRAPE_INTERVAL_SECONDS must be >= 15")
    if request_timeout_seconds <= 0:
        raise ValueError("REQUEST_TIMEOUT_SECONDS must be > 0")
    if advanced_metrics_timespan_seconds <= 0:
        raise ValueError("ADVANCED_METRICS_TIMESPAN_SECONDS must be > 0")
    if org_metrics_interval_seconds <= 0:
        raise ValueError("ORG_METRICS_INTERVAL_SECONDS must be > 0")
    if clients_lookback_seconds <= 0:
        raise ValueError("CLIENTS_LOOKBACK_SECONDS must be > 0")

    return Settings(
        meraki_api_key=meraki_api_key,
        meraki_org_id=meraki_org_id,
        exporter_port=exporter_port,
        scrape_interval_seconds=scrape_interval_seconds,
        request_timeout_seconds=request_timeout_seconds,
        enable_beta_metrics=enable_beta_metrics,
        enable_channel_utilization_metrics=enable_channel_utilization_metrics,
        enable_connection_failure_metrics=enable_connection_failure_metrics,
        enable_latency_metrics=enable_latency_metrics,
        enable_packet_loss_metrics=enable_packet_loss_metrics,
        advanced_metrics_timespan_seconds=advanced_metrics_timespan_seconds,
        org_metrics_interval_seconds=org_metrics_interval_seconds,
        clients_lookback_seconds=clients_lookback_seconds,
    )
