from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import threading
import time

import httpx
import pytest

from review_sampler.net import (
    AccessDenied,
    NetworkError,
    PacedClient,
    RateLimited,
)


def test_retry_after_wins_over_backoff():
    client = PacedClient(min_interval=0, max_retries=2)

    assert client.retry_delay(attempt=1, retry_after="7") == 7.0
    assert client.retry_delay(attempt=1, retry_after=None) < 3


def test_retry_after_accepts_http_date():
    client = PacedClient(min_interval=0)
    request_time = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
    retry_at = format_datetime(request_time + timedelta(seconds=11), usegmt=True)

    assert client.retry_delay(
        attempt=2,
        retry_after=retry_at,
        now=request_time.timestamp(),
    ) == 11.0


def test_non_retryable_403_raises_access_denied():
    client = PacedClient(min_interval=0, max_retries=3)

    with pytest.raises(AccessDenied):
        client.raise_for_status(403)


@pytest.mark.parametrize(
    ("status", "error"),
    [(429, RateLimited), (500, NetworkError)],
)
def test_retryable_status_exhausts_three_retries(
    monkeypatch, status, error
):
    count = 0

    def handler(_request):
        nonlocal count
        count += 1
        return httpx.Response(status)

    monkeypatch.setattr("review_sampler.net.time.sleep", lambda _delay: None)
    client = PacedClient(
        min_interval=0,
        max_retries=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(error):
        client.get_json("https://example.invalid/comments")

    assert count == 4


def test_bad_request_fails_without_retry():
    count = 0

    def handler(_request):
        nonlocal count
        count += 1
        return httpx.Response(400)

    client = PacedClient(
        min_interval=0,
        max_retries=3,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(NetworkError):
        client.get_json("https://example.invalid/comments")

    assert count == 1


def test_two_threads_share_the_same_pacing_lock():
    starts: list[float] = []
    guard = threading.Lock()

    def handler(_request):
        with guard:
            starts.append(time.monotonic())
        return httpx.Response(200, json={"ok": True})

    client = PacedClient(
        min_interval=0.8,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                client.get_json,
                [
                    "https://example.invalid/one",
                    "https://example.invalid/two",
                ],
            )
        )

    assert len(starts) == 2
    assert abs(starts[1] - starts[0]) >= 0.75
