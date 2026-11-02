import time

import pytest
from fastapi.testclient import TestClient

from review_sampler.app import create_app
from review_sampler.collectors.demo import DemoCollector
from review_sampler.service import TaskService
from review_sampler.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data.sqlite3")


@pytest.fixture
def service(store):
    return TaskService(store, {"demo": DemoCollector()})


@pytest.fixture
def app(store, service):
    return create_app(store, service)


@pytest.fixture
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def wait_for_task(client):
    def wait(task_id, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            response = client.get(f"/api/tasks/{task_id}")
            assert response.status_code == 200
            task = response.json()["task"]
            if task["status"] in {
                "completed",
                "failed",
                "cancelled",
                "needs_user",
                "interrupted",
            }:
                return task
            time.sleep(0.01)
        raise AssertionError(f"task {task_id} did not settle")

    return wait
