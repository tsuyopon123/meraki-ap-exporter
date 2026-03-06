from __future__ import annotations

import logging
import threading
import time
from typing import Any

from prometheus_client import Gauge, start_http_server
from requests import HTTPError

from meraki_client import MerakiClient
from settings import Settings


LOGGER = logging.getLogger(__name__)


class MerakiAPExporter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = MerakiClient(
            api_key=settings.meraki_api_key,
            timeout_seconds=settings.request_timeout_seconds,
        )
        self.stop_event = threading.Event()

        common_labels = ["network_id", "network_name", "ap_serial", "ap_name"]

        self.ap_status = Gauge(
            "meraki_ap_up",
            "AP online status (1=online, 0=otherwise)",
            common_labels,
        )
        self.ap_clients_total = Gauge(
            "meraki_ap_clients_total",
            "Connected clients per AP",
            common_labels,
        )
        self.ap_clients_by_band = Gauge(
            "meraki_ap_clients_by_band",
            "Connected clients per AP and frequency band",
            common_labels + ["band"],
        )
        self.ap_clients_by_ssid = Gauge(
            "meraki_ap_clients_by_ssid",
            "Connected clients per AP and SSID",
            common_labels + ["ssid"],
        )
        self.ap_channel_utilization_ratio = Gauge(
            "meraki_ap_channel_utilization_ratio",
            "Channel utilization ratio (0-1)",
            common_labels + ["utilization_type"],
        )
        self.ap_connection_failures = Gauge(
            "meraki_ap_connection_failures_total",
            "Connection failures per AP by step",
            common_labels + ["failure_step"],
        )
        self.ap_latency_ms = Gauge(
            "meraki_ap_latency_ms",
            "Average wireless latency in milliseconds",
            common_labels,
        )
        self.ap_loss_percent = Gauge(
            "meraki_ap_packet_loss_percent",
            "Average wireless packet loss percent",
            common_labels,
        )

    def start(self) -> None:
        start_http_server(self.settings.exporter_port)
        LOGGER.info("Exporter started on port %s", self.settings.exporter_port)
        while not self.stop_event.is_set():
            started_at = time.time()
            try:
                self.collect_once()
            except Exception:
                LOGGER.exception("Collection failed")

            elapsed = time.time() - started_at
            sleep_for = max(1, self.settings.scrape_interval_seconds - int(elapsed))
            self.stop_event.wait(timeout=sleep_for)

    def stop(self) -> None:
        self.stop_event.set()

    def collect_once(self) -> None:
        org_id = self.settings.meraki_org_id
        networks = self.client.get_wireless_networks(org_id)
        statuses = self.client.get_org_device_statuses(org_id)

        org_metrics_timespan = max(
            self.settings.advanced_metrics_timespan_seconds,
            self.settings.org_metrics_interval_seconds,
        )
        channel_utilization_map = self._load_channel_utilization_map(
            org_id, org_metrics_timespan, self.settings.org_metrics_interval_seconds
        )
        packet_loss_map = self._load_packet_loss_map(
            org_id, org_metrics_timespan, self.settings.org_metrics_interval_seconds
        )

        for network in networks:
            network_id = str(network.get("id", ""))
            network_name = str(network.get("name", ""))
            if not network_id:
                continue

            enabled_ssids = self._safe_get_enabled_ssids(network_id)

            aps = self.client.get_wireless_devices(network_id)
            for ap in aps:
                serial = str(ap.get("serial", ""))
                ap_name = str(ap.get("name") or ap.get("model") or serial)
                ap_model = str(ap.get("model", ""))
                if not serial:
                    continue

                labels = {
                    "network_id": network_id,
                    "network_name": network_name,
                    "ap_serial": serial,
                    "ap_name": ap_name,
                }

                self._collect_status(labels, statuses.get(serial, ""))
                self._collect_clients(labels, enabled_ssids, ap_model)

                if self.settings.enable_channel_utilization_metrics:
                    self._safe_collect_with_map(
                        self._collect_channel_utilization,
                        labels,
                        channel_utilization_map,
                    )

                if self.settings.enable_connection_failure_metrics:
                    self._safe_collect(self._collect_connection_failures, labels)

                if self.settings.enable_latency_metrics:
                    self._safe_collect(self._collect_latency_and_loss, labels)

                if self.settings.enable_packet_loss_metrics:
                    self._safe_collect_with_map(
                        self._collect_packet_loss,
                        labels,
                        packet_loss_map,
                    )

    def _safe_collect(self, func: Any, labels: dict[str, str]) -> None:
        try:
            func(labels)
        except HTTPError as exc:
            LOGGER.debug("Optional metric endpoint unavailable: %s", exc)
        except Exception:
            LOGGER.exception("Metric collection failed for AP %s", labels.get("ap_serial"))

    def _safe_collect_with_map(self, func: Any, labels: dict[str, str], data: Any) -> None:
        try:
            func(labels, data)
        except HTTPError as exc:
            LOGGER.debug("Optional metric endpoint unavailable: %s", exc)
        except Exception:
            LOGGER.exception("Metric collection failed for AP %s", labels.get("ap_serial"))

    def _safe_get_enabled_ssids(self, network_id: str) -> list[int]:
        try:
            return self.client.get_network_enabled_ssids(network_id)
        except HTTPError as exc:
            LOGGER.warning(
                "Failed to get enabled SSIDs for network %s: %s", network_id, exc
            )
            return []

    def _load_channel_utilization_map(
        self, org_id: str, timespan: int, interval: int
    ) -> dict[str, dict[str, float]]:
        if not self.settings.enable_channel_utilization_metrics:
            return {}

        try:
            rows = self.client.get_org_channel_utilization_by_device(
                org_id, timespan, interval
            )
        except Exception:
            LOGGER.exception("Failed to load channel utilization by device")
            return {}

        mapped: dict[str, dict[str, float]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            serial = row.get("serial")
            if not isinstance(serial, str):
                continue

            by_band = row.get("byBand")
            if not isinstance(by_band, list) or not by_band:
                continue

            wifi_values: list[float] = []
            non_wifi_values: list[float] = []
            total_values: list[float] = []
            for band_row in by_band:
                if not isinstance(band_row, dict):
                    continue
                wifi_values.append(
                    float(
                        ((band_row.get("wifi") or {}).get("percentage"))
                        or 0.0
                    )
                )
                non_wifi_values.append(
                    float(
                        ((band_row.get("nonWifi") or {}).get("percentage"))
                        or 0.0
                    )
                )
                total_values.append(
                    float(
                        ((band_row.get("total") or {}).get("percentage"))
                        or 0.0
                    )
                )

            def avg(values: list[float]) -> float:
                return (sum(values) / len(values)) if values else 0.0

            mapped[serial] = {
                "wifi": avg(wifi_values) / 100.0,
                "non_wifi": avg(non_wifi_values) / 100.0,
                "total": avg(total_values) / 100.0,
            }
        return mapped

    def _load_packet_loss_map(
        self, org_id: str, timespan: int, interval: int
    ) -> dict[str, float]:
        if not self.settings.enable_packet_loss_metrics:
            return {}

        try:
            rows = self.client.get_org_packet_loss_by_device(org_id, timespan, interval)
        except Exception:
            LOGGER.exception("Failed to load packet loss by device")
            return {}

        mapped: dict[str, float] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            device = row.get("device")
            if not isinstance(device, dict):
                continue
            serial = device.get("serial")
            if not isinstance(serial, str):
                continue

            upstream_loss = ((row.get("upstream") or {}).get("lossPercentage"))
            downstream_loss = ((row.get("downstream") or {}).get("lossPercentage"))
            values = [
                float(v)
                for v in [upstream_loss, downstream_loss]
                if isinstance(v, (int, float))
            ]
            mapped[serial] = (sum(values) / len(values)) if values else 0.0

        return mapped

    def _collect_status(self, labels: dict[str, str], status: str) -> None:
        self.ap_status.labels(**labels).set(1 if status.lower() == "online" else 0)

    def _collect_clients(
        self, labels: dict[str, str], enabled_ssids: list[int], ap_model: str
    ) -> None:
        path = f"/devices/{labels['ap_serial']}/wireless/clientCountHistory"
        base_params = {
            "timespan": self.settings.scrape_interval_seconds,
            "resolution": self.settings.scrape_interval_seconds,
        }

        self.ap_clients_total.labels(**labels).set(0)
        for band in ["2.4", "5", "6"]:
            self.ap_clients_by_band.labels(**labels, band=band).set(0)
        for ssid in enabled_ssids:
            self.ap_clients_by_ssid.labels(**labels, ssid=str(ssid)).set(0)

        if ap_model.startswith("CW"):
            self._collect_clients_from_fallback(labels)
            return

        try:
            total = self._latest_value(self.client.get(path, params=base_params))
            self.ap_clients_total.labels(**labels).set(total)

            for band in ["2.4", "5", "6"]:
                payload = self.client.get(path, params={**base_params, "band": band})
                band_value = self._latest_value(payload)
                self.ap_clients_by_band.labels(**labels, band=band).set(band_value)

            for ssid in enabled_ssids:
                payload = self.client.get(path, params={**base_params, "ssid": ssid})
                ssid_value = self._latest_value(payload)
                self.ap_clients_by_ssid.labels(**labels, ssid=str(ssid)).set(ssid_value)
            return
        except HTTPError as exc:
            response = exc.response
            if response is None or response.status_code != 404:
                raise

        self._collect_clients_from_fallback(labels)

    def _collect_clients_from_fallback(self, labels: dict[str, str]) -> None:
        fallback_clients = self._fetch_device_clients(labels["ap_serial"])
        self.ap_clients_total.labels(**labels).set(float(len(fallback_clients)))

        band_counts = {"2.4": 0.0, "5": 0.0, "6": 0.0}
        ssid_counts: dict[str, float] = {}

        for client in fallback_clients:
            if not isinstance(client, dict):
                continue

            band = self._extract_band(client)
            if band in band_counts:
                band_counts[band] += 1.0

            ssid_label = self._extract_ssid_label(client)
            if ssid_label:
                ssid_counts[ssid_label] = ssid_counts.get(ssid_label, 0.0) + 1.0

        for band, count in band_counts.items():
            self.ap_clients_by_band.labels(**labels, band=band).set(count)
        for ssid, count in ssid_counts.items():
            self.ap_clients_by_ssid.labels(**labels, ssid=ssid).set(count)

    def _fetch_device_clients(self, serial: str) -> list[dict[str, Any]]:
        lookback_seconds = max(self.settings.scrape_interval_seconds, 300)
        payload = self.client.get(
            f"/devices/{serial}/clients",
            params={
                "timespan": lookback_seconds,
                "perPage": 1000,
            },
        )
        if not isinstance(payload, list):
            return []
        return [row for row in payload if isinstance(row, dict)]

    @staticmethod
    def _extract_band(client: dict[str, Any]) -> str | None:
        candidate_values: list[str] = []

        connection = client.get("recentDeviceConnection")
        if isinstance(connection, dict):
            band = connection.get("band")
            if isinstance(band, str):
                candidate_values.append(band)

        for key in ["band", "radio", "channel"]:
            value = client.get(key)
            if isinstance(value, str):
                candidate_values.append(value)

        raw = " ".join(candidate_values).lower()
        if "6" in raw:
            return "6"
        if "5" in raw:
            return "5"
        if "2.4" in raw or "2g" in raw or "2_4" in raw:
            return "2.4"
        return None

    @staticmethod
    def _extract_ssid_label(client: dict[str, Any]) -> str | None:
        ssid_name = client.get("ssid")
        if isinstance(ssid_name, str) and ssid_name:
            return ssid_name

        ssid_number = client.get("ssidNumber")
        if isinstance(ssid_number, int):
            return str(ssid_number)

        return None

    def _collect_channel_utilization(
        self, labels: dict[str, str], channel_utilization_map: dict[str, dict[str, float]]
    ) -> None:
        values = channel_utilization_map.get(
            labels["ap_serial"],
            {"total": 0.0, "wifi": 0.0, "non_wifi": 0.0},
        )
        for key, value in values.items():
            self.ap_channel_utilization_ratio.labels(
                **labels, utilization_type=key
            ).set(max(0.0, value))

    def _collect_connection_failures(self, labels: dict[str, str]) -> None:
        path = f"/devices/{labels['ap_serial']}/wireless/connectionStats"
        payload = self.client.get(
            path,
            params={"timespan": self.settings.advanced_metrics_timespan_seconds},
        )

        if not isinstance(payload, dict):
            return

        failures = payload.get("connectionStats", {})
        if not isinstance(failures, dict):
            return

        for step in ["assoc", "auth", "dhcp", "dns"]:
            value = float(failures.get(step, 0.0))
            self.ap_connection_failures.labels(**labels, failure_step=step).set(value)

    def _collect_latency_and_loss(self, labels: dict[str, str]) -> None:
        path = f"/devices/{labels['ap_serial']}/wireless/latencyStats"
        payload = self.client.get(
            path,
            params={"timespan": self.settings.advanced_metrics_timespan_seconds},
        )

        if not isinstance(payload, dict):
            return

        latency_stats = payload.get("latencyStats", {})
        latency_ms = self._avg_latency_from_latency_stats(latency_stats)

        self.ap_latency_ms.labels(**labels).set(latency_ms)

    def _collect_packet_loss(
        self, labels: dict[str, str], packet_loss_map: dict[str, float]
    ) -> None:
        value = packet_loss_map.get(labels["ap_serial"], 0.0)
        self.ap_loss_percent.labels(**labels).set(value)

    @staticmethod
    def _avg_latency_from_latency_stats(latency_stats: Any) -> float:
        if not isinstance(latency_stats, dict):
            return 0.0

        values: list[float] = []
        for _, section in latency_stats.items():
            if not isinstance(section, dict):
                continue
            avg = section.get("avg")
            if isinstance(avg, (int, float)):
                values.append(float(avg))
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _latest_entry(payload: Any) -> dict[str, Any] | None:
        if isinstance(payload, list) and payload:
            candidate = payload[-1]
            return candidate if isinstance(candidate, dict) else None
        return None

    @staticmethod
    def _latest_value(payload: Any) -> float:
        latest = MerakiAPExporter._latest_entry(payload)
        if not latest:
            return 0.0

        for key in ["count", "clientCount", "value", "clients"]:
            value = latest.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return 0.0
