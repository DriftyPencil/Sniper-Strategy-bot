from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import requests

from sniper_bot.config import IGConfig
from sniper_bot.market import Candle


class IGClient:
    def __init__(self, config: IGConfig, timeout: int = 20) -> None:
        self.config = config
        self.timeout = timeout
        self.session = requests.Session()
        self.authenticated = False

    def login(self) -> None:
        if not self.config.api_key or not self.config.username or not self.config.password:
            raise ValueError("IG_API_KEY, IG_USERNAME and IG_PASSWORD are required")

        headers = self._headers(version="2")
        response = self.session.post(
            f"{self.config.base_url}/session",
            json={"identifier": self.config.username, "password": self.config.password},
            headers=headers,
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        self.session.headers.update(
            {
                "X-IG-API-KEY": self.config.api_key,
                "CST": response.headers["CST"],
                "X-SECURITY-TOKEN": response.headers["X-SECURITY-TOKEN"],
            }
        )
        if self.config.account_id:
            self.switch_account(self.config.account_id)
        self.authenticated = True

    def switch_account(self, account_id: str) -> None:
        response = self.session.put(
            f"{self.config.base_url}/session",
            json={"accountId": account_id, "defaultAccount": False},
            headers=self._headers(version="1"),
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        if "X-SECURITY-TOKEN" in response.headers:
            self.session.headers.update({"X-SECURITY-TOKEN": response.headers["X-SECURITY-TOKEN"]})

    def historical_prices(self, epic: str, resolution: str, points: int) -> list[Candle]:
        self._ensure_login()
        response = self.session.get(
            f"{self.config.base_url}/prices/{epic}/{resolution}/{points}",
            headers=self._headers(version="3"),
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        prices = response.json().get("prices", [])
        candles = [self._parse_price(item) for item in prices if self._has_ohlc(item)]
        return candles

    def open_positions(self) -> list[dict[str, Any]]:
        self._ensure_login()
        response = self.session.get(
            f"{self.config.base_url}/positions",
            headers=self._headers(version="2"),
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        return response.json().get("positions", [])

    def create_market_position(
        self,
        *,
        epic: str,
        direction: str,
        size: float,
        stop_distance: float,
        limit_distance: float,
        currency_code: str = "GBP",
    ) -> dict[str, Any]:
        self._ensure_login()
        payload = {
            "currencyCode": currency_code,
            "dealReference": f"SNIPER-{uuid.uuid4().hex[:20]}",
            "direction": direction,
            "epic": epic,
            "expiry": "-",
            "forceOpen": True,
            "guaranteedStop": False,
            "level": None,
            "limitDistance": round(limit_distance, 5),
            "orderType": "MARKET",
            "size": size,
            "stopDistance": round(stop_distance, 5),
            "timeInForce": "FILL_OR_KILL",
            "trailingStop": False,
        }
        response = self.session.post(
            f"{self.config.base_url}/positions/otc",
            json=payload,
            headers=self._headers(version="2"),
            timeout=self.timeout,
        )
        self._raise_for_status(response)
        return response.json()

    def _ensure_login(self) -> None:
        if not self.authenticated:
            self.login()

    def _headers(self, version: str) -> dict[str, str]:
        return {
            "Accept": "application/json; charset=UTF-8",
            "Content-Type": "application/json; charset=UTF-8",
            "X-IG-API-KEY": self.config.api_key,
            "VERSION": version,
        }

    def _raise_for_status(self, response: requests.Response) -> None:
        if response.ok:
            return
        detail = response.text[:500]
        raise RuntimeError(f"IG API error {response.status_code}: {detail}")

    def _has_ohlc(self, item: dict[str, Any]) -> bool:
        for key in ("openPrice", "highPrice", "lowPrice", "closePrice"):
            price = item.get(key) or {}
            if price.get("bid") is None or price.get("ask") is None:
                return False
        return True

    def _parse_price(self, item: dict[str, Any]) -> Candle:
        timestamp = item.get("snapshotTimeUTC") or item.get("snapshotTime")
        parsed_timestamp = self._parse_timestamp(timestamp)
        return Candle(
            timestamp=parsed_timestamp,
            open_bid=float(item["openPrice"]["bid"]),
            open_ask=float(item["openPrice"]["ask"]),
            high_bid=float(item["highPrice"]["bid"]),
            high_ask=float(item["highPrice"]["ask"]),
            low_bid=float(item["lowPrice"]["bid"]),
            low_ask=float(item["lowPrice"]["ask"]),
            close_bid=float(item["closePrice"]["bid"]),
            close_ask=float(item["closePrice"]["ask"]),
            volume=float(item.get("lastTradedVolume") or 1),
        )

    def _parse_timestamp(self, value: str) -> datetime:
        normalized = value.replace("Z", "+00:00")
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(normalized, fmt)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except ValueError:
                continue
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
