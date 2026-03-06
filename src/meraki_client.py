from __future__ import annotations

import logging
import time
from typing import Any

import requests


LOGGER = logging.getLogger(__name__)


class MerakiClient:
    BASE_URL = "https://api.meraki.com/api/v1"

    def __init__(self, api_key: str, timeout_seconds: int = 20) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-Cisco-Meraki-API-Key": api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "meraki-ap-exporter/0.1.1",
            }
        )

    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> requests.Response:
        url = f"{self.BASE_URL}{path}"
        max_attempts = 5
        backoff_seconds = 1.0

        for attempt in range(1, max_attempts + 1):
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                timeout=self.timeout_seconds,
            )

            if response.status_code != 429:
                if response.status_code >= 400:
                    LOGGER.warning(
                        "Meraki API error status=%s path=%s body=%s",
                        response.status_code,
                        path,
                        response.text[:500],
                    )
                response.raise_for_status()
                return response

            retry_after = response.headers.get("Retry-After")
            if retry_after is not None:
                sleep_seconds = float(retry_after)
            else:
                sleep_seconds = backoff_seconds
                backoff_seconds = min(backoff_seconds * 2, 16)

            LOGGER.warning(
                "Meraki rate limited (429) path=%s attempt=%s/%s sleep=%.1fs",
                path,
                attempt,
                max_attempts,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)

        raise RuntimeError(f"Meraki API rate limit exceeded for path: {path}")

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._request("GET", path, params=params)
        return response.json()

    def get_paginated(
        self, path: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        merged_params: dict[str, Any] = {"perPage": 1000}
        if params:
            merged_params.update(params)

        response = self._request("GET", path, params=merged_params)
        payload = response.json()
        if not isinstance(payload, list):
            return []

        results: list[dict[str, Any]] = list(payload)
        while True:
            link_header = response.headers.get("Link", "")
            next_url = self._extract_next_link(link_header)
            if not next_url:
                break

            response = self.session.get(next_url, timeout=self.timeout_seconds)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                response = self.session.get(next_url, timeout=self.timeout_seconds)

            response.raise_for_status()
            page = response.json()
            if isinstance(page, list):
                results.extend(page)
            else:
                break
        return results

    @staticmethod
    def _extract_next_link(link_header: str) -> str | None:
        if not link_header:
            return None
        parts = [part.strip() for part in link_header.split(",")]
        for part in parts:
            if 'rel="next"' in part and "<" in part and ">" in part:
                return part[part.find("<") + 1 : part.find(">")]
        return None

    def get_wireless_networks(self, org_id: str) -> list[dict[str, Any]]:
        return self.get_paginated(
            f"/organizations/{org_id}/networks",
            params={"productTypes[]": "wireless"},
        )

    def get_wireless_devices(self, network_id: str) -> list[dict[str, Any]]:
        devices = self.get_paginated(f"/networks/{network_id}/devices")
        aps: list[dict[str, Any]] = []
        for device in devices:
            model = str(device.get("model", ""))
            if model.startswith("MR") or model.startswith("CW"):
                aps.append(device)
        return aps

    def get_network_clients(self, network_id: str, timespan: int) -> list[dict[str, Any]]:
        payload = self.get_paginated(
            f"/networks/{network_id}/clients",
            params={
                "timespan": timespan,
            },
        )
        return [row for row in payload if isinstance(row, dict)]

    def get_org_device_statuses(self, org_id: str) -> dict[str, str]:
        statuses = self.get_paginated(f"/organizations/{org_id}/devices/statuses")
        result: dict[str, str] = {}
        for row in statuses:
            serial = row.get("serial")
            status = row.get("status")
            if isinstance(serial, str) and isinstance(status, str):
                result[serial] = status
        return result

    def get_network_enabled_ssids(self, network_id: str) -> list[int]:
        ssid_map = self.get_network_enabled_ssid_map(network_id)
        return sorted(ssid_map.keys())

    def get_network_enabled_ssid_map(self, network_id: str) -> dict[int, str]:
        payload = self.get(f"/networks/{network_id}/wireless/ssids")
        if not isinstance(payload, list):
            return {}

        result: dict[int, str] = {}
        for row in payload:
            if not isinstance(row, dict):
                continue
            if row.get("enabled") is False:
                continue
            number = row.get("number")
            name = row.get("name")
            if isinstance(number, int) and isinstance(name, str) and name.strip():
                result[number] = name.strip()
        return result

    def get_org_channel_utilization_by_device(
        self, org_id: str, timespan: int, interval: int
    ) -> list[dict[str, Any]]:
        return self.get_paginated(
            f"/organizations/{org_id}/wireless/devices/channelUtilization/byDevice",
            params={
                "timespan": timespan,
                "interval": interval,
            },
        )

    def get_org_packet_loss_by_device(
        self, org_id: str, timespan: int, interval: int
    ) -> list[dict[str, Any]]:
        return self.get_paginated(
            f"/organizations/{org_id}/wireless/devices/packetLoss/byDevice",
            params={
                "timespan": timespan,
                "interval": interval,
            },
        )
