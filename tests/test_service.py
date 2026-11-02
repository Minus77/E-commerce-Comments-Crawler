from threading import Event
import time

from review_sampler.collectors.demo import DemoCollector
from review_sampler.service import TaskService
from review_sampler.store import Store


def wait_until(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def test_demo_task_completes_with_the_requested_number_of_reviews(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    service = TaskService(store, {"demo": DemoCollector()})
    task = store.create_task(
        platform="demo",
        product_id="DEMO-001",
        input_url=None,
        mode="demo",
        limit=6,
    )

    service.run_now(task["id"])

    done = store.get_task(task["id"])
    assert done["status"] == "completed"
    assert done["collected_count"] == 6
    assert done["error_code"] is None
    assert done["started_at"]
    assert done["finished_at"]
    assert store.count_reviews(task_id=task["id"]) == 6


def test_demo_is_deterministic_and_capped_at_24(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    service = TaskService(store, {"demo": DemoCollector()})
    task = store.create_task("demo", "DEMO-001", None, "demo", 5000)

    service.run_now(task["id"])

    reviews = store.list_reviews(task_id=task["id"])
    assert len(reviews) == 24
    assert {item["rating"] for item in reviews} == {1, 2, 3, 4, 5}
    assert any("\n" in item["content"] for item in reviews)
    assert any('"' in item["content"] for item in reviews)
    assert store.get_task(task["id"])["status"] == "completed"


def test_repeating_run_now_does_not_insert_more_reviews(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    service = TaskService(store, {"demo": DemoCollector()})
    task = store.create_task("demo", "DEMO-001", None, "demo", 4)

    service.run_now(task["id"])
    service.run_now(task["id"])

    assert store.count_reviews(task_id=task["id"]) == 4


def test_unknown_platform_fails_with_a_stable_error_code(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    service = TaskService(store, {})
    task = store.create_task("jd", "100012043978", None, "auto", 10)

    service.run_now(task["id"])

    failed = store.get_task(task["id"])
    assert failed["status"] == "failed"
    assert failed["error_code"] == "UNSUPPORTED"
    assert "采集通道" in failed["status_reason"]


def test_collector_exception_is_mapped_without_exposing_the_exception(tmp_path):
    class BrokenCollector:
        def collect(self, task, runtime):
            raise RuntimeError("secret-token-and-stack")

    store = Store(tmp_path / "data.sqlite3")
    service = TaskService(store, {"jd": BrokenCollector()})
    task = store.create_task("jd", "100012043978", None, "auto", 10)

    service.run_now(task["id"])

    failed = store.get_task(task["id"])
    assert failed["status"] == "failed"
    assert failed["error_code"] == "PARSE_ERROR"
    assert "secret" not in failed["status_reason"]


def test_cancel_stops_an_active_collector(tmp_path):
    class WaitingCollector:
        started = Event()

        def collect(self, task, runtime):
            self.started.set()
            while True:
                runtime.checkpoint()
                time.sleep(0.01)

    store = Store(tmp_path / "data.sqlite3")
    collector = WaitingCollector()
    service = TaskService(store, {"jd": collector})
    task = store.create_task("jd", "100012043978", None, "auto", 10)
    service.submit(task["id"])
    wait_until(collector.started.is_set)

    service.cancel(task["id"])
    cancelled = wait_until(
        lambda: (
            current
            if (current := store.get_task(task["id"]))["status"] == "cancelled"
            else None
        )
    )

    assert cancelled["finished_at"]
    assert cancelled["error_code"] is None


def test_pause_marks_needs_user_and_continue_resumes(tmp_path):
    class PausingCollector:
        reached_pause = Event()

        def collect(self, task, runtime):
            self.reached_pause.set()
            runtime.pause("login", "请在浏览器中完成登录，然后继续。")
            runtime.emit([], None)

    store = Store(tmp_path / "data.sqlite3")
    collector = PausingCollector()
    service = TaskService(store, {"jd": collector})
    task = store.create_task("jd", "100012043978", None, "auto", 10)
    service.submit(task["id"])
    wait_until(collector.reached_pause.is_set)
    paused = wait_until(
        lambda: (
            current
            if (current := store.get_task(task["id"]))["status"] == "needs_user"
            else None
        )
    )

    assert paused["error_code"] == "AUTH_REQUIRED"
    service.continue_task(task["id"])
    completed = wait_until(
        lambda: (
            current
            if (current := store.get_task(task["id"]))["status"] == "completed"
            else None
        )
    )

    assert completed["status_reason"]


def test_continue_is_idempotent_while_a_task_is_active(tmp_path):
    class SlowCollector:
        started = Event()
        calls = 0

        def collect(self, task, runtime):
            self.calls += 1
            self.started.set()
            time.sleep(0.08)
            runtime.checkpoint()

    store = Store(tmp_path / "data.sqlite3")
    collector = SlowCollector()
    service = TaskService(store, {"jd": collector})
    task = store.create_task("jd", "100012043978", None, "auto", 10)
    service.submit(task["id"])
    wait_until(collector.started.is_set)

    service.continue_task(task["id"])
    wait_until(lambda: store.get_task(task["id"])["status"] == "completed")

    assert collector.calls == 1


def test_jd_auto_mode_uses_the_direct_collector(tmp_path):
    class RecordingCollector:
        calls = 0

        def collect(self, task, runtime):
            self.calls += 1

    store = Store(tmp_path / "data.sqlite3")
    direct = RecordingCollector()
    browser = RecordingCollector()
    service = TaskService(store, {"jd": direct, "browser": browser})
    task = store.create_task("jd", "100012043978", None, "auto", 10)

    service.run_now(task["id"])

    assert direct.calls == 1
    assert browser.calls == 0


def test_jd_browser_mode_uses_the_browser_collector(tmp_path):
    class RecordingCollector:
        calls = 0

        def collect(self, task, runtime):
            self.calls += 1

    store = Store(tmp_path / "data.sqlite3")
    direct = RecordingCollector()
    browser = RecordingCollector()
    service = TaskService(store, {"jd": direct, "browser": browser})
    task = store.create_task("jd", "100012043978", None, "browser", 10)

    service.run_now(task["id"])

    assert direct.calls == 0
    assert browser.calls == 1


def test_other_platforms_fall_back_to_browser_collector(tmp_path):
    class RecordingCollector:
        calls = 0

        def collect(self, task, runtime):
            self.calls += 1

    store = Store(tmp_path / "data.sqlite3")
    browser = RecordingCollector()
    service = TaskService(store, {"browser": browser})
    task = store.create_task(
        "pdd",
        "987654",
        "https://mobile.yangkeduo.com/goods.html?goods_id=987654",
        "auto",
        10,
    )

    service.run_now(task["id"])

    assert browser.calls == 1


def test_platform_access_errors_map_to_actionable_task_states(tmp_path):
    from review_sampler.net import AccessDenied, NetworkError, RateLimited

    cases = [
        (AccessDenied("private message"), "needs_user", "AUTH_REQUIRED"),
        (RateLimited("private message"), "failed", "RATE_LIMITED"),
        (NetworkError("private message"), "failed", "NETWORK_ERROR"),
    ]
    for error, status, code in cases:
        class FailingCollector:
            def collect(self, _task, _runtime, error=error):
                raise error

        store = Store(tmp_path / f"{code}.sqlite3")
        service = TaskService(store, {"jd": FailingCollector()})
        task = store.create_task("jd", "100012043978", None, "auto", 10)
        service.run_now(task["id"])
        result = store.get_task(task["id"])

        assert result["status"] == status
        assert result["error_code"] == code
        assert "private message" not in result["status_reason"]


def test_review_filter_is_stored_with_the_task(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    task = store.create_task(
        "jd",
        "100012043978",
        None,
        "auto",
        10,
        review_filter="negative",
    )

    assert task["review_filter"] == "negative"
