from pathlib import Path

import httpx
import pytest

from review_sampler.collectors.base import VerificationRequired
from review_sampler.collectors.jd import JdCollector
from review_sampler.net import PacedClient, RateLimited


FIXTURE = Path(__file__).parent / "fixtures" / "jd_page_1.json"


class FakeRuntime:
    def __init__(self, saved_count=0):
        self.saved_count = saved_count
        self.cursors = []
        self.batches = []

    def emit(self, reviews, cursor):
        self.batches.append(reviews)
        self.saved_count += len(reviews)
        self.cursors.append(cursor)
        return len(reviews)

    def checkpoint(self):
        return None


def task(limit=10, review_filter="all", cursor=None):
    return {
        "id": "task-1",
        "platform": "jd",
        "product_id": "100012043978",
        "input_url": "https://item.jd.com/100012043978.html",
        "limit": limit,
        "review_filter": review_filter,
        "cursor": cursor,
    }


def client_with(handler):
    return PacedClient(
        min_interval=0,
        max_retries=0,
        transport=httpx.MockTransport(handler),
    )


def test_jd_collects_comments_and_stops_at_limit():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=FIXTURE.read_text())

    runtime = FakeRuntime()
    JdCollector(client_with(handler)).collect(task(limit=2), runtime)

    assert runtime.saved_count == 2
    assert runtime.cursors[-1] == "1"
    assert len(requests) == 1
    params = requests[0].url.params
    assert params["productId"] == "100012043978"
    assert params["score"] == "0"
    assert params["page"] == "1"


def test_empty_comments_ends_collection():
    runtime = FakeRuntime()

    def handler(_request):
        return httpx.Response(
            200,
            text='fetchJSON_comment98vv1941({"comments":[]});',
        )

    JdCollector(client_with(handler)).collect(task(), runtime)

    assert runtime.batches == []


def test_without_max_page_uses_consecutive_empty_page_to_stop():
    calls = 0
    first_page = FIXTURE.read_text().replace('"maxPage":3,', "")

    def handler(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, text=first_page)
        return httpx.Response(
            200,
            text='fetchJSON_comment98vv1941({"comments":[]});',
        )

    runtime = FakeRuntime()
    JdCollector(client_with(handler)).collect(task(limit=20), runtime)

    assert calls == 2
    assert runtime.cursors == ["1", "2"]


def test_changed_jsonp_shell_is_a_parse_error():
    def handler(_request):
        return httpx.Response(
            200,
            text='anotherCallback({"comments":[{"content":"x"}]});',
        )

    with pytest.raises(ValueError):
        JdCollector(client_with(handler)).collect(task(), FakeRuntime())


def test_missing_content_or_author_is_skipped():
    payload = (
        'fetchJSON_comment98vv1941({"comments":['
        '{"id":"1","nickname":"A","content":"保留"},'
        '{"id":"2","nickname":"","content":"缺作者"},'
        '{"id":"3","nickname":"C","content":""}'
        "]});"
    )

    def handler(_request):
        return httpx.Response(200, text=payload)

    runtime = FakeRuntime()
    JdCollector(client_with(handler)).collect(task(limit=10), runtime)

    assert runtime.saved_count == 1
    assert runtime.batches[0][0].content == "保留"


@pytest.mark.parametrize(
    ("review_filter", "score"),
    [("all", "0"), ("negative", "1"), ("positive", "2")],
)
def test_review_filter_is_sent_as_the_jd_score(review_filter, score):
    seen = {}

    def handler(request):
        seen["score"] = request.url.params["score"]
        return httpx.Response(
            200,
            text='fetchJSON_comment98vv1941({"comments":[]});',
        )

    JdCollector(client_with(handler)).collect(
        task(review_filter=review_filter),
        FakeRuntime(),
    )

    assert seen["score"] == score


def test_login_page_requests_human_verification():
    def handler(_request):
        return httpx.Response(
            200,
            text="<html><title>京东登录</title><body>请登录后查看</body></html>",
        )

    with pytest.raises(VerificationRequired):
        JdCollector(client_with(handler)).collect(task(), FakeRuntime())


def test_jd_busy_message_is_reported_as_rate_limited():
    def handler(_request):
        return httpx.Response(200, text="活动太火爆，请稍微再试")

    with pytest.raises(RateLimited):
        JdCollector(client_with(handler)).collect(task(), FakeRuntime())
