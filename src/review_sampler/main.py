import os
from pathlib import Path

import uvicorn

from review_sampler.app import create_app
from review_sampler.collectors.browser import BrowserCollector
from review_sampler.collectors.demo import DemoCollector
from review_sampler.collectors.jd import JdCollector
from review_sampler.net import PacedClient
from review_sampler.service import TaskService
from review_sampler.store import Store


def build_default_app():
    database = Path(
        os.environ.get(
            "REVIEW_SAMPLER_DB",
            "runtime/review-sampler.sqlite3",
        )
    )
    store = Store(database)
    service = TaskService(
        store,
        {
            "demo": DemoCollector(),
            "jd": JdCollector(PacedClient(min_interval=0.8)),
            "browser": BrowserCollector(),
        },
    )
    return create_app(store, service)


def run() -> None:
    uvicorn.run(
        build_default_app(),
        host="127.0.0.1",
        port=8765,
        log_level="info",
    )
