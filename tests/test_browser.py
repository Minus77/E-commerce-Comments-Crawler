import builtins
import json
from pathlib import Path

import pytest

from review_sampler.collectors.base import BrowserUnavailable
from review_sampler.collectors.browser import BrowserCollector


FIXTURES = Path(__file__).parent / "fixtures"


class Runtime:
    def __init__(self, limit=10):
        self.limit = limit
        self.saved_count = 0
        self.cursors = []

    def emit(self, reviews, cursor):
        selected = reviews[: self.limit - self.saved_count]
        self.saved_count += len(selected)
        self.cursors.append(cursor)
        return len(selected)


def test_browser_payload_drain_honors_limit_and_reports_cursor():
    payload = json.loads((FIXTURES / "platform_payloads.json").read_text())[
        "amazon"
    ]
    runtime = Runtime(limit=1)

    BrowserCollector._drain(
        [payload, payload],
        {"platform": "amazon", "product_id": "B0D1234567", "limit": 1},
        runtime,
        "https://www.amazon.com/dp/B0D1234567",
    )

    assert runtime.saved_count == 1
    assert runtime.cursors == ["https://www.amazon.com/dp/B0D1234567"]


def test_missing_playwright_has_actionable_browser_error(monkeypatch):
    real_import = builtins.__import__

    def import_without_playwright(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_playwright)

    with pytest.raises(BrowserUnavailable, match="Chrome"):
        BrowserCollector().collect(
            {
                "platform": "pdd",
                "product_id": "987654",
                "input_url": "https://mobile.yangkeduo.com/goods.html?goods_id=987654",
                "limit": 1,
            },
            Runtime(),
        )
