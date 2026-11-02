from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import random
from threading import Lock
import time

import httpx


class AccessDenied(Exception):
    """The platform requires a person or an authorized session."""


class RateLimited(Exception):
    """The platform kept rejecting requests with HTTP 429."""


class NetworkError(Exception):
    """A request failed or returned a permanent HTTP error."""


class PacedClient:
    def __init__(
        self,
        *,
        min_interval: float = 0.8,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.min_interval = max(0.0, float(min_interval))
        self.max_retries = max(0, int(max_retries))
        self._client = httpx.Client(
            transport=transport,
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "ReviewSampler/0.1 (local review analysis)",
                "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                **(headers or {}),
            },
        )
        self._pace_lock = Lock()
        self._last_request_at = 0.0

    def _wait_for_turn(self) -> None:
        with self._pace_lock:
            elapsed = time.monotonic() - self._last_request_at
            delay = self.min_interval - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_request_at = time.monotonic()

    @staticmethod
    def _retry_after_seconds(value: str | None, now: float) -> float | None:
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            pass
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, retry_at.timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return None

    def retry_delay(
        self,
        *,
        attempt: int,
        retry_after: str | None,
        now: float | None = None,
    ) -> float:
        current = time.time() if now is None else now
        explicit = self._retry_after_seconds(retry_after, current)
        if explicit is not None:
            return explicit
        return min(2 ** max(0, attempt - 1), 16) + random.uniform(0, 0.25)

    def raise_for_status(self, status_code: int) -> None:
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            raise AccessDenied("平台要求登录、授权或人工验证")
        if status_code == 429:
            raise RateLimited("平台请求过于频繁")
        raise NetworkError(f"平台返回 HTTP {status_code}")

    def get_text(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        for attempt in range(self.max_retries + 1):
            self._wait_for_turn()
            try:
                response = self._client.get(url, params=params, headers=headers)
            except httpx.RequestError as exc:
                if attempt >= self.max_retries:
                    raise NetworkError("无法连接平台") from exc
                time.sleep(self.retry_delay(attempt=attempt + 1, retry_after=None))
                continue

            if response.status_code == 429:
                if attempt >= self.max_retries:
                    raise RateLimited("平台请求过于频繁")
                time.sleep(
                    self.retry_delay(
                        attempt=attempt + 1,
                        retry_after=response.headers.get("Retry-After"),
                    )
                )
                continue
            if response.status_code >= 500:
                if attempt >= self.max_retries:
                    raise NetworkError("平台暂时无法响应")
                time.sleep(
                    self.retry_delay(
                        attempt=attempt + 1,
                        retry_after=response.headers.get("Retry-After"),
                    )
                )
                continue

            self.raise_for_status(response.status_code)
            return response.text
        raise NetworkError("平台请求失败")

    def get_json(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        try:
            payload = json.loads(
                self.get_text(url, params=params, headers=headers)
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NetworkError("平台返回了无法解析的数据") from exc
        if not isinstance(payload, dict):
            raise NetworkError("平台返回的数据结构不正确")
        return payload

    def close(self) -> None:
        self._client.close()
